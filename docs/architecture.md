# Architecture

A frame's path, from the radio to the console and the SIEM, in three hops: the firmware on each board,
the sensor service, and its two consumers.

```mermaid
%%{init: {
  'theme': 'base',
  'themeVariables': {
    'primaryColor': '#0a0e12',
    'primaryTextColor': '#fff',
    'primaryBorderColor': '#35E0C4',
    'lineColor': '#35E0C4',
    'secondaryColor': '#0a0e12',
    'tertiaryColor': '#0a0e12',
    'actorBkg': '#0a0e12',
    'actorBorder': '#35E0C4',
    'actorTextColor': '#fff',
    'signalColor': '#35E0C4',
    'signalTextColor': '#6B7C8C',
    'noteBkgColor': '#0a0e12',
    'noteBorderColor': '#9B8CFF',
    'noteTextColor': '#C9D6DF',
    'labelBoxBkgColor': '#0a0e12',
    'labelBoxBorderColor': '#9B8CFF',
    'labelTextColor': '#fff',
    'loopTextColor': '#6B7C8C',
    'activationBkgColor': '#11171d',
    'activationBorderColor': '#35E0C4',
    'fontFamily': 'monospace'
  }
}}%%
flowchart TB
    subgraph FW["Firmware · each ESP32-C5"]
        RX["promiscuous rx_cb<br/>copy header + IEs"]
        RG[("ring buffer<br/>32 KB")]
        EM["emit task<br/>decode → JSON line"]
        HP["hop task<br/>channel · sweep · telemetry"]
        CM["cmd task<br/>NVS config"]
    end
    subgraph SN["Sensor · one asyncio loop"]
        RD["SerialReader<br/>DTR/RTS low"]
        PR["Parser<br/>strip · latch band · stamp"]
        PL{"Pipeline.ingest()<br/>synchronous"}
        DE["Detection Engine"]
        ST[("SQLite WAL")]
        BA["boards.py<br/>health + commands"]
        API["FastAPI<br/>REST + /ws"]
    end
    subgraph OUT["Consumers"]
        WEB["Next.js console"]
        WZ["Wazuh"]
    end
    RX -- "full: drop_queue++" --> RG
    RG --> EM
    HP --> EM
    EM -- "UART0 · 460800" --> RD
    RD --> PR --> PL
    PL --> DE
    PL -- "1 s batches" --> ST
    DE -- "Threat" --> ST
    DE -- "RFC 5424" --> WZ
    ST --> BA --> API
    PL -- "250 ms" --> API
    API --> WEB
    WEB -. "POST /api/boards/{id}/cmd" .-> API
    API -. "send()" .-> RD
    RD -. "JSON command" .-> CM

    style FW fill:transparent,stroke:#9B8CFF,stroke-width:1px,stroke-dasharray: 5 5,color:#fff
    style SN fill:transparent,stroke:#35E0C4,stroke-width:1px,stroke-dasharray: 5 5,color:#fff
    style OUT fill:transparent,stroke:#FF4D5E,stroke-width:1px,stroke-dasharray: 5 5,color:#fff
    style RX fill:#0a0e12,stroke:#9B8CFF,stroke-width:2px,color:#fff
    style RG fill:#0a0e12,stroke:#F5A623,stroke-width:2px,color:#fff
    style EM fill:#0a0e12,stroke:#9B8CFF,stroke-width:2px,color:#fff
    style HP fill:#0a0e12,stroke:#9B8CFF,stroke-width:2px,color:#fff
    style CM fill:#0a0e12,stroke:#9B8CFF,stroke-width:2px,color:#fff
    style RD fill:#0a0e12,stroke:#35E0C4,stroke-width:2px,color:#fff
    style PR fill:#0a0e12,stroke:#35E0C4,stroke-width:2px,color:#fff
    style PL fill:#0a0e12,stroke:#35E0C4,stroke-width:3px,color:#fff
    style DE fill:#0a0e12,stroke:#35E0C4,stroke-width:2px,color:#fff
    style ST fill:#0a0e12,stroke:#F5A623,stroke-width:2px,color:#fff
    style BA fill:#0a0e12,stroke:#35E0C4,stroke-width:2px,color:#fff
    style API fill:#0a0e12,stroke:#35E0C4,stroke-width:2px,color:#fff
    style WEB fill:#0a0e12,stroke:#C9D6DF,stroke-width:2px,color:#fff
    style WZ fill:#0a0e12,stroke:#FF4D5E,stroke-width:2px,color:#fff
```

## Firmware (`firmware/spectre-sniffer`)

- **rx callback** runs in the Wi-Fi driver's context. It copies the 802.11 header and the information
  elements (data frames: 64 bytes, header only) plus the radio metadata into a ring buffer and returns. If
  the ring is full, the frame is counted in `drop_queue` instead of blocking the driver.
- **emit task** decodes each item (`core/`, portable C with no IDF dependency) into one JSON line and writes
  it to UART0. It also writes an `ap_info` line the first time a BSSID is seen and whenever its advertised
  configuration changes, and every `ap_info_s` seconds.
- **hop task** steps through the channel plan, and at dwell boundaries writes `channel_sweep_complete`,
  `telemetry` and `clock_sync` lines.
- **cmd task** reads JSON commands from the same UART, validates them, saves the config in NVS and acks.

Details: [firmware/README.md](../firmware/README.md).

## Sensor responsibilities

- **SerialReader** (`reader.py`) — one async task per port via `loop.add_reader`. Opens the tty
  with DTR/RTS cleared (stdlib `termios` `TIOCMBIC`) so the board keeps running, line-buffers, and
  hands raw lines to a per-port `Parser`. `send()` writes one JSON command, serialized per port.
- **Parser** (`parser.py`) — strips PRI + tag, JSON-parses, latches band from the boot event (and from
  a successful `cmd_ack`), stamps `received_at`, counts malformed lines.
- **Pipeline** (`pipeline.py`) — owns all live state and the periodic background tasks. `ingest()`
  is synchronous and awaits nothing, so it stays fast under load; everything expensive (DB writes,
  broadcasts) is batched on timers.
- **Detection Engine** (`detect/`) — runs each rule against every event; rules are small, stateful,
  and read thresholds live from config. Threats are rate-limited by a per-signature cooldown.
- **Store** (`store.py`) — SQLite WAL. Batched frame inserts, upserted inventory, threat/summary
  logs, `board_events` (lifecycle lines and the command audit), `ap_info`, control-plane tables
  (config/users/sessions), retention + disk guard, additive schema migration.
- **Boards** (`boards.py`) — reduces each board's newest `boot`, `telemetry`, sweep and `cmd_ack` rows
  to firmware, radio plan, loss and UART load, and validates console commands. Commands are refused
  unless `SPECTRE_BOARD_CONTROL=true`.
- **WazuhForwarder** (`wazuh.py`) — builds RFC 5424 and sends over UDP/TCP; reads host/port/proto
  live so Settings changes take effect immediately.
- **API** (`api.py`) — REST + `/ws`. Cookie-session auth; the WebSocket streams batched frames and
  threats to the console.

## Timers

```mermaid
%%{init: {
  'theme': 'base',
  'themeVariables': {
    'primaryColor': '#0a0e12',
    'primaryTextColor': '#fff',
    'primaryBorderColor': '#35E0C4',
    'lineColor': '#35E0C4',
    'secondaryColor': '#0a0e12',
    'tertiaryColor': '#0a0e12',
    'actorBkg': '#0a0e12',
    'actorBorder': '#35E0C4',
    'actorTextColor': '#fff',
    'signalColor': '#35E0C4',
    'signalTextColor': '#6B7C8C',
    'noteBkgColor': '#0a0e12',
    'noteBorderColor': '#9B8CFF',
    'noteTextColor': '#C9D6DF',
    'labelBoxBkgColor': '#0a0e12',
    'labelBoxBorderColor': '#9B8CFF',
    'labelTextColor': '#fff',
    'loopTextColor': '#6B7C8C',
    'activationBkgColor': '#11171d',
    'activationBorderColor': '#35E0C4',
    'fontFamily': 'monospace'
  }
}}%%
flowchart LR
    I["ingest()<br/>every line"] --> FB["frame buffer"]
    FB -- "1 s" --> DB[("SQLite<br/>frames")]
    I --> INV["inventory<br/>(dirty set)"]
    INV -- "3 s" --> DB2[("SQLite<br/>devices · aps")]
    I --> WS["WS queue"]
    WS -- "250 ms" --> C["console"]
    SUM["summary ticker"] -- "summary_interval_seconds" --> Z["Wazuh + summaries"]
    PRN["prune loop"] -- "5 min" --> RET["retention + disk guard"]

    style I fill:#0a0e12,stroke:#35E0C4,stroke-width:3px,color:#fff
    style FB fill:#0a0e12,stroke:#35E0C4,stroke-width:2px,color:#fff
    style DB fill:#0a0e12,stroke:#F5A623,stroke-width:2px,color:#fff
    style INV fill:#0a0e12,stroke:#35E0C4,stroke-width:2px,color:#fff
    style DB2 fill:#0a0e12,stroke:#F5A623,stroke-width:2px,color:#fff
    style WS fill:#0a0e12,stroke:#35E0C4,stroke-width:2px,color:#fff
    style C fill:#0a0e12,stroke:#C9D6DF,stroke-width:2px,color:#fff
    style SUM fill:#0a0e12,stroke:#35E0C4,stroke-width:2px,color:#fff
    style Z fill:#0a0e12,stroke:#FF4D5E,stroke-width:2px,color:#fff
    style PRN fill:#0a0e12,stroke:#35E0C4,stroke-width:2px,color:#fff
    style RET fill:#0a0e12,stroke:#F5A623,stroke-width:2px,color:#fff
```

## A board command, end to end

```mermaid
%%{init: {
  'theme': 'base',
  'themeVariables': {
    'primaryColor': '#0a0e12',
    'primaryTextColor': '#fff',
    'primaryBorderColor': '#35E0C4',
    'lineColor': '#35E0C4',
    'secondaryColor': '#0a0e12',
    'tertiaryColor': '#0a0e12',
    'actorBkg': '#0a0e12',
    'actorBorder': '#35E0C4',
    'actorTextColor': '#fff',
    'signalColor': '#35E0C4',
    'signalTextColor': '#6B7C8C',
    'noteBkgColor': '#0a0e12',
    'noteBorderColor': '#9B8CFF',
    'noteTextColor': '#C9D6DF',
    'labelBoxBkgColor': '#0a0e12',
    'labelBoxBorderColor': '#9B8CFF',
    'labelTextColor': '#fff',
    'loopTextColor': '#6B7C8C',
    'activationBkgColor': '#11171d',
    'activationBorderColor': '#35E0C4',
    'fontFamily': 'monospace'
  }
}}%%
sequenceDiagram
    autonumber
    participant U as Console
    participant A as API
    participant S as board_events
    participant R as SerialReader
    participant B as Board
    U->>A: POST /api/boards/{id}/cmd
    alt SPECTRE_BOARD_CONTROL is not true
        A-->>U: 403, nothing written
    else enabled
        A->>A: validate, add id
        A->>S: audit row (kind=cmd)
        A->>R: send(command)
        R->>B: one JSON line
        B-->>R: cmd_ack {id, ok, config}
        R->>S: cmd_ack row
        A-->>U: ack (waits up to 3 s)
    end
```

## Why one Python service

Ingest is inherently Python (serial + parsing), so folding detection, storage, forwarding and the
API into one FastAPI process keeps the moving parts minimal and the hot path in a single event
loop. The frontend is a pure client of that API.

## Threading model

A single asyncio loop runs the readers, pipeline tasks and API. SQLite is accessed through one
connection guarded by a lock (`check_same_thread=False`) so uvicorn worker threads and the loop can
share it safely.

_Author: gurvinny · Project: SPECTRE_
