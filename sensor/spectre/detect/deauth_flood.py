"""Deauthentication / disassociation flood detection.

DEAUTH and DISASSOC are management frames a legitimate AP only sends
occasionally. A burst targeting a BSSID (or spoofed from one) is the classic
signature of a WiFi denial-of-service or a handshake-capture attack (forcing a
client to reconnect so the 4-way handshake can be sniffed).

Heuristic: count DEAUTH+DISASSOC frames per BSSID over a sliding window; alert
when the rate crosses the configured threshold.

Author: gurvinny
Project: SPECTRE
"""
from __future__ import annotations

from . import Rule, SlidingWindow
from ..models import Event, Threat


class DeauthFlood(Rule):
    name = "deauth_flood"

    def __init__(self, cfg) -> None:
        super().__init__(cfg)
        self._windows: dict[str, SlidingWindow] = {}

    def process(self, ev: Event) -> list[Threat]:
        if ev.frame_type not in ("DEAUTH", "DISASSOC"):
            return []

        window_s = float(self.cfg("deauth_window_seconds", 10))
        threshold = int(self.cfg("deauth_threshold", 20))

        key = ev.bssid or ev.src or "unknown"
        win = self._windows.get(key)
        if win is None or win.window != window_s:
            win = self._windows[key] = SlidingWindow(window_s)

        count = win.add(ev.received_at)
        if count < threshold:
            return []

        rate = round(count / window_s, 1)
        return [Threat(
            ts=ev.received_at,
            rule=self.name,
            severity="high",
            title=f"Deauth flood on {key} ({rate}/s)",
            band=ev.band,
            bssid=ev.bssid,
            ssid=ev.ssid,
            src=ev.src,
            detail={
                "frames_in_window": count,
                "window_seconds": window_s,
                "rate_per_sec": rate,
                "threshold": threshold,
                "target_dst": ev.dst,
            },
        )]
