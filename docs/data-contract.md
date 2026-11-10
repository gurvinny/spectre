# Data Contract: ESP32-C5 UART

This is the wire format SPECTRE ingests. Two firmwares speak it:

- the **original** sniffer firmware, verified live from the hardware (2.4GHz board on `/dev/ttyUSB0`,
  **115200** baud), and
- the open **v2** firmware in [`firmware/`](../firmware/README.md), at **460800** baud, which keeps every
  original key and only adds new ones.

Either way the port is opened with DTR/RTS held low so the board does not reset on open. Set
`SERIAL_BAUD` to the firmware's rate (`115200` or `460800`; `921600` is mapped but not yet soaked).
Any other value stops the sensor at startup: reading at the wrong speed produces garbage that would
otherwise look like a quiet board.

## Line format

Every line the firmware emits looks like:

```
<190>ESP32C5 wifi_sniffer: {<json>}
```

| Segment | Meaning | Handling |
|---|---|---|
| `<190>` | Syslog PRI the firmware prepends: facility `local7` (23), severity `info` (6). | Stripped by the parser. |
| `ESP32C5 wifi_sniffer:` | Source tag. | Stripped. |
| `{…}` | The event payload (JSON object). | Parsed. |

Boot-ROM banner lines (`ESP-ROM:esp32c5-eco2-…`, `Build:…`, `rst:…`) carry no JSON and are ignored.
Lines with `"type"` are frames; lines with `"event"` are everything else.

## Frame events

```json
{"seq":47,"uptime_ms":2728,"ch":6,"rssi":-55,"type":"BEACON",
 "src":"00:00:5E:00:53:01","dst":"FF:FF:FF:FF:FF:FF",
 "bssid":"00:00:5E:00:53:01","ssid":"ExampleNet"}
```

| Field | Type | Notes |
|---|---|---|
| `seq` | int | Frame lines emitted since boot. **Resets on board reboot.** A gap is a line lost between the board and the host. |
| `uptime_ms` | int | Milliseconds since boot. **No wall clock**: SPECTRE stamps `received_at` at ingest. |
| `ch` | int | Channel the radio was tuned to (2.4GHz 1–13, 5GHz 36–165). The board channel-hops. |
| `rssi` | int | dBm. |
| `type` | str | `BEACON`, `DATA`, `PROBE_REQ`, `PROBE_RESP`, `DEAUTH`, `DISASSOC`, `AUTH`, … |
| `src` / `dst` / `bssid` | str | MACs, upper-cased. Broadcast is `FF:FF:FF:FF:FF:FF`. |
| `ssid` | str | `"?"` (or empty) means hidden/unknown, normalized to `null`. |

### v2 frame keys

The v2 firmware adds the keys below. Each becomes a typed, nullable `frames` column; lines from the
original firmware leave them all `NULL`. A value of the wrong JSON type is stored as `NULL` rather
than coerced. Meanings are in the [firmware README](../firmware/README.md#frame-lines).

| Wire key | Column | Type |
|---|---|---|
| `sub` | `sub` | int, exact 802.11 subtype |
| `nf` | `nf` | int, noise floor dBm |
| `phy` / `mcs` / `bw` / `rate` | `phy` / `mcs` / `bw` / `rate` | str / int / int (MHz) / int |
| `ts` | `ts_us` | int, radio µs timestamp, 32-bit, wraps ~71 min |
| `sn` | `sn` | int, 802.11 sequence number |
| `fl` | `fc_flags` | int, frame-control flag byte (`0x08` retry, `0x40` protected, …) |
| `dur` | `dur` | int, Duration/ID |
| `reason` | `reason` | int, deauth/disassoc reason (unprotected frames only) |
| `aalg` / `aseq` / `st` | `auth_alg` / `auth_seq` / `status` | int, auth frames |
| `eapol` | `eapol` | int, 1–4 handshake message, 5 group key, 6 other |
| `fp` | `probe_fp` | str, probe-request element fingerprint |
| `ouis` | `ouis` | list of str on the wire, stored comma-joined |

Keys outside both tables are kept in `Event.extra` (tolerant parsing) and not stored. The firmware's
own contract check (`make -C firmware/test samples`) runs every sample line through this parser and
fails if a frame key reaches `extra`, so a firmware addition cannot be dropped silently.

## Lifecycle events

```json
{"event":"boot","chip":"ESP32-C5","mode":"promiscuous","band":"2.4GHz","channels":"1-13"}
{"event":"sniffer_started","ch":1,"usb_cdc":true}
{"event":"channel_sweep_complete","total_pkts":84,"uptime_ms":16570}
```

The **`band` from the `boot` event is latched** per board: this is how SPECTRE labels a board's
frames regardless of which `/dev/ttyUSB*` it enumerated as. The v2 firmware can switch band by
command without rebooting, so a `cmd_ack` with `"ok":true` re-latches `config.band` too; a failed
command changes nothing.

Every lifecycle line is stored in the `board_events` table (`received_at`, `sensor_id`, latched
`band`, `kind` = the `event` value, and the remaining keys as JSON `payload`), on the same rolling
retention window and disk guard as raw frames. A `boot` row marks a board reboot, which is also where
`seq` restarts; `total_pkts` on `channel_sweep_complete` is the firmware's own line count.

The v2 firmware adds these kinds, stored the same way:

| `kind` | Payload highlights |
|---|---|
| `boot` (extended) | `fw`, `ver`, `elf_sha`, `reset`, `baud`, `caps`, and the radio plan: `channels`, `dwell_ms`, `pin`, `filter`, `dedup`, `ap_info_s` |
| `channel_sweep_complete` (extended) | `sweep_ms` and the counters `rx_total`, `emitted`, `drop_queue`, `drop_short`, `drop_dedup`, `drop_overflow` |
| `telemetry` | the counters, ring-buffer `q_hwm` / `q_size`, `heap`, `heap_min`, `temp_dc`, `uart_bps` |
| `clock_sync` | `uptime_ms` and the 64-bit `mono_us`, for mapping `ts_us` onto host time |
| `cmd_ack` | `cmd`, `id`, `ok`, `err`, and the resulting `config` |
| `cmd` | Written by the sensor, not the board: one audit row per console command, with `id`, the `command` as sent, the `user`, and `sent` (bytes) or `error` |

### `ap_info`

`ap_info` lines (one AP's advertised security and capabilities, sent on first sighting, on change and
every `ap_info_s` seconds) go to their own **`ap_info`** table instead of `board_events`: `received_at`,
`sensor_id`, `band`, `bssid` (upper-cased), `why`, `ch`, `ds_ch`, `ssid` (`"?"` → `NULL`), `sec`,
`pmf`, the 0/1 flags `wpa1`, `ht`, `vht`, `he`, `eht`, `wps`, the element `hash`, and the whole line
as JSON `payload` (`akm`, `pairwise`, `group`, `csa`, `ouis`, …). Same retention and disk guard as raw
frames.

## Commands

The v2 firmware reads one JSON object per line on the same UART (reference in the
[firmware README](../firmware/README.md#commands)). `SerialReader.send()` writes one: a dict is sent
as compact JSON, a line break inside it is refused, and a command over **254 bytes** (the board's
buffer, less its terminator) is refused before it is written. Writes are serialized per port, and a
port that does not drain within 2 s raises instead of blocking. Every reply arrives as a `cmd_ack`
lifecycle line.

From the console, `POST /api/boards/{id}/cmd` sends one, only when the sensor runs with
`SPECTRE_BOARD_CONTROL=true` (otherwise `403`, and nothing is written). It accepts `get_config`,
`set`, `reset_config` and `reboot`, adds an `id` when the body has none, writes the `cmd` audit row
stamped before the send, and waits up to 3 s for the `cmd_ack` carrying that `id`. A command the
sensor refuses before writing (too long, not one line) is `400`; a port that is closed or does not
drain is `502`. Both are audited too. `GET /api/boards` reduces the newest row of each kind per
board to firmware, radio plan (the boot plan, or a newer successful `cmd_ack`'s), and health:
loss is `drop_queue + drop_overflow` over `rx_total` (`drop_short` and `drop_dedup` are not losses),
UART load is `uart_bps × 10` over the boot `baud` (8N1).

## Schema migration

`frames` only ever gains columns. On startup the store compares `frames` with the current column list
and adds whatever is missing (`ALTER TABLE … ADD COLUMN`, no default, so existing rows are not
rewritten and read the new columns as `NULL`). It runs on every start and is a no-op once current, so
a database from any earlier release upgrades in place, and a fresh one ends up with identical columns.

## Volume

~30 frames/sec per board in a normal environment (measured: 46 frames in 1.5s), so **~50–60/sec /
~4–5M/day** across both bands. At 115200 baud (~11.5 KB/s) and a ~190-byte line, the original
firmware tops out at an estimated ~60 lines/sec per board; the v2 firmware's ceiling at 460800 will
be documented after a long soak. Raw frames are kept only in a rolling window and are **never**
forwarded to Wazuh: only threats and summaries are.

## Canonical event

After parsing, the internal shape (`spectre/models.py::Event`) is:

```python
Event(received_at, sensor_id, band, frame_type, ch, rssi, seq,
      uptime_ms, src, dst, bssid, ssid,
      # v2 firmware, None otherwise:
      sub, nf, phy, mcs, bw, rate, ts_us, sn, fc_flags, dur, reason,
      auth_alg, auth_seq, status, eapol, probe_fp, ouis,
      extra)
```

`models.FRAME_COLUMNS` lists the `frames` columns in `Event.to_row()` order.

_Author: gurvinny · Project: SPECTRE_
