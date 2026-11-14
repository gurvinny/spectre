"""Beacon-flood and probe-flood detection.

* **Beacon flood** — tools like mdk4/airbase spam beacons for many fabricated
  SSIDs/BSSIDs to clutter the airwaves or hide a real attack. Signature: an
  abnormal number of *distinct* BSSIDs beaconing within a short window, counted
  per band: each board hears its own neighbourhood, and two bands' ordinary
  APs must not add up to a flood.
* **Probe flood** — a burst of PROBE_REQ frames (often from a single tool
  cycling MACs) used for reconnaissance or as a DoS. Signature: probe-request
  rate above threshold, counted per band like the beacon flood. The alert
  names the loudest sources in the window, not whichever device happened to
  send the probe that crossed the threshold.

Author: gurvinny
Project: SPECTRE
"""
from __future__ import annotations

from collections import Counter, deque

from . import Rule
from ..models import Event, Threat


class FloodRule(Rule):
    name = "beacon_probe_flood"

    def __init__(self, cfg) -> None:
        super().__init__(cfg)
        # band -> (timestamp, bssid) ring for counting distinct beaconing BSSIDs.
        self._beacon_rings: dict[str | None, deque[tuple[float, str]]] = {}
        # band -> (timestamp, source MAC) ring for counting probe requests.
        self._probe_rings: dict[str | None, deque[tuple[float, str]]] = {}
        self._last_beacon_alert: dict[str | None, float] = {}  # per band
        self._last_probe_alert: dict[str | None, float] = {}   # per band

    def process(self, ev: Event) -> list[Threat]:
        window_s = float(self.cfg("flood_window_seconds", 5))
        cooldown = float(self.cfg("flood_cooldown_seconds", 30))
        out: list[Threat] = []

        if ev.frame_type == "BEACON" and ev.bssid:
            distinct = self._distinct_beacons(ev.received_at, ev.band, ev.bssid, window_s)
            threshold = int(self.cfg("beacon_flood_distinct_bssids", 40))
            last_alert = self._last_beacon_alert.get(ev.band, 0.0)
            if distinct >= threshold and ev.received_at - last_alert > cooldown:
                self._last_beacon_alert[ev.band] = ev.received_at
                out.append(Threat(
                    ts=ev.received_at, rule=self.name, severity="medium",
                    title=f"Beacon flood: {distinct} distinct APs in {window_s:.0f}s",
                    band=ev.band,
                    detail={"distinct_bssids": distinct, "window_seconds": window_s,
                            "threshold": threshold},
                ))

        elif ev.frame_type == "PROBE_REQ":
            ring = self._window(self._probe_rings, ev.received_at, ev.band,
                                ev.src or "", window_s)
            count = len(ring)
            threshold = int(self.cfg("probe_flood_threshold", 120))
            last_alert = self._last_probe_alert.get(ev.band, 0.0)
            if count >= threshold and ev.received_at - last_alert > cooldown:
                self._last_probe_alert[ev.band] = ev.received_at
                sources = Counter(m for _, m in ring)
                top = [[m, n] for m, n in sources.most_common(3)]
                out.append(Threat(
                    ts=ev.received_at, rule=self.name, severity="medium",
                    title=f"Probe-request flood ({count} in {window_s:.0f}s)",
                    band=ev.band, src=top[0][0] or None,
                    detail={"probe_reqs": count, "window_seconds": window_s,
                            "threshold": threshold,
                            "distinct_sources": len(sources), "top_sources": top},
                ))

        return out

    def _distinct_beacons(self, now: float, band: str | None, bssid: str,
                          window_s: float) -> int:
        ring = self._window(self._beacon_rings, now, band, bssid, window_s)
        return len({b for _, b in ring})

    @staticmethod
    def _window(rings: dict, now: float, band: str | None, mac: str,
                window_s: float) -> deque[tuple[float, str]]:
        """Add (*now*, *mac*) to *band*'s ring and drop entries older than the window."""
        ring = rings.setdefault(band, deque())
        ring.append((now, mac))
        cutoff = now - window_s
        while ring and ring[0][0] < cutoff:
            ring.popleft()
        return ring
