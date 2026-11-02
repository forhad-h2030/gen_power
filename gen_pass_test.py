#!/usr/bin/env python3
"""Play a test list once on the generator and see whether the pass completes. The list is like the real profile: the
frequencies step from START_HZ by STEP_HZ, and the level changes on every bin (or stays CONSTANT_DBM with --constant).
It goes into its own list "gen_test". The queries below are asked every POLL_S seconds, and a line is printed whenever
an answer changes. At the end it says COMPLETE or NOT complete (the index must reach the last bin and the error queue
must be clean). RF is off at the end. Close the other scripts that use the generator before running it.
    python gen_pass_test.py                    # 500 bins, 5 ms dwell
    python gen_pass_test.py 500 0.002          # 500 bins, 2 ms dwell
    python gen_pass_test.py 500 0.002 --constant
"""
import argparse
import time
import pyvisa

SMB_ETHERNET_ADDRESS = "TCPIP0::192.168.24.10::inst0::INSTR"
LIST_NAME = "gen_test"  # a list of its own, so the profile list that gen_send_list.py uses is not touched
START_HZ = 26.6392e6  # the real profile runs from about 26.6 to 38.7 MHz in about 24 kHz steps
STEP_HZ = 24.2e3
LEVELS_DBM = (-40.0, -20.0, -30.0, -10.0)  # cycled, so the level changes on every bin
CONSTANT_DBM = -30.0
RUNNING_BIT = 8  # bit of STATus:OPERation:CONDition? that is set while a list pass runs
POLL_S = 0.05
AFTER_S = 1.0  # keep asking this long after the expected end of the pass
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


def is_running(status):
    try:
        return int(status) & RUNNING_BIT != 0
    except ValueError:
        return False


def main():
    p = argparse.ArgumentParser(description="Play a test list once and check that the pass completes.")
    p.add_argument("bins", nargs="?", type=int, default=500, help="number of bins (default 500)")
    p.add_argument("dwell", nargs="?", type=float, default=0.005, help="dwell per bin, s (default 0.005)")
    p.add_argument("--constant", action="store_true", help=f"hold the level at {CONSTANT_DBM:g} dBm on every bin")
    a = p.parse_args()

    freqs = [START_HZ + i * STEP_HZ for i in range(a.bins)]
    if a.constant:
        powers = [CONSTANT_DBM] * a.bins
    else:
        powers = [LEVELS_DBM[i % len(LEVELS_DBM)] for i in range(a.bins)]
    expected = a.bins * a.dwell

    smb = pyvisa.ResourceManager().open_resource(SMB_ETHERNET_ADDRESS, timeout=5000)
    smb.read_termination = '\n'
    smb.write_termination = '\n'
    try:
        smb.write("*CLS")
        for command in (f'SOURce:LIST:SELect "{LIST_NAME}"',
                        "SOURce:LIST:FREQuency " + ",".join(f"{f:.0f}" for f in freqs),
                        "SOURce:LIST:POWer " + ",".join(f"{pw:.4f}" for pw in powers),
                        f"SOURce:LIST:DWELl {a.dwell:g}",
                        "OUTPut:STATe OFF",
                        "SOURce:FREQuency:MODE CW",
                        "SOURce:POWer:MODE CW",
                        f"SOURce:POWer:LEVel {powers[0]:.4f}",
                        "SOURce:LIST:MODE AUTO",
                        "SOURce:LIST:TRIGger:SOURce SINGle",
                        "OUTPut:STATe ON",
                        "SOURce:FREQuency:MODE LIST"):
            send(smb, command)

        print(f"queries: {QUERIES}")
        print(f"{a.bins} bins, dwell {a.dwell:g} s, expected pass {expected:g} s, "
              f"level {'constant' if a.constant else 'changing on every bin'}")
        last = [ask(smb, q) for q in QUERIES]
        print(f"t = {0:7.3f} s  before the trigger: {last}")

        smb.write("SOURce:LIST:TRIGger:EXECute")
        start = time.monotonic()
        t_clear = None  # when the running flag was seen to clear
        seen_running = False
        while time.monotonic() - start < expected + AFTER_S:
            answers = [ask(smb, q) for q in QUERIES]
            t = time.monotonic() - start
            if answers != last:
                print(f"t = {t:7.3f} s  {answers}")
                last = answers
            if is_running(answers[1]):
                seen_running = True
            elif seen_running and t_clear is None:
                t_clear = t
            time.sleep(POLL_S)

        error = ask(smb, "SYSTem:ERRor?")
        print(f"index reached {last[2]} of {a.bins - 1}")
        print("error queue:", error)
        complete = last[2] == str(a.bins - 1) and error.startswith("0")
        cleared = f"{t_clear:.3f} s" if t_clear is not None else "never seen"
        print(f"pass {'COMPLETE' if complete else 'NOT complete'}: the running flag cleared at {cleared}, "
              f"expected {expected:g} s")
    finally:
        smb.write("OUTPut:STATe OFF")
        smb.close()


if __name__ == "__main__":
    main()
