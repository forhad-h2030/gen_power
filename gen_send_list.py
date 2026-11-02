#!/usr/bin/env python3
"""Receive a profile from the client and write each line to the generator. The sender gives MHz and mW; the generator
takes Hz and dBm. Set CONVERT_FREQ and CONVERT_POWER below: True converts that line, False sends it as received.
The dwell line is cut to its first value. After each write it prints the generator's error queue and what it holds.
With DRIVE = False nothing is armed or triggered. With DRIVE = True, drive() then plays the list once and switches RF off.
    python gen_send_list.py
"""
import math
import socket
import time
import pyvisa
from PyComm.Tcp import ReceiveLines

SMB_ETHERNET_ADDRESS = "TCPIP0::192.168.24.10::inst0::INSTR"
CONVERT_FREQ = True  # True: the frequencies come in MHz, send Hz. False: send them as received
CONVERT_POWER = True  # True: the powers come in mW, send dBm. False: send them as received
MIN_DBM = -120.0  # 0 mW has no dBm value, so it is sent as this
DRIVE = False  # False: only load the lists. True: after writing them, play one pass (RF on), then RF off
MAX_DBM = 0.0  # with DRIVE on, no pass starts if any power is above this (dBm). Raise it on purpose only
USE_MIN_DWELL = False  # True: use the generator's own minimum dwell, in the line sent and in the wait. False: the sender's
RUNNING_BIT = 8  # bit of STATus:OPERation:CONDition? that is set while a list pass runs (seen with gen_pass_test.py)
POLL_S = 0.1  # how often drive() asks the generator whether the pass is still running
DONE_LIMIT_S = 5.0  # a pass is waited for at most its calculated length plus this, then RF goes off anyway
LIST_NAME = "gen_profile"  # the generator list that the lines below are written into
# commands (short form, as sent) whose setting is read back with the same name plus "?"
READBACK = {"SOUR:LIST:FREQ", "SOUR:LIST:POW", "SOUR:LIST:DWEL", "SOUR:POW:LEV", "SOUR:FREQ", "OUTP:STAT"}


def mw_to_dbm(mw):
    """mW to dBm. 0 mW has no dBm value, so it becomes MIN_DBM. A negative number is not a power in mW."""
    if mw < 0:
        raise ValueError(f"{mw} is not a power in mW")
    return max(10 * math.log10(mw), MIN_DBM) if mw > 0 else MIN_DBM


def mw_to_test_profile(powers_mw):
    """Scaling the mW[] list to 0 to 1 dBm[], for test only. The largest value becomes 1 and zero stays 0."""
    if any(p < 0 for p in powers_mw):
        raise ValueError("a power in mW cannot be negative")
    top = max(powers_mw)
    if top <= 0:
        raise ValueError("all powers are zero, nothing to scale")
    return [p / top for p in powers_mw]


def mark(smb, t_msg, label):
    """Print the time since the message arrived, then the generator's RF state and its operation status register."""
    t = time.monotonic() - t_msg  # taken first, so the two queries below do not shift it
    try:
        rf = smb.query("OUTPut:STATe?").strip()
        operation = smb.query("STATus:OPERation:CONDition?").strip()
    except pyvisa.VisaIOError as e:
        rf = operation = f"no answer ({e})"
    print(f"  t = {t:8.3f} s  {label}: RF {rf}, operation status {operation}")
    return t


def running(smb):
    """True while the generator reports a list pass running (RUNNING_BIT of its operation status)."""
    return int(smb.query("STATus:OPERation:CONDition?")) & RUNNING_BIT != 0


def drive(smb, n_points, first_dbm, dwell_s, t_msg):
    """Play the lists written above once, then leave RF off. The generator refuses list mode while RF is off,
    so RF goes on first. The pass is over when the generator stops reporting it running. Any error stops the pass,
    and RF is switched off whatever happens.
    t_msg is the time the message arrived (time.monotonic()); the times printed are counted from it."""
    t_trigger = 0.0
    try:
        for q in ("FREQuency", "POWer"):
            if int(smb.query(f"SOURce:LIST:{q}:POINts?")) != n_points:
                raise RuntimeError(f"the generator holds the wrong number of {q} points")
        for command in ("OUTPut:STATe OFF",
                        "SOURce:FREQuency:MODE CW",
                        "SOURce:POWer:MODE CW",
                        f"SOURce:POWer:LEVel {first_dbm:.4f}",  # RF starts at the first list power
                        "SOURce:LIST:MODE AUTO",
                        "SOURce:LIST:TRIGger:SOURce SINGle",  # one pass per trigger, no repeat
                        "OUTPut:STATe ON",
                        "SOURce:FREQuency:MODE LIST",
                        "SOURce:LIST:TRIGger:EXECute"):  # starts the pass
            print("  drive >", command)
            smb.write(command)
            if command.endswith("EXECute"):
                t_trigger = mark(smb, t_msg, "trigger sent")
            error = smb.query("SYSTem:ERRor?").strip()
            if not error.startswith("0"):
                raise RuntimeError(f"{command!r} rejected: {error}")
        expected = n_points * dwell_s
        print(f"driving {n_points} bins for {expected:g} s")
        deadline = t_msg + t_trigger + expected + DONE_LIMIT_S
        while running(smb):
            if time.monotonic() > deadline:
                raise RuntimeError(f"the generator still reports the pass running {DONE_LIMIT_S:g} s after its end")
            time.sleep(POLL_S)
        t_end = mark(smb, t_msg, "pass done")  # the generator has stopped reporting the pass running
        passed = t_end - t_trigger
        if passed < expected / 2:
            print("  warning: the running flag was not seen, the pass may not have started")
        print(f"  message to trigger {t_trigger:.3f} s, trigger to pass done {passed:.3f} s "
              f"(the bins alone: {expected:.3f} s)")
        print("pass done, RF off")
    except (RuntimeError, pyvisa.VisaIOError) as e:
        print(f"not driven, RF off: {e}")
    finally:
        smb.write("OUTPut:STATe OFF")
        mark(smb, t_msg, "RF off")


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
    min_dwell = 0.0
    if USE_MIN_DWELL:
        min_dwell = float(smb.query("SOURce:LIST:DWELl? MIN"))  # the shortest dwell the generator allows
        print(f"using the generator's minimum dwell: {min_dwell:g} s")

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
            print("  t =    0.000 s  message received")

            n_points, powers, dwell = 0, [], 0.0  # what drive() needs, taken from the lines below
            for line in msg.splitlines():
                cmd, _, arg = line.strip().partition(" ")
                values = [v.strip() for v in arg.split(",") if v.strip()]

                if cmd.upper() == "SOUR:LIST:FREQ":
                    n_points = len(values)

                if CONVERT_FREQ and cmd.upper() == "SOUR:LIST:FREQ":
                    line = f"{cmd} " + ",".join(f"{float(v) * 1e6:.0f}" for v in values)

                if cmd.upper() == "SOUR:LIST:POW":
                    try:
                        powers = [float(v) for v in values]
                        if CONVERT_POWER:
                            powers = [mw_to_dbm(p) for p in powers]
                            # for a test, use this line instead of the one above:
                            # powers = mw_to_test_profile(powers)
                            line = f"{cmd} " + ",".join(f"{p:.4f}" for p in powers)
                    except ValueError as e:
                        print(f"  power line not sent: {e}")
                        powers = []  # no pass is driven from a power list that was not sent
                        continue

                if cmd.upper() == "SOUR:LIST:DWEL" and values:
                    try:
                        dwell = float(values[0])
                    except ValueError:
                        dwell = 0.0  # no pass is driven; the generator will refuse the line itself
                    if USE_MIN_DWELL:
                        print(f"  note: the sender gave {values[0]}, using the generator's minimum {min_dwell:g} s")
                        dwell = min_dwell
                        line = f"{cmd} {dwell:g}"

                if cmd.upper() == "SOUR:LIST:DWEL" and len(values) > 1 and not USE_MIN_DWELL:
                    if len(set(values)) > 1:
                        print("  note: the dwell values differ, only the first is sent")
                    line = f"{cmd} {values[0]}"

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
        soc_svr.close()
        smb.close()


if __name__ == "__main__":
    main()
