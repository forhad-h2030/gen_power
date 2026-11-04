#!/usr/bin/env python3
import csv
from pathlib import Path
import pyvisa
try:
    import matplotlib.pyplot as plt
except ImportError:
    plt = None

SMB_ETHERNET_ADDRESS = "TCPIP0::192.168.24.10::inst0::INSTR"
PROFILE_FILE = Path(__file__).resolve().parent / "last_profile.csv"  # written by gen_send_list.py: every bin received
QUERIES = [
    "OUTPut:STATe?",
    "SOURce:FREQuency:MODE?",
    "SOURce:FREQuency?",
    "SOURce:POWer:LEVel?",
    "SOURce:LIST:SELect?",
    "SOURce:LIST:MODE?",
    "SOURce:LIST:TRIGger:SOURce?",
    "SOURce:LIST:FREQuency:POINts?",
    "SOURce:LIST:POWer:POINts?",
    "SOURce:LIST:DWELl?",
    "SOURce:LIST:FREQuency?",
    "SOURce:LIST:POWer?",
    "SYSTem:ERRor?",
]

def load_full_profile():
    """The last profile gen_send_list.py received, every bin: (freq_mhz[], power_dbm[]), or None if unavailable."""
    try:
        with open(PROFILE_FILE, newline="") as f:
            rows = list(csv.DictReader(f))
        return [float(r["freq_mhz"]) for r in rows], [float(r["power_dbm"]) for r in rows]
    except (OSError, KeyError, ValueError):
        return None


def plot_profile(freq_text, power_text):
    """Plot the list the generator holds: frequency (MHz) on x, power as the generator holds it (arbitrary units for now) on y.
    When gen_send_list.py has saved the whole profile, it is drawn behind, and the generator's bins are the dots."""
    freqs = [float(v) / 1e6 for v in freq_text.split(",") if v.strip()]  # an empty list or a trailing comma gives ''
    powers = [float(v) for v in power_text.split(",") if v.strip()]
    if not freqs or not powers:
        print(f"not plotted: the generator list is empty ({len(freqs)} frequencies, {len(powers)} powers)")
        return
    if len(freqs) != len(powers):
        print(f"not plotted: {len(freqs)} frequencies but {len(powers)} powers")
        return
    fig, ax = plt.subplots()
    full = load_full_profile()
    if full:
        floor = min(powers) - 10  # a bin at 0 mW is -120 dBm, which is left below the axis
        ax.step(full[0], full[1], where="post", color="#1e7f55", label=f"whole profile ({len(full[0])} bins)")
        ax.fill_between(full[0], full[1], floor, step="post", color="#1e7f55", alpha=0.25)
        ax.plot(freqs, powers, "o", color="#b8312f", markersize=3, label=f"held by the generator ({len(freqs)} bins)")
        ax.set_ylim(bottom=floor)
        ax.legend()
    else:
        ax.step(freqs, powers, where="post", color="#1e7f55")
        ax.fill_between(freqs, powers, min(powers), step="post", color="#1e7f55", alpha=0.25)
        print(f"whole profile not drawn: {PROFILE_FILE.name} not found (it is written when gen_send_list.py gets a message)")
    ax.set_xlabel("Frequency (MHz)")
    ax.set_ylabel("Power (dBm)")
    ax.grid(alpha=0.3)


def plot_raw_profile():
    """Plot the profile as gen_send_list.py received it, before any scaling: power as received (mW) against frequency.
    The bins that were not sent to the generator (cut by MIN_DB) are marked with a grey cross."""
    try:
        with open(PROFILE_FILE, newline="") as f:
            rows = list(csv.DictReader(f))
        freqs = [float(r["freq_mhz"]) for r in rows]
        powers = [float(r["power_received"]) for r in rows]
        sent = [r["sent"] == "1" for r in rows]
    except (OSError, KeyError, ValueError):
        print(f"raw profile not drawn: {PROFILE_FILE.name} not found or unreadable "
              "(it is written when gen_send_list.py gets a message)")
        return
    fig, ax = plt.subplots()
    ax.step(freqs, powers, where="post", color="#1e7f55", label=f"profile as received ({len(freqs)} bins)")
    ax.fill_between(freqs, powers, 0, step="post", color="#1e7f55", alpha=0.25)
    dropped = [(f, p) for f, p, s in zip(freqs, powers, sent) if not s]
    if dropped:
        ax.plot(*zip(*dropped), "x", color="#7a7a7a", markersize=4, label=f"not sent ({len(dropped)} bins)")
    ax.set_xlabel("Frequency (MHz)")
    ax.set_ylabel("Power as received (mW)")
    ax.grid(alpha=0.3)
    ax.legend()


def main():
    smb = pyvisa.ResourceManager().open_resource(SMB_ETHERNET_ADDRESS, timeout=5000)
    answers = {}
    try:
        print(f"Connected to RF Gen: {smb.query('*IDN?').strip()}")
        for q in QUERIES:
            try:
                answers[q] = smb.query(q).strip()
                print(f"{q:34} {answers[q]}")
            except pyvisa.VisaIOError as e:
                print(f"{q:34} no answer: {e}")
    finally:
        smb.close()

    if plt is None:
        print("not plotted: matplotlib is not installed (pip install matplotlib)")
    else:
        if "SOURce:LIST:FREQuency?" in answers and "SOURce:LIST:POWer?" in answers:
            plot_profile(answers["SOURce:LIST:FREQuency?"], answers["SOURce:LIST:POWer?"])
        else:
            print("not plotted: the generator did not answer the frequency or power list")
        plot_raw_profile()
        plt.show()

if __name__ == "__main__":
    main()
