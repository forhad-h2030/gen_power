#!/usr/bin/env python3
import time
import pyvisa

SMB_ETHERNET_ADDRESS = "TCPIP0::192.168.24.10::inst0::INSTR"
LIST_NAME = "gen_test"  # a list of its own, so the profile list that gen_send_list.py uses is not touched
N_BINS = 10
DWELL_S = 0.5  # N_BINS * DWELL_S = 5 s, long enough to see a change at the start and at the end
LEVEL_DBM = -30.0
FREQ_HZ = [213e6 + i * 100e3 for i in range(N_BINS)]
POLL_S = 0.1
AFTER_S = 3.0  # keep asking this long after the expected end of the pass
QUERIES = ["OUTPut:STATe?", "STATus:OPERation:CONDition?", "SOURce:LIST:INDex?", "SOURce:FREQuency?"]


def ask(smb, query):
    try:
        return smb.query(query).strip()
    except pyvisa.VisaIOError:
        return "no answer"


def send(smb, command):
    """Write one command and stop if the generator's error queue is not clean."""
    smb.write(command)
    error = smb.query("SYSTem:ERRor?").strip()
    if not error.startswith("0"):
        raise RuntimeError(f"{command!r} rejected: {error}")


def main():
    smb = pyvisa.ResourceManager().open_resource(SMB_ETHERNET_ADDRESS, timeout=5000)
    smb.read_termination = '\n'
    smb.write_termination = '\n'
    try:
        smb.write("*CLS")
        for command in (f'SOURce:LIST:SELect "{LIST_NAME}"',
                        "SOURce:LIST:FREQuency " + ",".join(f"{f:.0f}" for f in FREQ_HZ),
                        "SOURce:LIST:POWer " + ",".join(f"{LEVEL_DBM:.4f}" for _ in FREQ_HZ),
                        f"SOURce:LIST:DWELl {DWELL_S:g}",
                        "OUTPut:STATe OFF",
                        "SOURce:FREQuency:MODE CW",
                        "SOURce:POWer:MODE CW",
                        f"SOURce:POWer:LEVel {LEVEL_DBM:.4f}",
                        "SOURce:LIST:MODE AUTO",
                        "SOURce:LIST:TRIGger:SOURce SINGle",
                        "OUTPut:STATe ON",
                        "SOURce:FREQuency:MODE LIST"):
            send(smb, command)

        print(f"queries: {QUERIES}")
        print(f"expected pass: {N_BINS * DWELL_S:g} s")
        last = [ask(smb, q) for q in QUERIES]
        print(f"t =  {0:6.3f} s  before the trigger: {last}")

        smb.write("SOURce:LIST:TRIGger:EXECute")
        start = time.monotonic()
        while time.monotonic() - start < N_BINS * DWELL_S + AFTER_S:
            answers = [ask(smb, q) for q in QUERIES]
            t = time.monotonic() - start
            if answers != last:
                print(f"t = {t:7.3f} s  {answers}")
                last = answers
            time.sleep(POLL_S)
        print(f"still {last} at t = {time.monotonic() - start:.3f} s, the end of the test")
        print("error queue:", ask(smb, "SYSTem:ERRor?"))
    finally:
        smb.write("OUTPut:STATe OFF")
        smb.close()


if __name__ == "__main__":
    main()
