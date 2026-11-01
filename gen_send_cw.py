#!/usr/bin/env python3
import math
import socket
import time
import pyvisa
from PyComm.Tcp import ReceiveLines

SMB_ETHERNET_ADDRESS = "TCPIP0::192.168.24.10::inst0::INSTR"
CONVERT_FREQ = True  # True: the frequencies come in MHz, send Hz. False: send them as received
CONVERT_POWER = True  # True: the powers come in mW, send dBm. False: send them as received
MIN_DBM = -120.0  # 0 mW has no dBm value, so it is sent as this
DRIVE = False  # False: only read and check the message. True: play one pass (RF on), then RF off
MAX_DBM = 0.0  # with DRIVE on, no pass starts if any power is above this (dBm). Raise it on purpose only


def mw_to_dbm(mw):
    """mW to dBm. 0 mW has no dBm value, so it becomes MIN_DBM. A negative number is not a power in mW."""
    if mw < 0:
        raise ValueError(f"{mw} is not a power in mW")
    return max(10 * math.log10(mw), MIN_DBM) if mw > 0 else MIN_DBM


def drive_cw(smb, freqs_hz, powers_dbm, dwell_s):
    """Play the profile once in CW mode, then leave RF off. Each bin is written at its own start time, counted from one
    start, so the delays do not add up. RF is switched off whatever happens."""
    n = len(freqs_hz)
    try:
        for command in ("OUTPut:STATe OFF",
                        "SOURce:FREQuency:MODE CW",
                        "SOURce:POWer:MODE CW",
                        f"SOURce:FREQuency:CW {freqs_hz[0]:.0f}",  # RF starts at the first bin
                        f"SOURce:POWer:LEVel {powers_dbm[0]:.4f}",
                        "OUTPut:STATe ON"):
            smb.write(command)
        smb.query("*OPC?")  # the generator has finished applying the settings
        print(f"driving {n} bins, {dwell_s:g} s each, expected {n * dwell_s:g} s")

        start = time.monotonic()
        worst_late = 0.0
        for i in range(n):
            due = start + i * dwell_s
            time.sleep(max(0.0, due - time.monotonic()))
            if i:  # the first bin is already set
                smb.write(f"SOURce:FREQuency:CW {freqs_hz[i]:.0f}")
                smb.write(f"SOURce:POWer:LEVel {powers_dbm[i]:.4f}")
                worst_late = max(worst_late, time.monotonic() - due)
        time.sleep(max(0.0, start + n * dwell_s - time.monotonic()))  # the last bin gets its full dwell
        elapsed = time.monotonic() - start
        print(f"pass took {elapsed:.3f} s, expected {n * dwell_s:.3f} s, {elapsed - n * dwell_s:+.3f} s")
        print(f"slowest bin change was {worst_late * 1000:.0f} ms after its due time")

        for _ in range(10):  # the generator's errors from the whole pass
            error = smb.query("SYSTem:ERRor?").strip()
            if error.startswith("0"):
                break
            print("  generator error queue:", error)
        print("pass done, RF off")
    except pyvisa.VisaIOError as e:
        print(f"pass stopped, RF off: {e}")
    finally:
        smb.write("OUTPut:STATe OFF")


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
    smb.write("*CLS")  # clear old errors, so the error queue shows only this pass

    try:
        while True:
            try:
                soc, addr = soc_svr.accept()
            except socket.timeout:
                continue
            print("------------------------------------------------------------")
            print("---- Message ----")

            msg = ReceiveLines(soc)
            soc.close()  # the pass below can take minutes

            freqs, powers, dwell = [], [], 0.0
            try:
                for line in msg.splitlines():
                    cmd, _, arg = line.strip().partition(" ")
                    values = [v.strip() for v in arg.split(",") if v.strip()]

                    if cmd.upper() == "SOUR:LIST:FREQ":
                        freqs = [float(v) * 1e6 if CONVERT_FREQ else float(v) for v in values]

                    if cmd.upper() == "SOUR:LIST:POW":
                        powers = [mw_to_dbm(float(v)) if CONVERT_POWER else float(v) for v in values]

                    if cmd.upper() == "SOUR:LIST:DWEL" and values:
                        if len(set(values)) > 1:
                            print("  note: the dwell values differ, only the first is used")
                        dwell = float(values[0])
            except ValueError as e:
                print(f"message not used: {e}")
                continue

            print(f"received {len(freqs)} frequencies, {len(powers)} powers, dwell {dwell:g} s")
            if not (freqs and len(freqs) == len(powers) and dwell > 0):
                print("not driven: need the same number of frequencies and powers, and a dwell above 0")
            elif not DRIVE:
                print("not driven: DRIVE is False")
            elif max(powers) > MAX_DBM:
                print(f"not driven: {max(powers):.2f} dBm is above MAX_DBM {MAX_DBM:g} dBm")
            else:
                drive_cw(smb, freqs, powers, dwell)
    except KeyboardInterrupt:
        print("Stopped.")
    finally:
        soc_svr.close()
        smb.close()


if __name__ == "__main__":
    main()
