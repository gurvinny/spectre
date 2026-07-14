# Architecture

```
[ESP32-C5 2.4G] ttyUSB0 ┐
                        ├─▶ SerialReader (async) ─▶ Parser ─▶ Pipeline.ingest() ──┐
[ESP32-C5 5G]  ttyUSB1 ┘     DTR/RTS low          strip+JSON   (synchronous, fast) │
                                                                                   │
   ┌───────────────────────────────────────────────────────────────────────────────┘
   ▼
Pipeline (in-memory brain)
   ├─ recent-frame ring (overview / channel histogram)
   ├─ device + AP inventory (dirty-flushed to SQLite)
   ├─ Detection Engine ─▶ Threat ─▶ store + WebSocket + Wazuh
   ├─ frame buffer ─(1s)─▶ SQLite.insert_frames (batched)
   ├─ WS broadcaster ─(250ms)─▶ subscribers
   ├─ summary ticker ─(N s)─▶ SQLite + Wazuh
   └─ prune loop ─(5min)─▶ retention + disk guard
   ▼
FastAPI  ──  REST + /ws  ──▶  Next.js SOC console
```

## Responsibilities

- **SerialReader** (`reader.py`) — one async task per port via `loop.add_reader`. Opens the tty
  with DTR/RTS cleared (stdlib `termios` `TIOCMBIC`) so the board keeps running, line-buffers, and
  hands raw lines to a per-port `Parser`.
- **Parser** (`parser.py`) — strips PRI + tag, JSON-parses, latches band from the boot event,
  stamps `received_at`, counts malformed lines.
- **Pipeline** (`pipeline.py`) — owns all live state and the periodic background tasks. `ingest()`
  is synchronous and awaits nothing, so it stays fast under load; everything expensive (DB writes,
  broadcasts) is batched on timers.
- **Detection Engine** (`detect/`) — runs each rule against every event; rules are small, stateful,
  and read thresholds live from config. Threats are rate-limited by a per-signature cooldown.
- **Store** (`store.py`) — SQLite WAL. Batched frame inserts, upserted inventory, threat/summary
  logs, control-plane tables (config/users/sessions), retention + disk guard.
- **WazuhForwarder** (`wazuh.py`) — builds RFC 5424 and sends over UDP/TCP; reads host/port/proto
  live so Settings changes take effect immediately.
- **API** (`api.py`) — REST + `/ws`. Cookie-session auth; the WebSocket streams batched frames and
  threats to the console.

## Why one Python service

Ingest is inherently Python (serial + parsing), so folding detection, storage, forwarding and the
API into one FastAPI process keeps the moving parts minimal and the hot path in a single event
loop. The frontend is a pure client of that API.

## Threading model

A single asyncio loop runs the readers, pipeline tasks and API. SQLite is accessed through one
connection guarded by a lock (`check_same_thread=False`) so uvicorn worker threads and the loop can
share it safely.

_Author: gurvinny · Project: SPECTRE_
