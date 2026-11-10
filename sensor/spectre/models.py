"""Canonical data structures shared across the SPECTRE pipeline.

These are plain dataclasses (not pydantic) so the ingest/detection core stays
importable with only the Python standard library — the FastAPI layer converts
them to/from JSON at the edges.

Author: gurvinny
Project: SPECTRE
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict
from typing import Any, Optional

# ── Frame types the firmware emits (extend freely; parser is tolerant) ──
MGMT_TYPES = {"BEACON", "PROBE_REQ", "PROBE_RESP", "ASSOC_REQ", "ASSOC_RESP",
              "AUTH", "DEAUTH", "DISASSOC", "REASSOC_REQ", "REASSOC_RESP"}
BROADCAST_MAC = "FF:FF:FF:FF:FF:FF"


# frames table columns, in Event.to_row() order. The first 12 are the original
# schema; the rest were added for the v2 firmware (store migrates old DBs).
FRAME_COLUMNS = ("received_at", "sensor_id", "band", "frame_type", "ch", "rssi",
                 "seq", "uptime_ms", "src", "dst", "bssid", "ssid",
                 "sub", "nf", "phy", "mcs", "bw", "rate", "ts_us", "sn",
                 "fc_flags", "dur", "reason", "auth_alg", "auth_seq", "status",
                 "eapol", "probe_fp", "ouis")


@dataclass(slots=True)
class Event:
    """A single normalized frame observation from one sensor board.

    ``uptime_ms`` and ``seq`` come from the board (both reset on reboot), so we
    stamp ``received_at`` (wall-clock epoch seconds) at ingest for ordering.
    """
    received_at: float
    sensor_id: str
    band: str                      # "2.4GHz" | "5GHz" | "unknown"
    frame_type: str                # BEACON, DEAUTH, ...
    ch: Optional[int] = None
    rssi: Optional[int] = None
    seq: Optional[int] = None
    uptime_ms: Optional[int] = None
    src: Optional[str] = None
    dst: Optional[str] = None
    bssid: Optional[str] = None
    ssid: Optional[str] = None     # None when the firmware reports "?"
    # ── v2 firmware fields; all None on lines from the original firmware ──
    sub: Optional[int] = None      # exact 802.11 subtype
    nf: Optional[int] = None       # noise floor, dBm
    phy: Optional[str] = None      # "b", "g", "a", "n", "ac", "ax", ...
    mcs: Optional[int] = None
    bw: Optional[int] = None       # MHz
    rate: Optional[int] = None     # legacy rate code (11b/a/g)
    ts_us: Optional[int] = None    # radio rx timestamp, 32-bit, wraps ~71 min
    sn: Optional[int] = None       # 802.11 sequence number
    fc_flags: Optional[int] = None  # frame-control flag byte (retry, protected, ...)
    dur: Optional[int] = None      # Duration/ID
    reason: Optional[int] = None   # deauth/disassoc reason (unprotected frames)
    auth_alg: Optional[int] = None
    auth_seq: Optional[int] = None
    status: Optional[int] = None   # auth status code
    eapol: Optional[int] = None    # 1-4 handshake message, 5 group key, 6 other
    probe_fp: Optional[str] = None  # probe-request element fingerprint
    ouis: Optional[str] = None     # vendor OUIs, comma list
    extra: dict[str, Any] = field(default_factory=dict)

    def to_row(self) -> tuple:
        """Column tuple matching store.frames insert order (see FRAME_COLUMNS)."""
        return (self.received_at, self.sensor_id, self.band, self.frame_type,
                self.ch, self.rssi, self.seq, self.uptime_ms,
                self.src, self.dst, self.bssid, self.ssid,
                self.sub, self.nf, self.phy, self.mcs, self.bw, self.rate,
                self.ts_us, self.sn, self.fc_flags, self.dur, self.reason,
                self.auth_alg, self.auth_seq, self.status, self.eapol,
                self.probe_fp, self.ouis)

    def to_public(self) -> dict:
        """Compact dict for the live WebSocket feed / API."""
        return {
            "ts": round(self.received_at, 3),
            "sensor": self.sensor_id,
            "band": self.band,
            "type": self.frame_type,
            "ch": self.ch,
            "rssi": self.rssi,
            "src": self.src,
            "dst": self.dst,
            "bssid": self.bssid,
            "ssid": self.ssid,
        }


# ── Threat severities, mapped later to RFC 5424 syslog severities ──────
# name -> (numeric rank for UI sorting, syslog severity code)
# Codes must rise with rank: a SIEM sorting by syslog severity has to see
# critical above high. (high was once 1 "alert", which outranked critical.)
SEVERITY = {
    "critical": (1, 2),   # syslog crit
    "high":     (2, 3),   # syslog err
    "medium":   (3, 4),   # syslog warning
    "low":      (4, 5),   # syslog notice
    "info":     (5, 6),   # syslog info
}


@dataclass(slots=True)
class Threat:
    """A detection produced by a rule in the detection engine."""
    ts: float
    rule: str                      # e.g. "deauth_flood"
    severity: str                  # key into SEVERITY
    title: str
    band: str = "unknown"
    bssid: Optional[str] = None
    ssid: Optional[str] = None
    src: Optional[str] = None
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def dedupe_key(self) -> str:
        """Rate-limit key so one ongoing attack isn't re-emitted every frame."""
        return f"{self.rule}:{self.bssid or self.src or ''}:{self.band}"

    def to_public(self) -> dict:
        return {
            "ts": round(self.ts, 3),
            "rule": self.rule,
            "severity": self.severity,
            "rank": SEVERITY.get(self.severity, (9, 7))[0],
            "title": self.title,
            "band": self.band,
            "bssid": self.bssid,
            "ssid": self.ssid,
            "src": self.src,
            "detail": self.detail,
        }


def now() -> float:
    """Wall-clock epoch seconds — single source of truth for timestamps."""
    return time.time()
