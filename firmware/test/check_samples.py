#!/usr/bin/env python3
"""Check every sample line the firmware tests wrote.

Each line must carry the syslog prefix, hold exactly one valid JSON object,
and be ingested by the sensor's real parser: frame lines become Events with
the original keys intact and every other key typed (none left in ``extra``),
every other line is routed as a lifecycle event.
This is the firmware-to-sensor contract, checked without hardware.

Author: gurvinny
Project: SPECTRE
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "sensor"))

from spectre.parser import Parser  # noqa: E402

PREFIX = "<190>ESP32C5 wifi_sniffer: "
EXPECTED_EVENTS = {"boot", "sniffer_started", "channel_sweep_complete",
                   "telemetry", "clock_sync", "cmd_ack", "ap_info"}
MIN_FRAMES = 7


def main(path: str) -> int:
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    errors: list[str] = []
    events: set[str] = set()
    frames = 0
    lifecycle: list[dict] = []
    parser = Parser("ttyTEST", on_lifecycle=lifecycle.append)

    for n, line in enumerate(lines, 1):
        if not line.startswith(PREFIX):
            errors.append(f"line {n}: missing prefix")
            continue
        try:
            obj = json.loads(line[len(PREFIX):])
        except json.JSONDecodeError as exc:
            errors.append(f"line {n}: invalid JSON: {exc}")
            continue
        before = len(lifecycle)
        event = parser.parse_line(line)
        if "type" in obj:
            frames += 1
            if event is None:
                errors.append(f"line {n}: frame line not parsed")
                continue
            if event.frame_type != obj["type"] or event.seq != obj["seq"]:
                errors.append(f"line {n}: type/seq mismatch")
            if event.ch != obj["ch"] or event.rssi != obj["rssi"]:
                errors.append(f"line {n}: ch/rssi mismatch")
            if "src" in obj and event.src != obj["src"]:
                errors.append(f"line {n}: src mismatch")
            if event.extra:
                errors.append(f"line {n}: keys the sensor does not type: {sorted(event.extra)}")
        else:
            events.add(obj.get("event", "?"))
            if event is not None or len(lifecycle) != before + 1:
                errors.append(f"line {n}: lifecycle line not routed")

    missing = EXPECTED_EVENTS - events
    if missing:
        errors.append(f"no sample for: {sorted(missing)}")
    if frames < MIN_FRAMES:
        errors.append(f"only {frames} frame samples, floor is {MIN_FRAMES}")
    if parser.malformed:
        errors.append(f"parser counted {parser.malformed} malformed lines")

    for e in errors:
        print(f"FAIL: {e}")
    print(f"{len(lines)} sample lines, {frames} frames, {len(events)} event kinds, "
          f"{len(errors)} errors")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "out/samples.txt"))
