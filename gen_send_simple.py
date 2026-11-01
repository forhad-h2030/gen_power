#!/usr/bin/env python3
"""Receive a profile from the client and write each line to the generator. The sender gives MHz and mW; the generator
takes Hz and dBm. Set CONVERT_FREQ and CONVERT_POWER below: True converts that line, False sends it as received.
The dwell line is cut to its first value. After each write it prints the generator's error queue and what it holds.
Nothing is armed or triggered.
    python gen_send_simple.py
"""
import math
import socket
import pyvisa
from PyComm.Tcp import ReceiveLines

SMB_ETHERNET_ADDRESS = "TCPIP0::192.168.24.10::inst0::INSTR"
CONVERT_FREQ = True  # True: the frequencies come in MHz, send Hz. False: send them as received
CONVERT_POWER = True  # True: the powers come in mW, send dBm. False: send them as received
MIN_DBM = -120.0  # 0 mW has no dBm value, so it is sent as this
# commands (short form, as sent) whose setting is read back with the same name plus "?"
READBACK = {"SOUR:LIST:FREQ", "SOUR:LIST:POW", "SOUR:LIST:DWEL", "SOUR:POW:LEV", "SOUR:FREQ", "OUTP:STAT"}


def mw_to_dbm(mw):
    """mW to dBm. 0 mW has no dBm value, so it becomes MIN_DBM. A negative number is not a power in mW."""
    if mw < 0:
        raise ValueError(f"{mw} is not a power in mW")
    return max(10 * math.log10(mw), MIN_DBM) if mw > 0 else MIN_DBM


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

    try:
        while True:
            try:
                soc, addr = soc_svr.accept()
            except socket.timeout:
                continue
            print("------------------------------------------------------------")
            print("---- Message ----")

            msg = ReceiveLines(soc)

            for line in msg.splitlines():
                cmd, _, arg = line.strip().partition(" ")
                values = [v.strip() for v in arg.split(",") if v.strip()]

                if CONVERT_FREQ and cmd.upper() == "SOUR:LIST:FREQ":
                    line = f"{cmd} " + ",".join(f"{float(v) * 1e6:.0f}" for v in values)

                if CONVERT_POWER and cmd.upper() == "SOUR:LIST:POW":
                    try:
                        line = f"{cmd} " + ",".join(f"{mw_to_dbm(float(v)):.4f}" for v in values)
                    except ValueError as e:
                        print(f"  power line not sent: {e}")
                        continue

                if cmd.upper() == "SOUR:LIST:DWEL" and len(values) > 1:
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
            soc.close()
    except KeyboardInterrupt:
        print("Stopped.")
    finally:
        soc_svr.close()
        smb.close()


if __name__ == "__main__":
    main()
