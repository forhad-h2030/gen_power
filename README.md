# gen_power

Drive the SMB100B generator with a power profile (frequency, power, dwell per bin) sent over TCP.

```
PyComm/Tcp.py        sockets: the lab functions, plus SendLines and ReceiveLineStop
PyComm/Power.py      profile rules: mW/dBm, drop zero bins, 0 dBm cap, wire lines
to_gen_server.py     runs next to the generator: receives a profile and plays it once
from_nmr_client.py   builds a profile and sends it
```

## Run

Needs Python 3 and `pyvisa`. The generator is at `192.168.24.10`. Run both from this folder.

```
python to_gen_server.py            # wait for "Wait on <host>:11111"
python from_nmr_client.py zeros    # in another window; try: one, three, span, zeros
```

Stop the server with Ctrl+C (RF turns off).

## Rules

- Wire format: lines `SOUR:LIST:FREQ` (Hz), `SOUR:LIST:POW` (dBm), `SOUR:LIST:DWEL` (s), then `EOT`.
- Set `UNIT = "dBm"` or `"mW"` at the top of `from_nmr_client.py`. The wire is always dBm.
- Zero power (0 mW, -inf dBm, or at or below -120 dBm) is dropped with its frequency and dwell.
- Power above 0 dBm is never sent or played: the whole profile is refused (client and server both check).
  The limit is `MAX_DBM` in `PyComm/Power.py`.
- RF is off after every profile, when the client disconnects, and on Ctrl+C.

## The server and the RF list

`to_gen_server.py` runs on the PC next to the generator. It waits for a profile from the NMR side, plays it once, and turns RF off.

| Function | Role |
|---|---|
| `connect_generator()` | Opens the LAN connection and prints the generator's `*IDN?` answer. |
| `serve(host, port)` | Listens on port 11111, accepts one client at a time, and always ends with RF off. |
| `ReceiveLineStop` (`PyComm/Tcp.py`) | Reads the next line from the client. It checks the stop flag every second, so Ctrl+C works. |
| `parse_line` (`PyComm/Power.py`) | Folds each received line into the profile being built. |
| `handle_client()` | Collects lines until `EOT`, then calls `play()`. |
| `validate` (`PyComm/Power.py`) | Refuses a bad profile before the generator is touched, including any power above 0 dBm. |
| `play()` | Validates, loads the list, triggers it, waits for it to finish, and always writes RF off. |
| `load_list()` | Sends the list to the generator (steps below). |
| `send()` and `ask()` | `send` writes one command, then reads `SYSTem:ERRor?`, so a rejected command stops the profile with the generator's own message. `ask` is a query that names the command if it gets no answer. |

How the RF list is handled:

1. **Receive.** The client sends the lines and `EOT`. The server rebuilds the profile and runs `validate()`.
2. **Load, with RF off.** `load_list()` clears errors (`*CLS`), puts frequency and power in CW mode, and sets the level to the first list power so RF does not start at an old level. It selects the list `gen_profile` and writes the frequency list (Hz), the power list (dBm) and the dwell. Equal dwells use one `LIST:DWELl` value. Different dwells use `LIST:DWELl:LIST`, one value per bin.
3. **Check.** It asks for the number of frequency and power points and stops if they differ from what was sent.
4. **Arm.** It sets list mode to AUTO and the trigger source to SINGle (one pass per trigger, no repeat), then switches RF on and frequency mode to LIST. The generator refuses list mode while RF is off, so the order matters.
5. **Trigger and wait.** `play()` sends `LIST:TRIGger:EXECute`, logs the profile to `data/rf_events.jsonl`, and waits the sum of the dwells (plus 0.1 s).
6. **Finish.** RF goes off in `finally`, whatever happened.

Each profile plays once. Profiles that arrive during a pass are read after it finishes.

Not yet confirmed on the real generator: the per-bin dwell command (`LIST:DWELl:LIST`). Only the single-value form was verified.
