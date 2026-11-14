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
* An optional ``on_lifecycle`` callback receives one record per lifecycle line
  (``received_at``, ``sensor_id``, latched ``band``, ``kind``, ``payload``), so
  reboots, sweep counters, telemetry, clock syncs and command acks are stored.
* ``ap_info`` lines (v2 firmware: one AP's advertised security and
  capabilities) go to ``on_ap_info`` when given, else to ``on_lifecycle``.
* A successful ``cmd_ack`` reports the board's resulting config; a band switch
  takes effect without a reboot, so its ``config.band`` is latched too.
* v2 frame keys become typed :class:`Event` fields (``docs/data-contract.md``);
  a value of the wrong JSON type becomes ``None`` rather than a bad column.

Author: gurvinny
Project: SPECTRE
"""
from __future__ import annotations

import json
import re
from typing import Callable, Optional

from .models import Event, now

# Strip an optional leading "<PRI>" and an optional "word word:" tag, then we
# hunt for the JSON body starting at the first "{".
_PRI_RE = re.compile(r"^<\d{1,3}>")

# Frame keys of the original firmware, handled explicitly below.
_V1_KEYS = {"seq", "uptime_ms", "ch", "rssi", "type", "src", "dst", "bssid", "ssid"}
# v2 frame keys -> Event field, for integer and string values.
_V2_INTS = {"sub": "sub", "nf": "nf", "mcs": "mcs", "bw": "bw", "rate": "rate",
            "ts": "ts_us", "sn": "sn", "fl": "fc_flags", "dur": "dur",
            "reason": "reason", "aalg": "auth_alg", "aseq": "auth_seq",
            "st": "status", "eapol": "eapol"}
_V2_STRS = {"phy": "phy", "fp": "probe_fp"}
_KNOWN_KEYS = _V1_KEYS | set(_V2_INTS) | set(_V2_STRS) | {"ouis"}


def _extract_json(line: str) -> Optional[dict]:
    """Return the JSON object embedded in *line*, or None if there isn't one.

    The object runs to the last ``}``. Its start is the first ``{`` that parses:
    a board reset part-way through a line leaves that partial line, then boot-ROM
    output read at the wrong baud, in front of the next record on the same line.
    """
    end = line.rfind("}")
    start = line.find("{")
    while start != -1 and start < end:
        try:
            obj = json.loads(line[start:end + 1])
            return obj if isinstance(obj, dict) else None
        except (ValueError, json.JSONDecodeError):
            start = line.find("{", start + 1)
    return None


class Parser:
    """Stateful per-board parser. One instance per serial port.

    Holds the latched band for this board and a running malformed-line counter
    for observability.
    """

    def __init__(self, sensor_id: str, default_band: str = "unknown",
                 on_lifecycle: Optional[Callable[[dict], None]] = None,
                 on_ap_info: Optional[Callable[[dict], None]] = None,
                 on_malformed: Optional[Callable[[str], None]] = None) -> None:
        self.sensor_id = sensor_id
        self.band = default_band
        self.malformed = 0
        self.last_event_kind: Optional[str] = None
        self.on_lifecycle = on_lifecycle
        self.on_malformed = on_malformed
        self.on_ap_info = on_ap_info

    def _report_malformed(self, raw: str) -> None:
        if self.on_malformed is not None:
            self.on_malformed(raw)

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
                self._report_malformed(raw)
            return None

        # ── Lifecycle events (no "type", carry "event") ────────────────
        if "event" in obj and "type" not in obj:
            kind = str(obj.get("event"))
            self.last_event_kind = kind
            if kind == "boot":
                self._latch_band(obj.get("band"))
            elif kind == "cmd_ack" and obj.get("ok") is True:
                config = obj.get("config")
                if isinstance(config, dict):
                    self._latch_band(config.get("band"))
            sink = self.on_lifecycle
            if kind == "ap_info" and self.on_ap_info is not None:
                sink = self.on_ap_info
            if sink is not None:
                sink({
                    "received_at": now(), "sensor_id": self.sensor_id,
                    "band": self.band, "kind": kind,
                    "payload": {k: v for k, v in obj.items() if k != "event"},
                })
            return None

        # ── Frame events ───────────────────────────────────────────────
        frame_type = obj.get("type")
        if not isinstance(frame_type, str):
            self.malformed += 1
            self._report_malformed(raw)
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
        extra = {k: v for k, v in obj.items() if k not in _KNOWN_KEYS}
        v2: dict = {field: _as_int(obj.get(key)) for key, field in _V2_INTS.items()}
        for key, field in _V2_STRS.items():
            v = obj.get(key)
            v2[field] = v if isinstance(v, str) and v else None
        ouis = obj.get("ouis")
        v2["ouis"] = (",".join(o for o in ouis if isinstance(o, str) and o) or None
                      if isinstance(ouis, list) else None)

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
            **v2,
        )

    def _latch_band(self, band) -> None:
        if isinstance(band, str) and band:
            self.band = band


def _as_int(v) -> Optional[int]:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _as_mac(v) -> Optional[str]:
    if isinstance(v, str) and v:
        return v.upper()
    return None
