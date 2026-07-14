"""Beacon-flood and probe-flood detection.

* **Beacon flood** — tools like mdk4/airbase spam beacons for many fabricated
  SSIDs/BSSIDs to clutter the airwaves or hide a real attack. Signature: an
  abnormal number of *distinct* BSSIDs beaconing within a short window.
* **Probe flood** — a burst of PROBE_REQ frames (often from a single tool
  cycling MACs) used for reconnaissance or as a DoS. Signature: probe-request
  rate above threshold.

Author: gurvinny
Project: SPECTRE
"""
from __future__ import annotations

from collections import deque

from . import Rule, SlidingWindow
from ..models import Event, Threat


class FloodRule(Rule):
    name = "beacon_probe_flood"

    def __init__(self, cfg) -> None:
        super().__init__(cfg)
        # (timestamp, bssid) ring for counting distinct beaconing BSSIDs.
        self._beacon_ring: deque[tuple[float, str]] = deque()
        self._probe_win = SlidingWindow(float(cfg("flood_window_seconds", 5)))
        self._last_beacon_alert = 0.0
        self._last_probe_alert = 0.0

    def process(self, ev: Event) -> list[Threat]:
        window_s = float(self.cfg("flood_window_seconds", 5))
        cooldown = float(self.cfg("flood_cooldown_seconds", 30))
        out: list[Threat] = []

        if ev.frame_type == "BEACON" and ev.bssid:
            distinct = self._distinct_beacons(ev.received_at, ev.bssid, window_s)
            threshold = int(self.cfg("beacon_flood_distinct_bssids", 40))
            if distinct >= threshold and ev.received_at - self._last_beacon_alert > cooldown:
                self._last_beacon_alert = ev.received_at
                out.append(Threat(
                    ts=ev.received_at, rule=self.name, severity="medium",
                    title=f"Beacon flood: {distinct} distinct APs in {window_s:.0f}s",
                    band=ev.band,
                    detail={"distinct_bssids": distinct, "window_seconds": window_s,
                            "threshold": threshold},
                ))

        elif ev.frame_type == "PROBE_REQ":
            if self._probe_win.window != window_s:
                self._probe_win = SlidingWindow(window_s)
            count = self._probe_win.add(ev.received_at)
            threshold = int(self.cfg("probe_flood_threshold", 120))
            if count >= threshold and ev.received_at - self._last_probe_alert > cooldown:
                self._last_probe_alert = ev.received_at
                out.append(Threat(
                    ts=ev.received_at, rule=self.name, severity="medium",
                    title=f"Probe-request flood ({count} in {window_s:.0f}s)",
                    band=ev.band, src=ev.src,
                    detail={"probe_reqs": count, "window_seconds": window_s,
                            "threshold": threshold},
                ))

        return out

    def _distinct_beacons(self, now: float, bssid: str, window_s: float) -> int:
        self._beacon_ring.append((now, bssid))
        cutoff = now - window_s
        while self._beacon_ring and self._beacon_ring[0][0] < cutoff:
            self._beacon_ring.popleft()
        return len({b for _, b in self._beacon_ring})
