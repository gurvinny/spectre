"""Turn raw UART lines into canonical :class:`Event` objects.

Wire format observed live from the ESP32-C5 firmware::

    <190>ESP32C5 wifi_sniffer: {"seq":47,"uptime_ms":2728,"ch":6,"rssi":-55,
                                "type":"BEACON","src":"..","dst":"..",
                                "bssid":"..","ssid":"ExampleNet"}

* ``<190>`` is a syslog PRI the firmware prepends (local7.info) — stripped.
* ``ESP32C5 wifi_sniffer:`` is a tag — stripped.
* Lifecycle lines carry ``"event"`` instead of ``"type"``; the ``boot`` event
  declares the board's band, which we latch so every subsequent frame from that
  board is labelled correctly regardless of USB enumeration order.
* Boot-ROM banner lines (``ESP-ROM:...``) contain no JSON and are ignored.

Author: gurvinny
Project: SPECTRE
"""
from __future__ import annotations

import json
import re
from typing import Optional

from .models import Event, now

# Strip an optional leading "<PRI>" and an optional "word word:" tag, then we
# hunt for the JSON body starting at the first "{".
_PRI_RE = re.compile(r"^<\d{1,3}>")


def _extract_json(line: str) -> Optional[dict]:
    """Return the JSON object embedded in *line*, or None if there isn't one."""
    start = line.find("{")
    end = line.rfind("}")
    if start == -1 or end == -1 or end < start:
        return None
    try:
        obj = json.loads(line[start:end + 1])
        return obj if isinstance(obj, dict) else None
    except (ValueError, json.JSONDecodeError):
        return None


class Parser:
    """Stateful per-board parser. One instance per serial port.

    Holds the latched band for this board and a running malformed-line counter
    for observability.
    """

    def __init__(self, sensor_id: str, default_band: str = "unknown") -> None:
        self.sensor_id = sensor_id
        self.band = default_band
        self.malformed = 0
        self.last_event_kind: Optional[str] = None

    def parse_line(self, raw: str) -> Optional[Event]:
        """Parse one line. Returns an :class:`Event` for frame lines.

        Lifecycle lines (boot / sniffer_started) update internal state and
        return ``None``. Non-JSON noise increments ``malformed`` and returns
        ``None``.
        """
        line = _PRI_RE.sub("", raw.strip())
        if not line:
            return None

        obj = _extract_json(line)
        if obj is None:
            # Boot-ROM banners and other noise land here — only count lines that
            # looked like they wanted to be data.
            if "{" in line:
                self.malformed += 1
            return None

        # ── Lifecycle events (no "type", carry "event") ────────────────
        if "event" in obj and "type" not in obj:
            kind = str(obj.get("event"))
            self.last_event_kind = kind
            if kind == "boot":
                band = obj.get("band")
                if isinstance(band, str) and band:
                    self.band = band
            return None

        # ── Frame events ───────────────────────────────────────────────
        frame_type = obj.get("type")
        if not isinstance(frame_type, str):
            self.malformed += 1
            return None

        ch = _as_int(obj.get("ch"))
        # Band is normally latched from the boot event. If we never saw one
        # (e.g. the board was already running when the port opened, since the
        # DTR/RTS-low open intentionally avoids resetting it), fall back to the
        # channel: 1–14 → 2.4 GHz, 32+ → 5 GHz. Latch it so it stays stable.
        if self.band == "unknown" and ch is not None:
            self.band = "5GHz" if ch >= 32 else "2.4GHz"

        ssid = obj.get("ssid")
        if ssid == "?" or ssid == "":
            ssid = None

        # Preserve any unexpected keys for forward-compatibility.
        known = {"seq", "uptime_ms", "ch", "rssi", "type",
                 "src", "dst", "bssid", "ssid"}
        extra = {k: v for k, v in obj.items() if k not in known}

        return Event(
            received_at=now(),
            sensor_id=self.sensor_id,
            band=self.band,
            frame_type=frame_type.upper(),
            ch=ch,
            rssi=_as_int(obj.get("rssi")),
            seq=_as_int(obj.get("seq")),
            uptime_ms=_as_int(obj.get("uptime_ms")),
            src=_as_mac(obj.get("src")),
            dst=_as_mac(obj.get("dst")),
            bssid=_as_mac(obj.get("bssid")),
            ssid=ssid if isinstance(ssid, str) else None,
            extra=extra,
        )


def _as_int(v) -> Optional[int]:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _as_mac(v) -> Optional[str]:
    if isinstance(v, str) and v:
        return v.upper()
    return None
