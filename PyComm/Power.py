#!/usr/bin/env python3
"""A power profile: frequency (Hz), power (dBm) and dwell (s) per bin, shared by the client and the server.
No sockets and no generator in here.
    profile = {"freq_hz": [...], "power_dbm": [...], "dwell_s": [...]}
The client builds it with from_dbm() and sends to_lines(); the server rebuilds it with parse_line() and runs validate().
"""
import math

KEYS = {"SOUR:LIST:FREQ": "freq_hz", "SOUR:LIST:POW": "power_dbm", "SOUR:LIST:DWEL": "dwell_s"}
MIN_DBM, MAX_DBM = -120.0, 0.0  # MAX_DBM protects the tinySA input and the LANL system: no profile above it is ever
# sent or played, in any unit. validate() enforces it in the client and again in the server. Raise it on purpose only.


def mw_to_dbm(mw):
    """0 mW is minus infinity dBm."""
    if math.isnan(mw) or mw < 0:
        raise ValueError(f"{mw} mW is not a power")
    return -math.inf if mw == 0 else 10 * math.log10(mw)


def dbm_to_mw(dbm):
    return 10 ** (dbm / 10)


def from_power(freq_hz, power, dwell_s, unit="dBm"):
    """from_dbm() for powers given in unit, "dBm" or "mW". Returns (profile, number of bins dropped)."""
    if unit == "mW":
        try:
            power = [mw_to_dbm(p) for p in power]
        except ValueError as e:
            raise ValueError(f"bad power: {e}") from e
    elif unit != "dBm":
        raise ValueError(f'unit must be "dBm" or "mW", not {unit!r}')
    return from_dbm(freq_hz, power, dwell_s)


def from_dbm(freq_hz, power_dbm, dwell_s):
    """Build a profile from powers in dBm. Bins at or below MIN_DBM are dropped, and so is -inf, which is what 0 mW is
    in dBm: the generator cannot make them. dwell_s is one number for every bin or one per bin.
    Returns (profile, number of bins dropped). Raises when nothing is left to play."""
    n = len(freq_hz)
    dwell = list(dwell_s) if hasattr(dwell_s, "__len__") else [dwell_s] * n
    if not (n == len(power_dbm) == len(dwell)):
        raise ValueError(f"list lengths differ: freq {n}, power {len(power_dbm)}, dwell {len(dwell)}")
    for i, p in enumerate(power_dbm):
        if not p < math.inf:  # also catches nan
            raise ValueError(f"bin {i + 1}: power {p} dBm is not a power")
    keep = [i for i in range(n) if power_dbm[i] > MIN_DBM]
    if not keep:
        raise ValueError(f"all {n} bins are at or below {MIN_DBM:g} dBm (zero power), nothing to send")
    profile = {"freq_hz": [float(freq_hz[i]) for i in keep],
               "power_dbm": [float(power_dbm[i]) for i in keep],
               "dwell_s": [float(dwell[i]) for i in keep]}
    return profile, n - len(keep)


def validate(profile):
    """Raise ValueError, naming the bin, when the profile cannot be played."""
    lists = [profile.get(k) for k in KEYS.values()]
    if any(v is None for v in lists):
        raise ValueError("missing " + ", ".join(k for k, v in zip(KEYS.values(), lists) if v is None))
    n = len(lists[0])
    if n == 0 or any(len(v) != n for v in lists):
        raise ValueError("list lengths differ or are empty: " + ", ".join(f"{k} {len(v)}" for k, v in zip(KEYS.values(), lists)))
    for i, (f, p, d) in enumerate(zip(*lists), 1):
        if not all(math.isfinite(v) for v in (f, p, d)):
            raise ValueError(f"bin {i}: not a finite number (freq {f}, power {p} dBm, dwell {d})")
        if f <= 0 or d <= 0:
            raise ValueError(f"bin {i}: frequency and dwell must be positive (freq {f} Hz, dwell {d} s)")
        if not MIN_DBM <= p <= MAX_DBM:
            raise ValueError(f"bin {i}: power {p:.2f} dBm is outside {MIN_DBM:g} to {MAX_DBM:g} dBm")


def to_lines(profile):
    """The text lines the client sends (the terminator EOT is added when sending)."""
    return ["SOUR:FREQ:MODE LIST",
            "SOUR:LIST:FREQ " + ",".join(f"{v:.0f}" for v in profile["freq_hz"]),
            "SOUR:LIST:POW " + ",".join(f"{v:.4f}" for v in profile["power_dbm"]),
            "SOUR:LIST:DWEL " + ",".join(f"{v:g}" for v in profile["dwell_s"])]


def parse_line(line, pending):
    """Fold one received line into the pending profile. Returns False when the line was not understood."""
    cmd, _, arg = line.strip().partition(" ")
    if cmd.upper() in KEYS:
        pending[KEYS[cmd.upper()]] = [float(v) for v in arg.split(",") if v.strip()]
    elif cmd.upper() != "SOUR:FREQ:MODE":  # the mode line is accepted and ignored: a profile is always a list
        return False
    return True
