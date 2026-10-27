# Bench CLI: quick guide

An interactive prompt for testing each hardware path and the FC link, one command at a time.

## Start

```bash
ssh pi@<pi-ip>
cd gse_communication_controller && source venv/bin/activate
python3 -m src.bench                    # uses config/default/config.json
python3 -m src.bench -c path/to/config.json
```

On a laptop with no hardware, set `MOCK_MODE = True` and `RADIO_MOCK_MODE = True` in `src/settings.py`.

The comm loop starts **ON**. It answers every FC comm packet, the same way `main.py` does, and prints each packet:

```
RX [rs485] 4a 42 4d 45 4a 4d 53 52 05 ...   # from FC
TX [rs485] 4a 42 4d 45 4a 4d 53 52 01 ...   # our response
```

## Commands

| Command | What it does |
|---|---|
| `valves` | List the passthrough valves and their states |
| `valve <id> on\|off` | Switch a valve relay (on = override) |
| `qdc` | List the QDC actuator states |
| `qdc <id> locked\|released` | Set a QDC actuator |
| `pressure` | Read the pressure sensors (PSI) |
| `link [rs485\|radio]` | Show or set the TX link. RX always listens on both |
| `send <hex>` | Send one packet on the active link (RS485 adds the 2-byte length prefix) |
| `rawrs485 <hex>` | Write raw bytes to RS485 with no framing. Good for a scope test (`rawrs485 55 55 55`) |
| `fc` | Show the last FC status: mode, ping id, uptime, command status |
| `fcvalve <id> <0\|1>` | Queue an FC valve command |
| `fcpulse <id> <ms>` | Queue an FC valve pulse |
| `fcmode <n>` | Queue an FC mode change |
| `fclink <0\|1>` | Queue an FC link change (0 = RS485, 1 = radio) |
| `loop on\|off` | Turn auto-responses to the FC on or off |
| `verbose on\|off` | Show or hide the RX/TX hex |
| `help [cmd]` | Help |
| `quit` / Ctrl-C / Ctrl-D | Shut down the hardware cleanly and exit |

Hex can include spaces: `send 01 02 03` is the same as `send 010203`.

## End-to-end RS485 test with the FC

1. Start the bench and check `link` says `rs485`.
2. Power up the FC. An `RX ... 05 ...` / `TX ... 01 ...` pair should appear about every 100 ms.
3. `fcvalve 1 1`. The next TX gets longer, because it now carries the command: `... 01 <id> 00 00 01 01`.
4. `fc`. The command status should go from `in progress` to `completed`.
5. You can only queue a new FC command once the FC reports the last one finished. Until then you'll get `error: Previous command not ...`.

**Nothing arriving?** Turn `loop off`, use `rawrs485 55` with a scope on A/B, and check the wiring and baud rate in `config.json`.

**For FC firmware:** the RS485 length prefix is **big-endian**, the packet fields are **little-endian**, and every packet starts with the magic number `4a 42 4d 45 4a 4d 53 52`.

## Gotchas

- Errors like "already shutdown" printed on exit are harmless. They come from the drivers' `__del__`.
- There is no `fccustom` command because custom FC commands are broken in `flight_computer.py`. Build one by hand with `send <hex>`.
