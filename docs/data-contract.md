# Data Contract — ESP32-C5 UART

This is the wire format SPECTRE ingests, verified live from the hardware (2.4GHz board on
`/dev/ttyUSB0`, 115200 baud, DTR/RTS held low so the board does not reset on open).

## Line format

Every line the firmware emits looks like:

```
<190>ESP32C5 wifi_sniffer: {<json>}
```

| Segment | Meaning | Handling |
|---|---|---|
| `<190>` | Syslog PRI the firmware prepends — facility `local7` (23), severity `info` (6). | Stripped by the parser. |
| `ESP32C5 wifi_sniffer:` | Source tag. | Stripped. |
| `{…}` | The event payload (JSON object). | Parsed. |

Boot-ROM banner lines (`ESP-ROM:esp32c5-eco2-…`, `Build:…`, `rst:…`) carry no JSON and are ignored.

## Frame events

```json
{"seq":47,"uptime_ms":2728,"ch":6,"rssi":-55,"type":"BEACON",
 "src":"00:00:5E:00:53:01","dst":"FF:FF:FF:FF:FF:FF",
 "bssid":"00:00:5E:00:53:01","ssid":"ExampleNet"}
```

| Field | Type | Notes |
|---|---|---|
| `seq` | int | Monotonic counter — **resets on board reboot**. |
| `uptime_ms` | int | Milliseconds since boot. **No wall clock** — SPECTRE stamps `received_at` at ingest. |
| `ch` | int | Channel (2.4GHz 1–13, 5GHz 36–165). The board channel-hops. |
| `rssi` | int | dBm. |
| `type` | str | `BEACON`, `DATA`, `PROBE_REQ`, `PROBE_RESP`, `DEAUTH`, `DISASSOC`, `AUTH`, … |
| `src` / `dst` / `bssid` | str | MACs. Broadcast is `FF:FF:FF:FF:FF:FF`. |
| `ssid` | str | `"?"` (or empty) means hidden/unknown → normalized to `null`. |

Unknown keys are preserved in `Event.extra` (tolerant parsing) so firmware additions don't break
ingest.

## Lifecycle events

```json
{"event":"boot","chip":"ESP32-C5","mode":"promiscuous","band":"2.4GHz","channels":"1-13"}
{"event":"sniffer_started","ch":1,"usb_cdc":true}
```

The **`band` from the `boot` event is latched** per board — this is how SPECTRE labels a board's
frames regardless of which `/dev/ttyUSB*` it enumerated as.

## Volume

~30 frames/sec per board in a normal environment (measured: 46 frames in 1.5s), so **~50–60/sec /
~4–5M/day** across both bands. This is why raw frames are kept only in a rolling window and are
**never** forwarded to Wazuh — only threats and summaries are.

## Canonical event

After parsing, the internal shape (`spectre/models.py::Event`) is:

```python
Event(received_at, sensor_id, band, frame_type, ch, rssi, seq,
      uptime_ms, src, dst, bssid, ssid, extra)
```

_Author: gurvinny · Project: SPECTRE_
