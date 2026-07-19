<br/>

<div align="center">

<img src="docs/assets/spectre-banner.svg" alt="SPECTRE" width="100%"/>

<br/>

**A wireless intrusion-detection sensor. Two radios watch the air. Nothing gets on quietly.**

<br/>

[![WIDS](https://img.shields.io/badge/▁▂▃-WIRELESS%20IDS-35E0C4.svg?style=for-the-badge&labelColor=0a0e12)](#-what-it-does)

<br/>

[![Version](https://img.shields.io/badge/Version-0.1.0-35E0C4.svg?style=flat-square&labelColor=0a0e12)](#)
[![License](https://img.shields.io/badge/License-AGPL--3.0-35E0C4.svg?style=flat-square&logo=gnu&logoColor=white&labelColor=0a0e12)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.11-35E0C4.svg?style=flat-square&logo=python&logoColor=white&labelColor=0a0e12)](sensor/)
[![FastAPI](https://img.shields.io/badge/FastAPI-async-35E0C4.svg?style=flat-square&logo=fastapi&logoColor=white&labelColor=0a0e12)](sensor/)
[![Next.js](https://img.shields.io/badge/Next.js-15-C9D6DF.svg?style=flat-square&logo=nextdotjs&logoColor=white&labelColor=0a0e12)](web/)
[![Tailwind](https://img.shields.io/badge/Tailwind-v4-9B8CFF.svg?style=flat-square&logo=tailwindcss&logoColor=white&labelColor=0a0e12)](web/)
[![SQLite](https://img.shields.io/badge/SQLite-WAL-F5A623.svg?style=flat-square&logo=sqlite&logoColor=white&labelColor=0a0e12)](sensor/spectre/store.py)
[![Wazuh](https://img.shields.io/badge/Wazuh-RFC%205424-FF4D5E.svg?style=flat-square&logo=wazuh&logoColor=white&labelColor=0a0e12)](docs/wazuh-integration.md)
[![Self-Hosted](https://img.shields.io/badge/Self--Hosted-Docker-35E0C4.svg?style=flat-square&logo=docker&logoColor=white&labelColor=0a0e12)](docker-compose.yml)
[![PRs Welcome](https://img.shields.io/badge/PRs-Welcome-35E0C4.svg?style=flat-square&logo=github&logoColor=white&labelColor=0a0e12)](CONTRIBUTING.md)

<br/>

<p>
  <a href="#-what-it-does"><b>What It Does</b></a> &nbsp;·&nbsp;
  <a href="#-features"><b>Features</b></a> &nbsp;·&nbsp;
  <a href="#-architecture"><b>Architecture</b></a> &nbsp;·&nbsp;
  <a href="#-data-contract"><b>Data Contract</b></a> &nbsp;·&nbsp;
  <a href="#-detection"><b>Detection</b></a> &nbsp;·&nbsp;
  <a href="#-quick-start"><b>Quick Start</b></a> &nbsp;·&nbsp;
  <a href="#-deployment"><b>Deployment</b></a> &nbsp;·&nbsp;
  <a href="#-author"><b>Author</b></a>
</p>

</div>

---

## ✦ What It Does

**SPECTRE** turns two **ESP32-C5** WiFi boards — one sniffing 2.4GHz, one on 5GHz — into a live, dual-band **wireless intrusion-detection system**. Each board runs promiscuous-mode firmware that streams every management and data frame it hears as JSON over UART.

SPECTRE ingests both streams simultaneously, running attack-detection rules in real-time, rendering the threats in a beautiful, spectrum-analyzer–styled **SOC console**, and forwarding confirmed alerts to **Wazuh** as RFC 5424 syslog.

Built for seamless transitions, it can be developed and fully tested on a dev machine with the boards attached, then moved **unchanged** to a production LXC container on Proxmox.

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
    'fontFamily': 'monospace'
  }
}}%%
flowchart LR
    A((("📡 The Air\n(2.4GHz + 5GHz)"))) -->|"802.11 frames"| B["ESP32-C5 ×2\n(Promiscuous)"]
    B -->|"JSON Stream"| C(["🔌 UART"])
    C -->|"Ingest"| D{"SPECTRE Sensor"}
    D -->|"WebSocket"| E["SOC Console"]
    D -->|"RFC 5424"| F["Wazuh SIEM"]

    style A fill:#0a0e12,stroke:#9B8CFF,stroke-dasharray: 5 5,stroke-width:2px
    style B fill:#0a0e12,stroke:#35E0C4,stroke-width:2px
    style C fill:#0a0e12,stroke:#35E0C4,stroke-width:2px
    style D fill:#0a0e12,stroke:#35E0C4,stroke-width:3px
    style E fill:#0a0e12,stroke:#C9D6DF,stroke-width:2px
    style F fill:#0a0e12,stroke:#FF4D5E,stroke-width:2px
```

> 💡 **Why it matters:** A single passive board hears ~30 frames/second in a normal home environment. SPECTRE keeps a rolling raw window for forensics, distills the rest into a complete device and AP inventory, and sends *only threats and periodic summaries* upstream. Your SIEM stays sharp instead of drowning in millions of frames per day.

---

## ✦ Features

- 🎯 **Dual-band sensing** — 2.4GHz + 5GHz boards, each **auto-identified from its boot event** (USB re-enumeration can't mix them up).
- ⚡ **Real-time detection** — Detects deauth/disassoc floods, rogue APs, evil twins, beacon & probe floods, new devices, and RSSI anomalies. All server-side, tunable in Settings without reflashing.
- 🎛️ **SOC threat console** — Live frame feed, complete device & AP inventory, threat log with a severity spine, channel-utilization spectrum sweeps, and throughput trends. Crafted with a dark RF-instrument aesthetic.
- 🛡️ **Wazuh forwarding** — Native RFC 5424 over UDP/TCP. Syslog severity intelligently mapped from threat severity. Sends only threats and summaries to preserve SIEM efficiency. Editable at runtime.
- 💾 **Smart retention** — Rolling raw-frame window (default 48h) + long-term aggregates. A proactive disk-usage guard prunes early before the partition fills.
- 🔐 **Secure & Local** — Single-password console with a first-run setup wizard. Config & session state stored safely in SQLite.
- 🧪 **Hardware-free testing** — A built-in simulator generates realistic traffic and injectable attack scenarios. A replay mode allows playback of real `.pcap` / frame captures.

---

## ✦ Architecture

Two services configured elegantly via a single `docker-compose.yml`:

| Service | Stack | Port | Role |
|---|---|---|---|
| `sensor` | Python 3.11 · FastAPI · SQLite (stdlib core) | `8100` | UART ingest, detection, storage, Wazuh forwarding, API + WebSocket |
| `web` | Next.js 15 · Tailwind v4 · Recharts | `4100` | The Next.js SOC console |

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
    'fontFamily': 'monospace'
  }
}}%%
flowchart LR
    subgraph ESP["Hardware Sensors"]
        E1["[ESP32-C5 2.4G]"]
        E2["[ESP32-C5 5G]"]
    end

    subgraph Sensor["SPECTRE Sensor (Port 8100)"]
        R["Reader\n(async, DTR/RTS low)"]
        I["Ingest\n(strip PRI, tag, parse JSON)"]
        D{"Detection Engine"}
        S[("SQLite\n(frames / devices\naps / threats)")]
        W["WebSocket Server"]
        T["Summary Ticker"]
    end

    subgraph Output["SOC & SIEM"]
        N["Next.js Console"]
        Z["Wazuh (RFC 5424)"]
    end

    E1 -- "ttyUSB0" --> R
    E2 -- "ttyUSB1" --> R

    R --> I
    I -- "Stamp" --> D
    I --> S
    I --> W
    I --> T

    D -- "Threat Alerts" --> Z
    T -- "Tick Summaries" --> Z
    W -- "Live Stream" --> N

    style ESP fill:transparent,stroke:#9B8CFF,stroke-width:1px,stroke-dasharray: 5 5,color:#fff
    style Sensor fill:transparent,stroke:#35E0C4,stroke-width:1px,stroke-dasharray: 5 5,color:#fff
    style Output fill:transparent,stroke:#FF4D5E,stroke-width:1px,stroke-dasharray: 5 5,color:#fff

    style E1 fill:#0a0e12,stroke:#35E0C4,stroke-width:2px,color:#fff
    style E2 fill:#0a0e12,stroke:#35E0C4,stroke-width:2px,color:#fff
    style R fill:#0a0e12,stroke:#35E0C4,stroke-width:2px,color:#fff
    style I fill:#0a0e12,stroke:#35E0C4,stroke-width:2px,color:#fff
    style D fill:#0a0e12,stroke:#35E0C4,stroke-width:2px,color:#fff
    style S fill:#0a0e12,stroke:#F5A623,stroke-width:2px,color:#fff
    style W fill:#0a0e12,stroke:#35E0C4,stroke-width:2px,color:#fff
    style T fill:#0a0e12,stroke:#35E0C4,stroke-width:2px,color:#fff
    style N fill:#0a0e12,stroke:#C9D6DF,stroke-width:2px,color:#fff
    style Z fill:#0a0e12,stroke:#FF4D5E,stroke-width:2px,color:#fff
```

> **Deep Dive:** Full component walk-through in **[docs/architecture.md](docs/architecture.md)**.

---

## ✦ Data Contract

Verified live from the hardware — each UART line follows this strict format:

```json
<190>ESP32C5 wifi_sniffer: {"seq":47,"uptime_ms":2728,"ch":6,"rssi":-55,
                            "type":"BEACON","src":"..","dst":"..","bssid":"..","ssid":"ExampleNet"}
```

- `<190>` is a firmware-prepended syslog PRI (which SPECTRE strips).
- The board sends no wall clock; **SPECTRE natively stamps arrival times.**
- The `seq` identifier resets on reboot.
- Band identification comes reliably from the `{"event":"boot","band":"2.4GHz"}` event line.

> **Deep Dive:** Full schema and volume notes in **[docs/data-contract.md](docs/data-contract.md)**.

---

## ✦ Detection Rules

| Rule Name | Signature Logic | Default Severity |
|:---|:---|:---:|
| **Deauth / Disassoc Flood** | Spike in `DEAUTH` + `DISASSOC` frame rate per BSSID over a rolling window. | <kbd style="background:#FF4D5E;color:#000;">&nbsp;HIGH&nbsp;</kbd> |
| **Rogue AP / Evil Twin** | Trusted SSID broadcasted from an un-allowlisted BSSID or wrong band. | <kbd style="background:#b91c1c;color:#fff;">&nbsp;CRITICAL&nbsp;</kbd> |
| **Beacon / Probe Flood** | Abnormal count of distinct beaconing BSSIDs or heavy probe bursts. | <kbd style="background:#F5A623;color:#000;">&nbsp;MEDIUM&nbsp;</kbd> |
| **New Device / RSSI Anomaly**| First-seen client MAC addresses or sharp RSSI delta jumps. | <kbd style="background:#35E0C4;color:#000;">&nbsp;LOW&nbsp;</kbd> |

**All rules are fully tunable.** Windows, thresholds, and severities can be edited via the UI in **Settings**. Details and tuning guidance are in **[docs/detection-rules.md](docs/detection-rules.md)**.

---

## ✦ Quick Start

```bash
git clone <your-remote> spectre && cd spectre
bash init.sh                 # Generates .env + SPECTRE_SECRET, prompts for host IP
docker compose up -d --build
# Open http://<host>:4100  → Finish the setup wizard
```

### 🧪 No boards attached?
Run the integrated simulator instead. Set `SPECTRE_SOURCE=sim` in your `.env`, then run `docker compose up`. The console will fill with beautiful synthetic traffic and rotating attack scenarios.

---

## ✦ Configuration

Everything has a sensible default in `.env` (see `.env.example`) and can be dynamically changed at runtime from **Settings** (persisted in SQLite).

| Key | Default Value | Description |
|---|---|---|
| `SERIAL_PORTS` | `/dev/ttyUSB0,/dev/ttyUSB1` | Target boards (band is auto-detected). |
| `SPECTRE_SOURCE` | `serial` | Run mode: `serial` · `sim` · `replay`. |
| `WAZUH_HOST` / `WAZUH_PORT` | `10.0.0.20` / `514` | Target SIEM syslog destination. |
| `RAW_RETENTION_HOURS` | `48` | Window for rolling raw-frame retention. |
| `DISK_GUARD_PERCENT` | `85` | Early-prune threshold to prevent full disk. |

---

## ✦ Wazuh Integration

Threats and summaries are natively sent as **RFC 5424** (`app-name=spectre`). Syslog severity is automatically mapped from the threat severity level:
- `critical` → `crit`
- `high` → `alert`
- `medium` → `warning`
- `low` → `notice`
- `summary` → `info`

A sample decoder and ruleset to drop these perfectly into Wazuh live in **[docs/wazuh-integration.md](docs/wazuh-integration.md)**.

---

## ✦ Deployment

Develop and test your configuration locally, then move the exact same compose configuration to your Proxmox LXC; **only `.env` needs to change.**

Unprivileged LXCs require the USB adapters to be passed through via `lxc.cgroup2.devices.allow` + `lxc.mount.entry`. The exact steps, alongside the host-reader fallback strategy, are fully documented in **[docs/deployment.md](docs/deployment.md)**.

---

## ✦ Author

Built by **[gurvinny](https://github.com/gurvinny)**.

Licensed under the **GNU AGPL-3.0-or-later** — see [LICENSE](LICENSE). Copyright © 2026 gurvinny.
If you host a modified version, the AGPL requires you to publish your changes under the same open license.

**Commercial License:** To use SPECTRE in a closed-source or commercial product without the AGPL's source-disclosure obligations, a separate commercial license is available — reach out via [github.com/gurvinny](https://github.com/gurvinny).

<br/>

<div align="center">
  <sub>SPECTRE · Signal Processing &amp; Electromagnetic Threat Reconnaissance Engine</sub>
</div>
