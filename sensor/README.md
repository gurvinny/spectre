# SPECTRE · sensor

[![Python](https://img.shields.io/badge/Python-3.11-35E0C4.svg?style=flat-square&logo=python&logoColor=white&labelColor=0a0e12)](.)
[![FastAPI](https://img.shields.io/badge/FastAPI-async-35E0C4.svg?style=flat-square&logo=fastapi&logoColor=white&labelColor=0a0e12)](.)
[![stdlib core](https://img.shields.io/badge/core-stdlib%20only-8598A6.svg?style=flat-square&labelColor=0a0e12)](.)

The Python service: UART ingest → detection → storage → Wazuh forwarding → REST + WebSocket API.
The ingest/detection/storage core is **standard-library only** — FastAPI/uvicorn are needed just
for the HTTP layer — so the pipeline can be smoke-tested without installing anything.

## Module map

| Module | Responsibility |
|---|---|
| `spectre/reader.py` | Async serial reader. Opens each port with **DTR/RTS held low** (via stdlib `termios`) so the ESP32-C5 doesn't reset, and streams lines into the pipeline. |
| `spectre/parser.py` | Strips the `<PRI>` + `ESP32C5 wifi_sniffer:` tag, parses JSON, latches band from the boot event. |
| `spectre/models.py` | `Event` / `Threat` dataclasses + the severity ↔ syslog map. |
| `spectre/pipeline.py` | The hot path: in-memory ring, device/AP inventory, batched writes, detection fan-out, WS broadcast, summaries, retention. |
| `spectre/detect/` | One module per rule: `deauth_flood`, `evil_twin`, `flood`, `anomaly`. |
| `spectre/store.py` | SQLite (WAL) — frames, inventory, threats, summaries, config, users, sessions; retention + disk guard. |
| `spectre/wazuh.py` | RFC 5424 builder + UDP/TCP forwarder with severity mapping. |
| `spectre/api.py` | FastAPI routes, cookie auth, `/ws` live feed. |
| `spectre/main.py` | Wires it together and selects the ingest source. |
| `spectre/sim/` | `generate.py` (synthetic traffic + attack scenarios) and `replay.py` (capture playback). |

## Run it

```bash
# In Docker (recommended — brings FastAPI/uvicorn):
docker build -t spectre-sensor . && \
docker run --rm -e SPECTRE_SOURCE=sim -p 8100:8100 spectre-sensor

# Real boards:
docker run --rm --device /dev/ttyUSB0 -e SERIAL_PORTS=/dev/ttyUSB0 -p 8100:8100 spectre-sensor
```

## Simulator & replay

```bash
# Print synthetic firmware lines (pipe anywhere), inject an attack after 3s:
python -m spectre.sim.generate --band 2.4GHz --scenario deauth_flood --duration 20

# Normalize a real capture file to canonical events:
python -m spectre.sim.replay capture.txt
```

Set `SPECTRE_SOURCE=sim` to drive the live pipeline from the simulator (background traffic on both
bands + rotating `deauth_flood → evil_twin → beacon_flood → probe_flood` injections), or
`SPECTRE_SOURCE=replay` with `REPLAY_FILE=/data/capture.txt`.

## Ingest sources

| `SPECTRE_SOURCE` | Behaviour |
|---|---|
| `serial` *(default)* | Read the boards on `SERIAL_PORTS`. |
| `sim` | Built-in synthetic generator — no hardware needed. |
| `replay` | Play back `REPLAY_FILE` at wall-clock speed. |

_Author: gurvinny · Project: SPECTRE_
