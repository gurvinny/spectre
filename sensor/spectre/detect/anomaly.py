"""New-device and signal-anomaly detection.

* **New device** — first time a client MAC is observed. Low-severity awareness
  signal (useful in a known environment; noisy in a busy one, so it is rate-
  limited and can be muted from Settings).
* **RSSI jump** — a device whose signal strength changes sharply in a short
  time can indicate spoofing or a device physically approaching (proximity).
* **Randomized-MAC probing** — modern devices probe with locally-administered
  (randomized) MACs; a high volume of these can indicate a recon tool.

Author: gurvinny
Project: SPECTRE
"""
from __future__ import annotations

from . import Rule
from ..models import Event, Threat, BROADCAST_MAC


def _is_random_mac(mac: str) -> bool:
    """True if the locally-administered bit is set in the first octet.

    The second hex nibble of the first octet being 2/6/A/E means the U/L bit is
    set — i.e. a randomized/locally-administered address.
    """
    try:
        first_octet = int(mac.split(":")[0], 16)
        return bool(first_octet & 0b10)
    except (ValueError, IndexError):
        return False


class AnomalyRule(Rule):
    name = "anomaly"

    def __init__(self, cfg) -> None:
        super().__init__(cfg)
        self._seen: set[str] = set()             # client MACs ever seen
        self._last_rssi: dict[str, int] = {}     # mac -> last rssi
        self._last_jump_alert: dict[str, float] = {}  # mac -> last rssi-jump alert ts
        self._muted: set[str] = set()            # operator-trusted MACs (no alerts)
        self._start_ts: float | None = None      # first-event time, for warm-up

    def set_muted_devices(self, macs: list[str]) -> None:
        """Trusted client MACs whose anomaly alerts are silenced."""
        self._muted = {m.upper() for m in macs if m}

    def process(self, ev: Event) -> list[Threat]:
        mac = ev.src
        if not mac or mac == BROADCAST_MAC:
            return []

        if self._start_ts is None:
            self._start_ts = ev.received_at
        # During warm-up we learn the existing population silently so a busy
        # startup doesn't fire "new device" for every station already on the air.
        warming = (ev.received_at - self._start_ts) < float(
            self.cfg("new_device_warmup_seconds", 60))

        muted = mac in self._muted
        out: list[Threat] = []

        # ── New device ─────────────────────────────────────────────────
        if mac not in self._seen:
            self._seen.add(mac)
            random = _is_random_mac(mac)
            # Only surface non-AP client activity as "new device" (APs are
            # tracked in the AP inventory). Randomized MACs are ephemeral and
            # constant in the wild; muted/warm-up devices are silent too.
            alert = (not muted and not warming
                     and bool(self.cfg("new_device_alerts", False))
                     and mac != ev.bssid
                     and (not random or bool(self.cfg("alert_randomized_devices", False))))
            if alert:
                out.append(Threat(
                    ts=ev.received_at, rule=self.name,
                    severity="low" if not random else "info",
                    title=f"New device {mac}" + (" (randomized MAC)" if random else ""),
                    band=ev.band, src=mac,
                    detail={"rssi": ev.rssi, "frame_type": ev.frame_type,
                            "randomized_mac": random},
                ))

        # ── RSSI jump ──────────────────────────────────────────────────
        if ev.rssi is not None:
            prev = self._last_rssi.get(mac)
            self._last_rssi[mac] = ev.rssi
            jump = int(self.cfg("rssi_jump_db", 55))
            cooldown = float(self.cfg("rssi_jump_cooldown_seconds", 60))
            last_alert = self._last_jump_alert.get(mac, 0.0)
            if (not muted and prev is not None and abs(ev.rssi - prev) >= jump
                    and ev.received_at - last_alert >= cooldown):
                self._last_jump_alert[mac] = ev.received_at
                out.append(Threat(
                    ts=ev.received_at, rule=self.name, severity="low",
                    title=f"RSSI jump on {mac}: {prev} → {ev.rssi} dBm",
                    band=ev.band, src=mac,
                    detail={"previous_rssi": prev, "current_rssi": ev.rssi,
                            "delta": ev.rssi - prev},
                ))

        return out
