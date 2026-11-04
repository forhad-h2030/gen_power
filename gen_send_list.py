#!/usr/bin/env python3
"""Receive a profile from the client and write each line to the generator. The sender gives MHz and mW; the generator
takes Hz and dBm. Set CONVERT_FREQ and CONVERT_POWER below: True converts that line, False sends it as received.
The dwell is always DWELL_S below; the sender's dwell is not used.
Bins more than MIN_DB below the largest power of the profile are dropped (frequency and power together), so the pass is shorter.
After each write it prints the generator's error queue and what it holds.
With DRIVE = False nothing is armed or triggered. With DRIVE = True, drive() then plays the list once, waits until the
generator says the pass is over, switches RF off and prints the times.
    python gen_send_list.py
"""
import csv
import math
import socket
import time
from pathlib import Path
import pyvisa
from PyComm.Tcp import ReceiveLines

SMB_ETHERNET_ADDRESS = "TCPIP0::192.168.24.10::inst0::INSTR"
CONVERT_FREQ = True  # True: the frequencies come in MHz, send Hz. False: send them as received
CONVERT_POWER = True  # True: the powers come in mW, send dBm. False: send them as received
MIN_DBM = -120.0  # 0 mW has no dBm value, so it is sent as this
PEAK_DBM = 0.0  # the largest power of the profile goes out at this level (dBm), every other bin below it by its ratio
MIN_DB = -17.0  # a bin more than this many dB below the largest power of the profile is dropped, so the pass is shorter. None keeps every bin
DRIVE = True  # False: only load the lists. True: after writing them, play one pass (RF on), then RF off
REPEAT = False  # with DRIVE on, True: the list runs again and again (to watch it on the tinySA), RF stays on until the next message or Ctrl+C
MAX_DBM = 1.0  # with DRIVE on, no pass starts if any power is above this (dBm). Raise it on purpose only
DWELL_S = 0.0013  # dwell per bin, s, for every pass. 500 bins completed 5 of 5 times at 1.3 ms, and failed at 1.2 ms
RUNNING_BIT = 8  # bit of STATus:OPERation:CONDition? that is set while a list pass runs (seen with gen_pass_test.py)
POLL_S = 0.1  # how often drive() asks the generator whether the pass is still running
LIST_NAME = "gen_profile"  # the generator list that the lines below are written into
PROFILE_FILE = Path(__file__).resolve().parent / "last_profile.csv"  # every bin of the last message, for gen_readback.py
# commands (short form, as sent) whose setting is read back with the same name plus "?"
READBACK = {"SOUR:LIST:FREQ", "SOUR:LIST:POW", "SOUR:LIST:DWEL", "SOUR:POW:LEV", "SOUR:FREQ", "OUTP:STAT"}


def mw_to_dbm(mw):
    """mW to dBm. 0 mW has no dBm value, so it becomes MIN_DBM. A negative number is not a power in mW."""
    if mw < 0:
        raise ValueError(f"{mw} is not a power in mW")
    return max(10 * math.log10(mw), MIN_DBM) if mw > 0 else MIN_DBM


def mw_to_relative_dbm(powers_mw):
    """The largest power goes out at PEAK_DBM and every other by its ratio to it, so the output power has the shape of
    the profile in mW (a bin at 7% of the peak is 11.5 dB below it). 0 mW becomes MIN_DBM."""
    if any(p < 0 for p in powers_mw):
        raise ValueError("a power in mW cannot be negative")
    top = max(powers_mw)
    if top <= 0:
        raise ValueError("all powers are zero, nothing to scale")
    return [max(PEAK_DBM + 10 * math.log10(p / top), MIN_DBM) if p > 0 else MIN_DBM for p in powers_mw]


def mw_to_test_profile(powers_mw):
    """Scaling the mW[] list to 0 to 1 dBm[], for test only. The largest value becomes 1 and zero stays 0."""
    if any(p < 0 for p in powers_mw):
        raise ValueError("a power in mW cannot be negative")
    top = max(powers_mw)
    if top <= 0:
        raise ValueError("all powers are zero, nothing to scale")
    return [p / top for p in powers_mw]


def message_lists(msg):
    """The values of each line of the message, by command name (upper case)."""
    lists = {}
    for line in msg.splitlines():
        cmd, _, arg = line.strip().partition(" ")
        lists[cmd.upper()] = [v.strip() for v in arg.split(",") if v.strip()]
    return lists


def save_profile(msg, keep):
    """Write every bin of the message to PROFILE_FILE, before any bin is dropped, so gen_readback.py can show the whole
    profile next to what the generator holds. Columns: frequency (MHz), power as received, power divided by the
    largest power (0 to 1), the level in dBm the bin gets (as sent, for a dropped bin as it would have been), and
    whether the bin was sent."""
    lists = message_lists(msg)
    freqs, powers = lists.get("SOUR:LIST:FREQ"), lists.get("SOUR:LIST:POW")
    try:
        if not freqs or len(freqs) != len(powers or []):
            raise ValueError("no matching frequency and power lists")
        f_mhz = [float(f) if CONVERT_FREQ else float(f) / 1e6 for f in freqs]
        p = [float(v) for v in powers]
        top = max(p) or 1.0
        dbm = mw_to_relative_dbm(p) if CONVERT_POWER else p
        with open(PROFILE_FILE, "w", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(["freq_mhz", "power_received", "power_normalized", "power_dbm", "sent"])
            for i, (fm, pw, d) in enumerate(zip(f_mhz, p, dbm)):
                writer.writerow([f"{fm:.6f}", f"{pw:.6g}", f"{pw / top:.6g}", f"{d:.4f}", int(keep is None or keep[i])])
    except (OSError, ValueError) as e:
        print(f"  full profile not saved: {e}")


def quiet_bins(msg):
    """For each bin of the message, True if it stays and False if its power is more than MIN_DB below the largest power.
    None when nothing is dropped: MIN_DB is None, a list is missing, the lists differ in length or a power is not a number."""
    lists = message_lists(msg)
    freqs, powers = lists.get("SOUR:LIST:FREQ"), lists.get("SOUR:LIST:POW")
    if MIN_DB is None or not freqs or not powers:
        return None
    if len(freqs) != len(powers):
        print(f"  no bins dropped: {len(freqs)} frequencies but {len(powers)} powers")
        return None
    try:
        values = [float(p) for p in powers]
        cut = max(values) * 10 ** (MIN_DB / 10)  # the power MIN_DB below the largest one
        keep = [p >= cut and p > 0 for p in values]  # a bin at 0 is never kept
    except ValueError:
        return None  # the power line is reported below, as before
    return keep if not all(keep) else None


def running(smb):
    """True while the generator reports a list pass running (RUNNING_BIT of its operation status)."""
    return int(smb.query("STATus:OPERation:CONDition?")) & RUNNING_BIT != 0


def drive(smb, n_points, first_dbm, dwell_s, t_msg):
    """Play the lists written above once, then leave RF off. The generator refuses list mode while RF is off, so RF
    goes on first. The pass is over when the generator stops reporting it running, and its error queue then says if
    it was cut short. t_msg is the time the message arrived (time.monotonic()). RF is switched off whatever happens,
    except with REPEAT, where the list keeps running and RF stays on."""
    repeating = False
    try:
        for command in ("OUTPut:STATe OFF",
                        "SOURce:FREQuency:MODE CW",
                        "SOURce:POWer:MODE CW",
                        f"SOURce:POWer:LEVel {first_dbm:.4f}",  # RF starts at the first list power
                        "SOURce:LIST:MODE AUTO",
                        f"SOURce:LIST:TRIGger:SOURce {'AUTO' if REPEAT else 'SINGle'}",  # AUTO repeats, SINGle is one pass per trigger
                        "OUTPut:STATe ON",
                        "SOURce:FREQuency:MODE LIST") + (() if REPEAT else ("SOURce:LIST:TRIGger:EXECute",)):  # EXECute starts the pass
            smb.write(command)
        t_trigger = time.monotonic()
        print(f"driving {n_points} bins, expected {n_points * dwell_s:g} s")
        if REPEAT:
            repeating = True
            print("repeating the list, RF stays on until the next message or Ctrl+C")
            return

        while running(smb):
            time.sleep(POLL_S)
        t_done = time.monotonic()

        print(f"pass took {t_done - t_trigger:.3f} s")
        print(f"message to trigger {t_trigger - t_msg:.3f} s, message to pass done {t_done - t_msg:.3f} s")
        error = smb.query("SYSTem:ERRor?").strip()
        print("error queue:", error)
        if not error.startswith("0"):
            print("pass NOT complete")
    except pyvisa.VisaIOError as e:
        print(f"pass stopped: {e}")
    finally:
        if not repeating:
            smb.write("OUTPut:STATe OFF")
            print("RF off")


def main():
    host_svr = socket.gethostname()
    port_svr = 11111
    print(f"Wait on {host_svr}:{port_svr} (Ctrl+C to quit). Convert: freq {CONVERT_FREQ}, power {CONVERT_POWER}.")

    soc_svr = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    soc_svr.bind((host_svr, port_svr))
    soc_svr.listen(1)  # N of connections at once
    soc_svr.settimeout(1.0)  # accept() gives up every second, so Ctrl+C is noticed on Windows

    smb = pyvisa.ResourceManager().open_resource(SMB_ETHERNET_ADDRESS, timeout=5000)
    smb.read_termination = '\n'
    smb.write_termination = '\n'

    try:
        print(f"verified gen base power unit: {smb.query('UNIT:POWer?').strip()}")
    except pyvisa.VisaIOError as e:
        print("power unit query failed: ", e)
    smb.write("*CLS")  # clear old errors, so the error queue below shows only this message
    smb.write(f'SOURce:LIST:SELect "{LIST_NAME}"')  # the lists below go into this list, which drive() plays
    print(f"dwell for every pass: {DWELL_S:g} s")

    try:
        while True:
            try:
                soc, addr = soc_svr.accept()
            except socket.timeout:
                continue
            print("------------------------------------------------------------")
            print("---- Message ----")

            msg = ReceiveLines(soc)
            t_msg = time.monotonic()  # the times printed by drive() are counted from here

            keep = quiet_bins(msg)  # which bins stay (True), or None when nothing is dropped
            save_profile(msg, keep)
            if keep is not None:
                print(f"bins kept: {sum(keep)} of {len(keep)} (more than {abs(MIN_DB):g} dB below the peak dropped)")
                if not any(keep):
                    print("not sent: no bin is left after the MIN_DB cut")
                    soc.close()
                    continue

            n_points, powers, dwell = 0, [], 0.0  # what drive() needs, taken from the lines below
            for line in msg.splitlines():
                cmd, _, arg = line.strip().partition(" ")
                values = [v.strip() for v in arg.split(",") if v.strip()]

                if keep is not None and cmd.upper() in ("SOUR:LIST:FREQ", "SOUR:LIST:POW"):
                    values = [v for v, k in zip(values, keep) if k]
                    line = f"{cmd} " + ",".join(values)

                if cmd.upper() == "SOUR:LIST:FREQ":
                    n_points = len(values)

                if CONVERT_FREQ and cmd.upper() == "SOUR:LIST:FREQ":
                    line = f"{cmd} " + ",".join(f"{float(v) * 1e6:.0f}" for v in values)

                if cmd.upper() == "SOUR:LIST:POW":
                    try:
                        powers = [float(v) for v in values]
                        if CONVERT_POWER:
                            powers = mw_to_relative_dbm(powers)  # the peak goes out at PEAK_DBM, the others by their ratio
                            # for real powers, use this line instead of the one above:
                            # powers = [mw_to_dbm(p) for p in powers]
                            # for the old test (the list scaled to 0 to 1 dBm):
                            # powers = mw_to_test_profile(powers)
                            line = f"{cmd} " + ",".join(f"{p:.4f}" for p in powers)
                    except ValueError as e:
                        print(f"  power line not sent: {e}")
                        powers = []  # no pass is driven from a power list that was not sent
                        continue

                if cmd.upper() == "SOUR:LIST:DWEL":
                    print(f"  note: the sender's dwell is not used, sending {DWELL_S:g} s")
                    dwell = DWELL_S
                    line = f"{cmd} {dwell:g}"

                print("line command goes into generator: ", line)
                smb.write(line)
                print("  generator error queue:", smb.query("SYSTem:ERRor?").strip())
                if cmd.upper() in READBACK:
                    try:
                        print("  generator now holds: ", smb.query(cmd + "?").strip())
                    except pyvisa.VisaIOError as e:
                        print("  readback failed:", e)
            soc.close()  # the pass below can take minutes

            if DRIVE and n_points and powers and dwell:
                if max(powers) > MAX_DBM:
                    print(f"not driven: {max(powers):.2f} dBm is above MAX_DBM {MAX_DBM:g} dBm")
                else:
                    drive(smb, n_points, powers[0], dwell, t_msg)
    except KeyboardInterrupt:
        print("Stopped.")
    finally:
        if DRIVE and REPEAT:  # the list may still be running
            try:
                smb.write("OUTPut:STATe OFF")
                print("RF off")
            except pyvisa.VisaIOError:
                pass
        soc_svr.close()
        smb.close()


if __name__ == "__main__":
    main()
