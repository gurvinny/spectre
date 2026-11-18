# Changelog

All notable changes to SPECTRE. Versions follow [Semantic Versioning](https://semver.org/). The sensor and
web console share one version; the firmware has its own (`firmware/spectre-sniffer/version.txt`), and each
release names the firmware it ships.

## [1.0.0-beta.1] - 2026-11-18

First tagged release. Sensor and console `1.0.0-beta.1`, firmware `2.1.0`.

### Firmware (2.1.0)
- Open ESP-IDF sniffer for the ESP32-C5, one image for both bands. The band, channel plan and dwell are set
  by command and kept in NVS.
- Each frame carries its radio and 802.11 detail, a sequence number and the board's uptime. Periodic
  telemetry reports receive and drop counters, queue use, heap, stack, temperature and link throughput.
- Streams over the chip's native USB port (USB-Serial-JTAG) when a host is attached, with a bounded write
  timeout and a `drop_usb` counter. The UART stays available at 921600 baud.
- A 64 KiB receive ring, with ring accounting that no longer overshoots.
- Console logs are kept off the data lines.
- `firmware/flash.py` flashes a CI or local image, verifies it against its app descriptor and `SHA256SUMS`,
  and soaks the result.

### Sensor
- Ingests the v2 line contract, and stores board lifecycle events (boots, bad lines with their raw bytes)
  and telemetry.
- Board health panel, with board control behind a setting.
- Native USB serial ports, with a reader that reopens a port that goes away.
- Detection:
  - Deauth floods skip retransmissions and protected frames.
  - Beacon and probe floods are counted per band, and probe floods name their loudest sources.
  - Probe floods need a floor of distinct sources (`probe_flood_min_sources`, default 40).
  - Evil-twin bands are pinned per BSSID.
  - An RSSI anomaly must hold for the next reading, compared per channel.
  - Stored AP info is restored into detection at startup.
- API reads and store writes stay off the event loop. A slow WebSocket client drops its oldest batch.
- Cross-origin access is restricted, password attempts are throttled and row limits are bounded.
- Every detection is mapped to ATT&CK, and Wazuh severities are corrected.
- The simulator and replay emit v2 firmware lines.

### Console
- The firmware card follows the running image.
- The 3D battlespace view is behind an experimental flag.
- A setting for the probe-flood source floor.
- The live threat window loads the stored recent threats on every connect, so the active count, the
  Active threats panel and the radar include threats from before the page opened.
- The Boards page follows each board's data link: UART load on a UART, throughput and refused lines
  on native USB.
- A brand mark, favicon set and web manifest. The header mark follows the active skin.

### Documentation
- Refreshed screenshots from the simulator, a four-skin showcase, and example addresses in the
  documentation ranges (RFC 5737).

### Quality
- Floored unit suites with curated mutation catalogues for the sensor, console, firmware and flash tool.
- Browser QA against a simulated sensor, CodeQL, and Trivy repository and image scans in CI.

### Flashing
See [docs/flashing.md](docs/flashing.md). The release assets are the application image (the same for both bands),
its ELF, the bootloader, the partition table, `flasher_args.json` and `SHA256SUMS`. Check the sums before flashing; `flash.py` checks them again.
