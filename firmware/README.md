# SPECTRE sniffer firmware

Open ESP-IDF firmware for the **ESP32-C5** that turns one board into a receive-only 802.11 monitor and
streams what it hears to the SPECTRE sensor as JSON lines over UART. One image serves both bands; the
band, channel list and dwell are set at runtime and kept in NVS.

The radio never transmits: Wi-Fi runs in `NULL` mode with promiscuous receive only. That is why the full
2.4 GHz (1-14) and 5 GHz (36-177) channel lists can be monitored without assuming a regulatory domain.
Which of them you actually hop is up to you.

## Layout

| Path | What it is |
|---|---|
| `spectre-sniffer/main/app_main.c` | ESP-IDF glue: radio, ring buffer, UART, NVS, tasks |
| `spectre-sniffer/main/core/` | Portable C with no IDF dependency: 802.11 + IE decoding, line format, commands |
| `test/` | Host test suite for `core/` (ASan + UBSan), sample-line contract check |
| `scripts/mutate.py` | Mutation runner: proves the host tests can fail |
| `flash.py` | Flash a board and verify its boot line against the image (tests in `sensor/tests/test_flash_tool.py`) |

## Build

Requires ESP-IDF **v5.5** or later with the `esp32c5` target installed.

```bash
. $IDF_PATH/export.sh
cd firmware/spectre-sniffer
idf.py set-target esp32c5   # first time only
idf.py build
```

## Flash

Stop whatever reads the port first (the sensor, a serial monitor): two readers on one port each see
half the lines. Then:

```bash
python3 firmware/flash.py --port /dev/ttyUSB0 --band 2.4GHz
python3 firmware/flash.py --port /dev/ttyUSB1 --band 5GHz
```

`flash.py` flashes the build in `spectre-sniffer/build/` (or `--build DIR`, e.g. the unpacked `Firmware
build` CI artifact, whose `SHA256SUMS` it checks first) with esptool via `uvx` at 460800 baud. It then sets
the band by command, restores that band's default plan (`--keep-config` keeps the current one), reboots the
board by command and checks the new `boot` line against the image: firmware name, version, ELF sha256,
band, baud and the acknowledged plan. After `sniffer_started` it soaks for 10 s (`--soak N`): every line
must parse and frame `seq` must not skip. It prints a JSON report with the sha256 of every image file on
stdout (esptool's output goes to stderr). Any mismatch or silence exits non-zero. `--verify-only` skips the flash and
checks a board that is already running the image. Needs Python 3.10+ and
[uv](https://docs.astral.sh/uv/); nothing else.

Plain `idf.py -p /dev/ttyUSB0 -b 460800 flash` works too. A fresh board then boots on the 2.4 GHz plan; to
make it the 5 GHz board send `{"cmd":"set","band":"5GHz"}` (see below). The choice is saved in NVS and
survives reflashing the app.

The sensor must read at the same speed: set `SERIAL_BAUD=460800` in its `.env` before starting it again.

### Before the first flash: keep a way back

Read the board's whole flash once, before flashing this firmware over whatever it runs now:

```bash
uvx --from esptool==5.6.0 esptool --port /dev/ttyUSB0 --baud 460800 read-flash 0 ALL backup.bin
```

Read it twice and compare the files; keep the backup private, since NVS can hold credentials and
the board's MAC. 921600 baud is not reliable on every USB-serial adapter; 460800 is.

### Rollback

```bash
uvx --from esptool==5.6.0 esptool --port /dev/ttyUSB0 --baud 460800 write-flash 0 backup.bin
```

This restores the old application, partition table and NVS exactly as read. Then set the sensor's
`SERIAL_BAUD` back to what the old firmware used (115200 for the original sketch) and start it again.

**Opening the port must not reset the board.** Most ESP32 dev boards wire DTR/RTS to EN/IO0. The sensor
opens the port with DTR and RTS held low; any other reader should too, or each open reboots the board and
restarts `seq`.

## Host tests

```bash
cd firmware/test
make            # ASan + UBSan, test and assertion floors enforced
make samples    # also checks every line kind against the sensor's real parser
python3 ../scripts/mutate.py
```

## Wire format

Every line is `<190>ESP32C5 wifi_sniffer: {json}\n` at **460800 baud**, 8N1. Lines with `"type"` are frames;
lines with `"event"` are everything else. The keys of the original firmware (`seq`, `uptime_ms`, `ch`, `rssi`,
`type`, `src`, `dst`, `bssid`, `ssid`) keep their names and meanings; everything else is additive, so an older
sensor still ingests these lines.

### Frame lines

```json
{"seq":47,"uptime_ms":2728,"ch":6,"rssi":-52,"type":"BEACON","sub":8,
 "src":"00:00:5E:00:53:01","dst":"FF:FF:FF:FF:FF:FF","bssid":"00:00:5E:00:53:01","ssid":"ExampleNet",
 "nf":-95,"phy":"g","bw":20,"rate":11,"ts":123456789,"sn":100,"fl":0,"dur":314}
```

| Key | Meaning |
|---|---|
| `seq` | Frame lines emitted since boot (1, 2, 3, ...). Resets on reboot. A gap means a line was lost between the board and the host. |
| `ch` | The channel the radio was tuned to when it heard the frame. This is not the AP's advertised channel, which can differ when a frame leaks onto an adjacent channel (`ap_info.ds_ch` has that one). |
| `type` / `sub` | Frame type name (unchanged from the original firmware) and the exact 802.11 subtype. Subtypes without their own name report `MGMT`. |
| `src` / `dst` / `bssid` | Transmitter (addr2), receiver (addr1), BSSID resolved from the To/From-DS bits. Omitted when the frame does not carry them (CTS/ACK have no transmitter, 4-address frames have no single BSSID). |
| `ssid` | Only on frames that carry an SSID element. Hidden or zeroed SSIDs are `"?"`. Valid UTF-8 passes through; invalid bytes become `\u00XX`. |
| `nf` | Noise floor, dBm. |
| `phy` / `mcs` / `bw` | PHY format (`b`, `g`, `a`, `n`, `ac`, `ax`, ...), MCS where it applies, bandwidth in MHz decoded from the SIG field. |
| `rate` | Legacy rate code (11b/a/g only). |
| `ts` | Radio receive timestamp, µs, 32-bit, wraps about every 71 minutes. |
| `sn` | 802.11 sequence number (0-4095). |
| `fl` | Frame-control flag byte: `0x01` ToDS, `0x02` FromDS, `0x04` more fragments, `0x08` retry, `0x10` power management, `0x20` more data, `0x40` protected, `0x80` order. |
| `dur` | Duration/ID field. |
| `reason` | Deauth/disassoc reason code. Only present when the frame is unprotected; with PMF it is encrypted. |
| `aalg` / `aseq` / `st` | Authentication algorithm, transaction sequence and status code (auth frames). |
| `eapol` | `1`-`4` = message number of a 4-way handshake, `5` = group key handshake, `6` = other EAPOL (EAP, Start, Logoff). |
| `fp` / `ouis` | Probe requests only: a hash of the element-ID order and vendor element types (independent of the SSID text and the MAC), plus the vendor OUIs. Lets a client be counted across MAC randomization. |

Data frames are copied header-only (64 bytes), which is enough for the header, the LLC header and the
EAPOL key information. Payloads never leave the board.

### Event lines

| `event` | When | Content |
|---|---|---|
| `boot` | Once at start | `chip`, `mode`, `band`, `channels` (`"1-13"` / `"36-165"` for the defaults, else a list), `dwell_ms`, `pin`, `filter`, `dedup`, `ap_info_s`, `fw`, `ver`, `elf_sha` (first 16 hex chars of the ELF sha256), `reset` reason, `baud`, `caps` |
| `sniffer_started` | After the radio is up | `ch` |
| `channel_sweep_complete` | Each pass through the channel list | `total_pkts` (= `emitted`, as in the original firmware), `sweep_ms`, counters |
| `telemetry` | Every 10 s | counters, `q_hwm` / `q_size` (ring buffer bytes), `heap`, `heap_min`, `temp_dc` (chip temperature, 0.1 °C), `uart_bps` |
| `clock_sync` | Every 10 s | `uptime_ms` and the 64-bit monotonic `mono_us`, for mapping `ts` onto host time |
| `ap_info` | First beacon/probe response from a BSSID, whenever its advertised configuration changes, and every `ap_info_s` seconds | `bssid`, `ch`, `ds_ch`, `ssid`, beacon interval `bi`, capability `cap`, `sec` (`OPEN`, `WEP`, `WPA`, `WPA2`, `WPA2/WPA3`, `WPA3`, `OWE`, `ENT`), `akm`, `pairwise`, `group`, `pmf` (`none` / `capable` / `required`), `wpa1`, `ht`, `vht`, `he`, `eht`, `ht_sec`, `wps`, `csa` (`mode`, `ch`, `count`), `ouis`, `hash` |
| `cmd_ack` | After every command | `cmd`, `id`, `ok`, `err`, the resulting `config` |

### Counters

| Counter | Meaning |
|---|---|
| `rx_total` | Frames the Wi-Fi driver delivered to the callback |
| `emitted` | Frame lines written (equal to the last `seq`) |
| `drop_queue` | Frames lost because the ring buffer was full, i.e. the UART could not keep up |
| `drop_short` | Frames too short or malformed to decode |
| `drop_dedup` | Beacons suppressed by dedup mode |
| `drop_overflow` | Lines that would not fit the line buffer |

`rx_total = emitted + drop_queue + drop_short + drop_dedup + drop_overflow`, give or take frames still in
the ring buffer. Frames the radio never delivered (it was retuning, or the frame failed its FCS) are not
counted anywhere.

## Commands

One JSON object per line, sent to the board's UART. Flat objects only: strings, integers, booleans and
arrays of those. No escapes, no floats.

| Command | Effect |
|---|---|
| `{"cmd":"get_config"}` | Ack with the current config |
| `{"cmd":"set", ...}` | Apply and save the given keys |
| `{"cmd":"reset_config"}` | Back to the defaults for the current band |
| `{"cmd":"reboot"}` | Ack, then restart |

An optional `"id":"..."` (up to 16 characters) is echoed in the ack.

| `set` key | Values | Default 2.4 GHz / 5 GHz |
|---|---|---|
| `band` | `"2.4GHz"`, `"5GHz"`. Switching band resets the plan to that band's defaults. | |
| `channels` | 1-32 unique channels valid for the band | `1-13` / `36-64, 100-144, 149-165` |
| `dwell_ms` | 50-5000 | `300` / `200` (sweeps of ~3.9 s / ~5.0 s) |
| `pin` | `0` to hop, or one channel to stay on | `0` |
| `filter` | Any of `"mgmt"`, `"ctrl"`, `"data"` | `["mgmt","data"]` |
| `dedup` | `0` / `1`. With `1`, a BSSID's beacon is emitted once per dwell. This changes what beacon-count rules see. | `0` |
| `ap_info_s` | 0-3600. Periodic `ap_info` resend; `0` sends on change only. | `300` |

Invalid input changes nothing and acks with `ok: false` and an `err`: `bad json`, `missing cmd`,
`unknown cmd`, `unknown key`, `bad band`, `bad channel`, `bad dwell`, `bad pin`, `bad filter`,
`bad value` or `line too long`.

## Limits

- **One channel at a time.** While hopping, a board hears each channel for `dwell_ms` out of every sweep.
  An event shorter than a sweep can be missed; pin a channel to watch one closely.
- **20/40 MHz receive.** The C5 decodes 802.11a/b/g/n/ac/ax at 20 MHz and 802.11n at 40 MHz. Wider
  (80/160 MHz) PPDUs are not received. Beacons and other management frames are still sent at 20 MHz
  and are seen.
- **460800 baud** is about 46 KB/s. At a typical 280-300 byte line that is an estimated ~150 frame lines per
  second; the measured ceiling will be documented after a long soak. Anything above it is counted in
  `drop_queue` rather than lost silently.
- `mcs` and `bw` are decoded from the PHY SIG field per the IEEE 802.11 layout; VHT/HE MU frames report no MCS.

_Author: gurvinny · Project: SPECTRE_
