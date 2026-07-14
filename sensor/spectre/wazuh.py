"""RFC 5424 syslog forwarder to Wazuh.

Only *threats* and periodic *summaries* are forwarded — never raw frames — so
the SIEM stays signal-rich (raw volume is ~50-60 msgs/sec, which would swamp an
all-in-one Wazuh box).

Message shape::

    <PRI>1 TIMESTAMP HOST spectre PROCID MSGID [spectre@32473 k="v" ...] {json}

* PRI   = facility(local7=23)*8 + severity, severity mapped from the threat.
* MSG   = a compact JSON object Wazuh decodes natively (json decoder).
* SD    = structured data with band / sensor / rule for quick filtering.

Transport is UDP by default (fire-and-forget); TCP is available for guaranteed
delivery across network segments. Both are configurable at runtime.

Author: gurvinny
Project: SPECTRE
"""
from __future__ import annotations

import json
import socket
import time
from datetime import datetime, timezone
from typing import Callable, Optional

from .models import Threat, SEVERITY

FACILITY_LOCAL7 = 23
ENTERPRISE_ID = "32473"   # IANA example PEN; fine for a self-hosted decoder
MSGID_THREAT = "THREAT"
MSGID_SUMMARY = "SUMMARY"


def _rfc3339(ts: float) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime(
        "%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _sd(pairs: dict) -> str:
    """Build one RFC 5424 STRUCTURED-DATA element (values are escaped)."""
    items = []
    for k, v in pairs.items():
        if v is None:
            continue
        s = str(v).replace("\\", "\\\\").replace('"', '\\"').replace("]", "\\]")
        items.append(f'{k}="{s}"')
    if not items:
        return "-"
    return f"[{ENTERPRISE_ID}@spectre " + " ".join(items) + "]"


class WazuhForwarder:
    """Runtime-configurable syslog client.

    All settings are read through ``cfg(key, default)`` on every send so the
    Settings page can change host/port/proto/enabled without a restart.
    """

    def __init__(self, cfg: Callable[[str, object], object], hostname: str = "spectre") -> None:
        self.cfg = cfg
        self.hostname = hostname
        self._tcp: Optional[socket.socket] = None
        self._tcp_target: tuple[str, int] | None = None
        self.sent = 0
        self.failures = 0
        self.last_error: Optional[str] = None

    # ── Public API ─────────────────────────────────────────────────────
    def send_threat(self, t: Threat) -> bool:
        severity_code = SEVERITY.get(t.severity, (9, 5))[1]
        sd = _sd({"band": t.band, "rule": t.rule, "bssid": t.bssid,
                  "ssid": t.ssid, "severity": t.severity})
        body = json.dumps({"kind": "threat", **t.to_public()},
                          separators=(",", ":"))
        return self._emit(severity_code, MSGID_THREAT, sd, body)

    def send_summary(self, summary: dict) -> bool:
        sd = _sd({"kind": "summary"})
        body = json.dumps({"kind": "summary", **summary}, separators=(",", ":"))
        return self._emit(6, MSGID_SUMMARY, sd, body)  # info

    # ── Internals ──────────────────────────────────────────────────────
    def _emit(self, severity: int, msgid: str, sd: str, body: str) -> bool:
        if not bool(self.cfg("wazuh_enabled", True)):
            return False
        host = str(self.cfg("wazuh_host", ""))
        if not host:
            return False
        port = int(self.cfg("wazuh_port", 514))
        proto = str(self.cfg("wazuh_proto", "udp")).lower()
        app = str(self.cfg("wazuh_app_name", "spectre"))

        pri = FACILITY_LOCAL7 * 8 + severity
        frame = (f"<{pri}>1 {_rfc3339(time.time())} {self.hostname} {app} "
                 f"- {msgid} {sd} {body}")
        data = frame.encode("utf-8", "replace")
        try:
            if proto == "tcp":
                self._send_tcp(host, port, data)
            else:
                self._send_udp(host, port, data)
            self.sent += 1
            self.last_error = None
            return True
        except OSError as exc:
            self.failures += 1
            self.last_error = str(exc)
            self._reset_tcp()
            return False

    def _send_udp(self, host: str, port: int, data: bytes) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.settimeout(2.0)
            s.sendto(data, (host, port))

    def _send_tcp(self, host: str, port: int, data: bytes) -> None:
        if self._tcp is None or self._tcp_target != (host, port):
            self._reset_tcp()
            self._tcp = socket.create_connection((host, port), timeout=3.0)
            self._tcp_target = (host, port)
        # Non-transparent framing (LF-delimited) — accepted by Wazuh remote syslog.
        self._tcp.sendall(data + b"\n")

    def _reset_tcp(self) -> None:
        if self._tcp is not None:
            try:
                self._tcp.close()
            except OSError:
                pass
        self._tcp = None
        self._tcp_target = None

    def status(self) -> dict:
        return {
            "enabled": bool(self.cfg("wazuh_enabled", True)),
            "host": self.cfg("wazuh_host", ""),
            "port": self.cfg("wazuh_port", 514),
            "proto": self.cfg("wazuh_proto", "udp"),
            "sent": self.sent,
            "failures": self.failures,
            "last_error": self.last_error,
        }
