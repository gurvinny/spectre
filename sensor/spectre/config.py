"""Runtime configuration: defaults, first-run seeding, and a live accessor.

Config lives in the SQLite ``config`` table so the Settings page can change it
without a restart. :class:`Config` provides a ``cfg(key, default)`` callable that
detection rules and the Wazuh forwarder read on every use, falling back to
:data:`DEFAULTS` and finally the caller's default.

Author: gurvinny
Project: SPECTRE
"""
from __future__ import annotations

import os
from typing import Any

from .store import Store

# Detection thresholds + operational knobs. Every one is Settings-editable.
DEFAULTS: dict[str, Any] = {
    # deauth flood
    "deauth_window_seconds": 10,
    "deauth_threshold": 20,
    # evil twin
    "evil_twin_learn": False,
    # floods
    "flood_window_seconds": 5,
    "flood_cooldown_seconds": 30,
    "beacon_flood_distinct_bssids": 40,
    "probe_flood_threshold": 120,
    # anomalies (tuned "quiet" — real airspace is noisy)
    "new_device_alerts": False,          # off by default; enable per-environment
    "alert_randomized_devices": False,   # mute the constant randomized-MAC noise
    "new_device_warmup_seconds": 60,     # learn existing devices silently at startup
    "rssi_jump_db": 55,                  # only flag large, unlikely-multipath jumps
    "rssi_jump_cooldown_seconds": 60,    # per-MAC, so one device can't spam
    "muted_devices": [],                 # MACs whose anomaly alerts are silenced
    # retention
    "raw_retention_hours": 48,
    "disk_guard_percent": 85,
    # inventory lifecycle — devices are ephemeral (passing cars/phones), APs are
    # infrastructure. "active" = shown in the live Inventory; older-but-not-purged
    # is archived (still searchable); past the purge window it's deleted. Trusted
    # APs and muted devices never expire.
    "device_active_seconds": 600,        # 10 min in the active list
    "device_retention_hours": 24,        # purge stale clients after a day
    "ap_active_seconds": 1800,           # 30 min in the active list
    "ap_retention_hours": 168,           # keep APs a week before purging
    # wazuh
    "wazuh_enabled": True,
    "wazuh_host": "10.0.0.20",
    "wazuh_port": 514,
    "wazuh_proto": "udp",
    "wazuh_app_name": "spectre",
    "summary_interval_seconds": 60,
    # threat rate-limit (seconds a given dedupe_key stays muted)
    "threat_cooldown_seconds": 30,
}

# Config keys whose initial value should come from the environment on first run.
_ENV_SEED = {
    "wazuh_enabled": ("WAZUH_ENABLED", lambda v: v.lower() == "true"),
    "wazuh_host": ("WAZUH_HOST", str),
    "wazuh_port": ("WAZUH_PORT", int),
    "wazuh_proto": ("WAZUH_PROTO", str),
    "wazuh_app_name": ("WAZUH_APP_NAME", str),
    "raw_retention_hours": ("RAW_RETENTION_HOURS", float),
    "disk_guard_percent": ("DISK_GUARD_PERCENT", float),
    "summary_interval_seconds": ("SUMMARY_INTERVAL_SECONDS", int),
}


class Config:
    """Live, SQLite-backed config with a ``DEFAULTS`` fallback chain."""

    def __init__(self, store: Store) -> None:
        self.store = store
        self._seed()

    def _seed(self) -> None:
        existing = self.store.all_config()
        for key, default in DEFAULTS.items():
            if key in existing:
                continue
            value = default
            if key in _ENV_SEED:
                env_key, caster = _ENV_SEED[key]
                raw = os.environ.get(env_key)
                if raw is not None and raw != "":
                    try:
                        value = caster(raw)
                    except (ValueError, TypeError):
                        value = default
            self.store.set_config(key, value)

    def __call__(self, key: str, default: Any = None) -> Any:
        return self.store.get_config(key, DEFAULTS.get(key, default))

    def get(self, key: str, default: Any = None) -> Any:
        return self(key, default)

    def set(self, key: str, value: Any) -> None:
        self.store.set_config(key, value)

    def snapshot(self) -> dict:
        merged = dict(DEFAULTS)
        merged.update(self.store.all_config())
        return merged
