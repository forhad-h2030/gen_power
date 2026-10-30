#!/usr/bin/env python3
"""TO GENERATOR (the RF_Gen side): TCP server that waits for a power profile from NMR and plays it on the generator.
The client sends newline-terminated lines, then EOT (see power_profile.py for the format):
    SOUR:FREQ:MODE LIST
    SOUR:LIST:FREQ 213e6,214e6,215e6      Hz
    SOUR:LIST:POW -40,-45,-42             dBm
    SOUR:LIST:DWEL 0.5,0.5,1              s
    EOT
A profile plays once (no repeat), then RF goes off and the server waits for the next one. Profiles that arrive while
one is playing are handled after it finishes. A bad profile is rejected with its bin number and RF stays off.
RF also turns off when the client disconnects and on Ctrl+C. Every profile is logged to data/rf_events.jsonl.
    python to_gen_server.py --port 11111
"""
import argparse
import json
import socket
import threading
from datetime import datetime
from pathlib import Path

import pyvisa

from PyComm.Power import parse_line, validate
from PyComm.Tcp import ReceiveLineStop

SMB_IP_ADDRESS = "192.168.24.10"
SMB_ETHERNET_ADDRESS = f"TCPIP0::{SMB_IP_ADDRESS}::inst0::INSTR"
DATA_DIR = Path(__file__).resolve().parent / "data"  # everything the tools record goes here (ignored by git)
EVENTS = DATA_DIR / "rf_events.jsonl"
LIST_NAME = "gen_profile"


def log_event(kind, event_id, **fields):
    line = {"event_id": event_id, "kind": kind, "t": datetime.now().isoformat(), **fields}
    DATA_DIR.mkdir(exist_ok=True)
    with open(EVENTS, "a") as f:
        f.write(json.dumps(line) + "\n")


def send(smb, command):
    """Write one SCPI command; fail with the generator's own error text if it rejects it."""
    print(f"  > {command}")
    smb.write(command)
    err = smb.query("SYSTem:ERRor?").strip()
    if not err.startswith("0"):
        raise RuntimeError(f"{command!r} rejected: {err}")


def ask(smb, command):
    """Query the generator; name the command if it never answers."""
    print(f"  > {command}")
    try:
        return smb.query(command).strip()
    except pyvisa.VisaIOError as e:
        raise RuntimeError(f"{command!r} got no answer: {e}") from e


def connect_generator():
    smb = pyvisa.ResourceManager().open_resource(SMB_ETHERNET_ADDRESS, timeout=5000)
    print(f"Connected to RF Gen: {smb.query('*IDN?').strip()}")
    return smb


def load_list(smb, profile):
    """Load the lists with RF off, then arm one pass of the list. Returns the pass duration in s."""
    n = len(profile["freq_hz"])
    send(smb, "*CLS")
    send(smb, "OUTPut:STATe OFF")
    send(smb, "SOURce:FREQuency:MODE CW")
    send(smb, "SOURce:POWer:MODE CW")
    send(smb, f"SOURce:POWer:LEVel {profile['power_dbm'][0]}")  # RF comes on at the first list power, not an old level
    send(smb, f'SOURce:LIST:SELect "{LIST_NAME}"')
    send(smb, "SOURce:LIST:FREQuency " + ",".join(f"{v:.0f}" for v in profile["freq_hz"]))
    send(smb, "SOURce:LIST:POWer " + ",".join(f"{v:.4f}" for v in profile["power_dbm"]))
    if len(set(profile["dwell_s"])) == 1:  # the generator's DWELl takes one value for the whole list
        send(smb, f"SOURce:LIST:DWELl {profile['dwell_s'][0]}")
    else:
        send(smb, "SOURce:LIST:DWELl:LIST " + ",".join(f"{v}" for v in profile["dwell_s"]))
    for q in ("FREQuency", "POWer"):
        if int(ask(smb, f"SOURce:LIST:{q}:POINts?")) != n:
            raise RuntimeError(f"generator holds the wrong number of {q} points")
    send(smb, "SOURce:LIST:MODE AUTO")
    send(smb, "SOURce:LIST:TRIGger:SOURce SINGle")  # one pass per trigger, no repeat
    send(smb, "OUTPut:STATe ON")  # the generator refuses list mode while RF is off
    send(smb, "SOURce:FREQuency:MODE LIST")
    return sum(profile["dwell_s"])


def play(smb, profile, stop):
    """Validate, load and trigger one profile, wait for it to finish, and leave RF off whatever happens."""
    event_id = f"{datetime.now():%Y%m%d_%H%M%S}"
    try:
        validate(profile)
        duration = load_list(smb, profile)
        send(smb, "SOURce:LIST:TRIGger:EXECute")
        log_event("profile", event_id, **profile)
        print(f"-> profile {event_id}: {len(profile['freq_hz'])} bins live for {duration:g} s")
        stop.wait(duration + 0.1)
        print("profile done, RF off, waiting for the next one")
    except (ValueError, RuntimeError, pyvisa.VisaIOError) as e:
        print(f"profile rejected, RF off: {e}")
    finally:
        smb.write("OUTPut:STATe OFF")


def handle_client(soc, smb, stop):
    """Read lines until the client closes or stop is set. A profile plays when its EOT arrives."""
    pending, extra = {}, b""
    while True:
        line, extra, alive = ReceiveLineStop(soc, stop, extra)
        if line is None:
            return
        line = line.strip()
        if not line:
            continue
        if line.upper() == "EOT":
            profile, pending = pending, {}
            play(smb, profile, stop)
        elif not parse_line(line, pending):
            print(f"ignored: {line}")


def serve(host, port, stop=None):
    """Run until stop is set (or Ctrl+C)."""
    stop = stop or threading.Event()
    smb = connect_generator()
    soc_svr = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    soc_svr.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    soc_svr.bind((host, port))
    soc_svr.listen(1)
    soc_svr.settimeout(1.0)  # so Ctrl+C and stop are noticed while waiting for a client (Windows)
    print(f"Wait on {host}:{port} for a profile (Ctrl+C to stop)...")
    try:
        while not stop.is_set():
            try:
                soc, addr = soc_svr.accept()
            except socket.timeout:
                continue
            print(f"Accept: {addr}.")
            with soc:
                handle_client(soc, smb, stop)
            smb.write("OUTPut:STATe OFF")
            print("Client closed the connection, RF off.")
    except KeyboardInterrupt:
        pass
    finally:
        smb.write("OUTPut:STATe OFF")
        smb.close()
        soc_svr.close()
        log_event("off", f"{datetime.now():%Y%m%d_%H%M%S}")
        print("Generator safely disconnected.")


def main():
    p = argparse.ArgumentParser(description="Receive power profiles from a client and play them on the generator.")
    p.add_argument("--host", default=socket.gethostname(), help="address to listen on (default: this machine)")
    p.add_argument("--port", type=int, default=11111, help="port to listen on (default 11111)")
    a = p.parse_args()
    serve(a.host, a.port)


if __name__ == "__main__":
    main()
