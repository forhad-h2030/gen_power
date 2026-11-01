#!/usr/bin/env python3
import pyvisa
try:
    import matplotlib.pyplot as plt
except ImportError:
    plt = None

SMB_ETHERNET_ADDRESS = "TCPIP0::192.168.24.10::inst0::INSTR"
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

def plot_profile(freq_text, power_text):
    """Plot the list the generator holds: frequency (MHz) on x, power as the generator holds it (arbitrary units for now) on y."""
    freqs = [float(v) / 1e6 for v in freq_text.split(",")]
    powers = [float(v) for v in power_text.split(",")]
    if len(freqs) != len(powers):
        print(f"not plotted: {len(freqs)} frequencies but {len(powers)} powers")
        return
    fig, ax = plt.subplots()
    ax.step(freqs, powers, where="post", color="#1e7f55")
    ax.fill_between(freqs, powers, min(powers), step="post", color="#1e7f55", alpha=0.25)
    ax.set_xlabel("Frequency (MHz)")
    ax.set_ylabel("Power (arb. units)")
    ax.grid(alpha=0.3)
    plt.show()


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
    elif "SOURce:LIST:FREQuency?" in answers and "SOURce:LIST:POWer?" in answers:
        plot_profile(answers["SOURce:LIST:FREQuency?"], answers["SOURce:LIST:POWer?"])
    else:
        print("not plotted: the generator did not answer the frequency or power list")

if __name__ == "__main__":
    main()
