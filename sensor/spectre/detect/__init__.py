"""Server-side WiFi threat detection engine.

Each rule consumes the normalized :class:`~spectre.models.Event` stream and may
emit :class:`~spectre.models.Threat` objects. Rules are intentionally small and
independent so they can be reasoned about and tuned in isolation; thresholds are
read live from config via the ``cfg(key, default)`` accessor so the Settings
page can retune them without a restart.

Author: gurvinny
Project: SPECTRE
"""
from __future__ import annotations

from collections import deque
from typing import Callable

from ..models import Event, Threat


class SlidingWindow:
    """Timestamp ring for rate calculations over a fixed time window."""

    def __init__(self, window_seconds: float) -> None:
        self.window = window_seconds
        self._ts: deque[float] = deque()

    def add(self, ts: float) -> int:
        """Record an event at *ts* and return the current count in-window."""
        self._ts.append(ts)
        self._evict(ts)
        return len(self._ts)

    def count(self, now: float) -> int:
        self._evict(now)
        return len(self._ts)

    def _evict(self, now: float) -> None:
        cutoff = now - self.window
        while self._ts and self._ts[0] < cutoff:
            self._ts.popleft()


class Rule:
    """Base detection rule. Subclasses implement :meth:`process`."""

    name = "base"

    def __init__(self, cfg: Callable[[str, object], object]) -> None:
        self.cfg = cfg

    def process(self, ev: Event) -> list[Threat]:  # pragma: no cover - abstract
        return []

    def set_known_networks(self, known: list[dict]) -> None:
        """Override in rules that depend on the evil-twin allowlist."""

    def set_muted_devices(self, macs: list[str]) -> None:
        """Override in rules that honour the trusted/muted device list."""


class Engine:
    """Runs every rule against each event and collects the threats."""

    def __init__(self, cfg: Callable[[str, object], object]) -> None:
        # Imported here to avoid a circular import at module load.
        from .deauth_flood import DeauthFlood
        from .evil_twin import EvilTwin
        from .flood import FloodRule
        from .anomaly import AnomalyRule

        self.rules: list[Rule] = [
            DeauthFlood(cfg),
            EvilTwin(cfg),
            FloodRule(cfg),
            AnomalyRule(cfg),
        ]

    def feed(self, ev: Event) -> list[Threat]:
        threats: list[Threat] = []
        for rule in self.rules:
            threats.extend(rule.process(ev))
        return threats

    def set_known_networks(self, known: list[dict]) -> None:
        for rule in self.rules:
            rule.set_known_networks(known)

    def set_muted_devices(self, macs: list[str]) -> None:
        for rule in self.rules:
            rule.set_muted_devices(macs)
