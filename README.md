# gen_power

Plays a power profile from the NMR side on the SMB100B (`192.168.24.10`) in list mode.

| Script | Does |
|---|---|
| `gen_send_list.py` | The server (port 11111). Receives FREQ (MHz), POW (mW), DWEL, optional `FINISHED?`, then `EOT`. Plays the list once and answers `FINISHED` when the pass is over and RF is off. |
| `from_nmr_client.py` | Test client with fixed profiles. |
| `gen_readback.py` | Shows the last profile (`last_profile.csv`) next to what the generator holds. |
| `gen_send_cw.py` | Plays a profile in CW mode, one bin at a time. |
| `gen_pass_test.py`, `gen_dwell_test.py` | Check that a pass completes, and find the shortest dwell. |
| `PyComm/` | TCP lines (`SendLines`, `ReceiveLines`) and profile helpers. |

Needs Python 3 and `pyvisa`. Settings are the constants at the top of each script.
