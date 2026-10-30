#!/usr/bin/env python3
"""FROM NMR (the model side): builds a power profile (frequency in Hz, power, dwell in s) and sends it to to_gen_server.py.
The profiles are fixed lists in PROFILES below, standing in for RF_Model.py (Infer()) that will send them later.
Set UNIT below to "dBm" or "mW" to say what the power numbers are. The wire is always dBm: mW is converted here.
Zero power (0 mW, or -inf dBm) and anything at or below -120 dBm is dropped, with its frequency and dwell, before sending.
The profile is checked before it leaves this computer.
    python from_nmr_client.py                # send the default profile 'span'
    python from_nmr_client.py one three      # send profile 'one', wait, then 'three'
    python from_nmr_client.py zeros          # five bins, two of them zero power: three are sent
"""
import argparse
import socket
import time

from PyComm.Power import from_power, to_lines, validate
from PyComm.Tcp import SendLines

UNIT = "dBm"  # "dBm" or "mW": the unit of the power numbers in PROFILES (and of what RF_Model will send)
WAIT_S = 10  # time to watch the generator between profiles

F5 = [212.8e6, 212.9e6, 213e6, 213.1e6, 213.2e6]
# name: (frequency in Hz, power in UNIT, dwell in s: one number or one per bin)
PROFILES_DBM = {
    "one": ([213e6], [-40], 1.0),
    "three": ([213e6, 214e6, 215e6], [-40, -45, -42], [0.5, 0.5, 1.0]),
    "span": (F5, [-40, -45, -50, -45, -40], 0.5),
    "zeros": (F5, [-40, float("-inf"), -50, -150, -40], 0.5),
    "silent": ([213e6, 214e6], [float("-inf")] * 2, 1.0),  # nothing to play: refused here
    "bad": ([213e6, 214e6], [-40], 1.0),  # lengths differ: refused here, before anything is sent
}
PROFILES_MW = {
    "one": ([213e6], [1e-4], 1.0),
    "three": ([213e6, 214e6, 215e6], [1e-4, 3.2e-5, 6.3e-5], [0.5, 0.5, 1.0]),
    "span": (F5, [1e-4, 3.2e-5, 1e-5, 3.2e-5, 1e-4], 0.5),
    "zeros": (F5, [1e-4, 0, 1e-5, 1e-15, 1e-4], 0.5),
    "silent": ([213e6, 214e6], [0, 0], 1.0),
    "bad": ([213e6, 214e6], [1e-4], 1.0),
}
PROFILES = {"dBm": PROFILES_DBM, "mW": PROFILES_MW}[UNIT]


def build(name):
    """The profile called name, with zero-power bins dropped and the rest checked."""
    profile, dropped = from_power(*PROFILES[name], unit=UNIT)
    if dropped:
        print(f"dropped {dropped} of {dropped + len(profile['freq_hz'])} bins with zero power")
    validate(profile)
    return profile


def main():
    p = argparse.ArgumentParser(description="Send power profiles to to_gen_server.py.")
    p.add_argument("names", nargs="*", default=["span"], choices=list(PROFILES), help="profiles to send, in order")
    p.add_argument("--host", default=socket.gethostname(), help="the server's address (default: this machine)")
    p.add_argument("--port", type=int, default=11111)
    p.add_argument("--wait", type=float, default=WAIT_S, help="seconds to wait after each profile (default 10)")
    a = p.parse_args()

    try:
        profiles = [build(name) for name in a.names]  # all checked before the connection is opened
    except ValueError as e:
        print(f"profile refused: {e}")
        return
    try:
        soc = socket.create_connection((a.host, a.port))
    except ConnectionRefusedError:
        print(f"Connection refused by {a.host}:{a.port}. Is to_gen_server.py running and printing 'Wait on'?")
        return
    with soc:
        for name, profile in zip(a.names, profiles):
            lines = to_lines(profile)
            SendLines(soc, lines)
            for line in lines:
                print(f"sent: {line}")
            print(f"---- profile '{name}' sent, waiting {a.wait:g} s ----")
            time.sleep(a.wait)


if __name__ == "__main__":
    main()
