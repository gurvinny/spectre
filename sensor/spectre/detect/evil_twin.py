"""Rogue AP / Evil-Twin detection.

An evil twin advertises a trusted SSID from an attacker-controlled radio to lure
clients into associating. We detect it against a user-managed allowlist of known
networks (Settings → Known Networks):

* A beacon/probe-response advertises a **known SSID** from a **BSSID that is not
  on the allowlist** for that SSID  →  evil twin.
* A known SSID/BSSID appears on an **unexpected band**  →  suspicious (a 2.4GHz
  home AP suddenly beaconing on 5GHz from a new radio, etc.).

If the allowlist is empty the rule can optionally *learn* the first BSSID seen
per SSID as the baseline (``evil_twin_learn`` config) — off by default to avoid
false positives until the operator has vetted their networks.

Author: gurvinny
Project: SPECTRE
"""
from __future__ import annotations

from . import Rule
from ..models import Event, Threat


class EvilTwin(Rule):
    name = "evil_twin"

    def __init__(self, cfg) -> None:
        super().__init__(cfg)
        # ssid -> set of allowed BSSIDs (from the allowlist)
        self._allow: dict[str, set[str]] = {}
        # ssid -> expected band (from the allowlist, if pinned)
        self._band: dict[str, str] = {}
        # ssid -> first-seen BSSID (learn mode baseline)
        self._learned: dict[str, str] = {}
        # avoid re-alerting for the same rogue bssid repeatedly
        self._flagged: set[str] = set()

    def set_known_networks(self, known: list[dict]) -> None:
        allow: dict[str, set[str]] = {}
        band: dict[str, str] = {}
        for row in known:
            ssid = row.get("ssid")
            if not ssid:
                continue
            bssid = (row.get("bssid") or "").upper()
            if bssid:
                allow.setdefault(ssid, set()).add(bssid)
            if row.get("band"):
                band[ssid] = row["band"]
        self._allow, self._band = allow, band
        self._flagged.clear()

    def process(self, ev: Event) -> list[Threat]:
        # Only AP-originated frames carry a trustworthy SSID<->BSSID binding.
        if ev.frame_type not in ("BEACON", "PROBE_RESP"):
            return []
        if not ev.ssid or not ev.bssid:
            return []

        ssid, bssid = ev.ssid, ev.bssid
        allowed = self._allow.get(ssid)

        # Learn-mode baseline when there is no allowlist entry for this SSID.
        if allowed is None:
            if bool(self.cfg("evil_twin_learn", False)):
                first = self._learned.setdefault(ssid, bssid)
                if bssid == first:
                    return []
                allowed = {first}
            else:
                return []

        threats: list[Threat] = []

        if bssid not in allowed and bssid not in self._flagged:
            self._flagged.add(bssid)
            threats.append(Threat(
                ts=ev.received_at, rule=self.name, severity="critical",
                title=f"Evil twin: '{ssid}' from unexpected BSSID {bssid}",
                band=ev.band, bssid=bssid, ssid=ssid,
                detail={"known_bssids": sorted(allowed), "rogue_bssid": bssid,
                        "rssi": ev.rssi, "channel": ev.ch},
            ))

        expected_band = self._band.get(ssid)
        if expected_band and ev.band != "unknown" and ev.band != expected_band \
                and (bssid + "|band") not in self._flagged:
            self._flagged.add(bssid + "|band")
            threats.append(Threat(
                ts=ev.received_at, rule=self.name, severity="high",
                title=f"'{ssid}' seen on unexpected band {ev.band}",
                band=ev.band, bssid=bssid, ssid=ssid,
                detail={"expected_band": expected_band, "seen_band": ev.band},
            ))

        return threats
