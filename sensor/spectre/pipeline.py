"""The SPECTRE pipeline: ingest → inventory → detect → store → forward → stream.

One :class:`Pipeline` instance owns the live in-memory state (recent-frame ring,
device / AP inventory, rolling counters, WebSocket subscribers) and coordinates
the periodic background tasks (frame flush, inventory flush, summary tick,
retention prune). Reader tasks call :meth:`ingest` synchronously per frame — it
does no awaiting, so it stays fast under the ~60 frames/sec load.

Author: gurvinny
Project: SPECTRE
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from collections import deque
from typing import Optional

from .config import Config
from .detect import Engine, SlidingWindow
from .models import Event, Threat, now
from .store import Store
from .wazuh import WazuhForwarder

log = logging.getLogger("spectre.pipeline")

RECENT_RING = 2000        # frames kept in memory for the overview/heatmap
FEED_BATCH_CAP = 300      # max frames pushed to the live feed per broadcast tick
SUBSCRIBER_QUEUE_CAP = 50


def _is_random_mac(mac: Optional[str]) -> bool:
    if not mac:
        return False
    try:
        return bool(int(mac.split(":")[0], 16) & 0b10)
    except (ValueError, IndexError):
        return False


class Pipeline:
    def __init__(self, store: Store, config: Config) -> None:
        self.store = store
        self.cfg = config
        self.engine = Engine(config)
        self.wazuh = WazuhForwarder(config)
        self.started_at = now()

        # ── live in-memory state ──────────────────────────────────────
        self._recent: deque[Event] = deque(maxlen=RECENT_RING)
        self._frame_buffer: list[Event] = []          # pending DB writes
        self._devices: dict[str, dict] = {}
        self._aps: dict[str, dict] = {}
        self._dirty_devices: set[str] = set()
        self._dirty_aps: set[str] = set()
        self._known_bssids: set[str] = set()

        # counters / rates
        self.total_frames = 0
        self._fps_win = SlidingWindow(5.0)
        self._sensor_fps: dict[str, SlidingWindow] = {}
        self._sensor_last: dict[str, dict] = {}       # sensor_id -> {band,last_seen,frames}

        # threat rate-limiting
        self._threat_cooldown: dict[str, float] = {}

        # live feed
        self._feed_batch: list[dict] = []
        self._threat_batch: list[dict] = []
        self.subscribers: set[asyncio.Queue] = set()

        self._tasks: list[asyncio.Task] = []
        self.refresh_known_networks()
        self.refresh_muted_devices()

    # ── known networks (evil-twin allowlist) ──────────────────────────
    def refresh_known_networks(self) -> None:
        known = self.store.list_known_networks()
        self.engine.set_known_networks(known)
        self._known_bssids = {(k.get("bssid") or "").upper()
                              for k in known if k.get("bssid")}

    # ── muted devices (trusted clients — no anomaly alerts) ───────────
    def refresh_muted_devices(self) -> None:
        macs = self.cfg("muted_devices", []) or []
        self.engine.set_muted_devices([str(m) for m in macs])

    # ── ingest (hot path, synchronous) ────────────────────────────────
    def ingest(self, ev: Event) -> None:
        self.total_frames += 1
        self._recent.append(ev)
        self._frame_buffer.append(ev)
        self._fps_win.add(ev.received_at)
        self._update_sensor(ev)
        self._update_inventory(ev)

        # live feed (batched by the broadcaster)
        if len(self._feed_batch) < FEED_BATCH_CAP:
            self._feed_batch.append(ev.to_public())

        # detection
        for threat in self.engine.feed(ev):
            self._handle_threat(threat)

    def _update_sensor(self, ev: Event) -> None:
        s = self._sensor_last.setdefault(
            ev.sensor_id, {"band": ev.band, "last_seen": 0.0, "frames": 0})
        s["band"] = ev.band
        s["last_seen"] = ev.received_at
        s["frames"] += 1
        win = self._sensor_fps.get(ev.sensor_id)
        if win is None:
            win = self._sensor_fps[ev.sensor_id] = SlidingWindow(5.0)
        win.add(ev.received_at)

    def _update_inventory(self, ev: Event) -> None:
        # Access point (from AP-originated frames carrying a BSSID/SSID).
        if ev.bssid and ev.bssid == ev.src and ev.frame_type in (
                "BEACON", "PROBE_RESP"):
            ap = self._aps.get(ev.bssid)
            if ap is None:
                ap = self._aps[ev.bssid] = {
                    "bssid": ev.bssid, "ssid": ev.ssid, "band": ev.band,
                    "channels": set(), "first_seen": ev.received_at,
                    "last_seen": ev.received_at, "last_rssi": ev.rssi,
                    "beacons": 0, "is_known": 0}
            ap["last_seen"] = ev.received_at
            ap["last_rssi"] = ev.rssi if ev.rssi is not None else ap["last_rssi"]
            ap["band"] = ev.band
            if ev.ssid:
                ap["ssid"] = ev.ssid
            if ev.ch is not None:
                ap["channels"].add(ev.ch)
            if ev.frame_type == "BEACON":
                ap["beacons"] += 1
            ap["is_known"] = int(ev.bssid in self._known_bssids)
            self._dirty_aps.add(ev.bssid)

        # Client device (from src, excluding broadcast).
        mac = ev.src
        if mac and mac != "FF:FF:FF:FF:FF:FF":
            d = self._devices.get(mac)
            if d is None:
                d = self._devices[mac] = {
                    "mac": mac, "first_seen": ev.received_at,
                    "last_seen": ev.received_at, "bands": set(),
                    "last_rssi": ev.rssi, "min_rssi": ev.rssi,
                    "max_rssi": ev.rssi, "frames": 0,
                    "is_random": int(_is_random_mac(mac)), "last_ssid": ev.ssid}
            d["last_seen"] = ev.received_at
            d["frames"] += 1
            if ev.band:
                d["bands"].add(ev.band)
            if ev.rssi is not None:
                d["last_rssi"] = ev.rssi
                d["min_rssi"] = min(d["min_rssi"] or ev.rssi, ev.rssi)
                d["max_rssi"] = max(d["max_rssi"] or ev.rssi, ev.rssi)
            if ev.ssid:
                d["last_ssid"] = ev.ssid
            self._dirty_devices.add(mac)

    def _handle_threat(self, t: Threat) -> None:
        cooldown = float(self.cfg("threat_cooldown_seconds", 30))
        last = self._threat_cooldown.get(t.dedupe_key, 0.0)
        if t.ts - last < cooldown:
            return
        self._threat_cooldown[t.dedupe_key] = t.ts

        sent = self.wazuh.send_threat(t)
        self.store.insert_threat(t, wazuh_sent=sent)
        pub = t.to_public()
        pub["wazuh_sent"] = sent
        self._threat_batch.append(pub)
        log.warning("THREAT %s [%s] %s", t.severity.upper(), t.rule, t.title)

    # ── background tasks ──────────────────────────────────────────────
    def start(self) -> None:
        self._tasks = [
            asyncio.create_task(self._loop_flush_frames()),
            asyncio.create_task(self._loop_flush_inventory()),
            asyncio.create_task(self._loop_broadcast()),
            asyncio.create_task(self._loop_summary()),
            asyncio.create_task(self._loop_prune()),
        ]

    async def stop(self) -> None:
        for task in self._tasks:
            task.cancel()
        for task in self._tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        self._flush_frames()

    async def _loop_flush_frames(self) -> None:
        while True:
            await asyncio.sleep(1.0)
            self._flush_frames()

    def _flush_frames(self) -> None:
        if not self._frame_buffer:
            return
        batch, self._frame_buffer = self._frame_buffer, []
        try:
            self.store.insert_frames(batch)
        except Exception:  # noqa: BLE001 - never let a write kill the loop
            log.exception("frame flush failed")

    async def _loop_flush_inventory(self) -> None:
        while True:
            await asyncio.sleep(3.0)
            self._flush_inventory()

    def _flush_inventory(self) -> None:
        if self._dirty_devices:
            rows = [self._device_row(m) for m in list(self._dirty_devices)
                    if m in self._devices]
            self._dirty_devices.clear()
            self.store.upsert_devices(rows)
        if self._dirty_aps:
            rows = [self._ap_row(b) for b in list(self._dirty_aps)
                    if b in self._aps]
            self._dirty_aps.clear()
            self.store.upsert_aps(rows)

    def _device_row(self, mac: str) -> dict:
        d = self._devices[mac]
        return {**d, "bands": ",".join(sorted(d["bands"]))}

    def _ap_row(self, bssid: str) -> dict:
        a = self._aps[bssid]
        return {**a, "channels": ",".join(str(c) for c in sorted(a["channels"]))}

    async def _loop_broadcast(self) -> None:
        """Push batched frames + any threats to WS subscribers ~4x/sec."""
        while True:
            await asyncio.sleep(0.25)
            if not self.subscribers:
                self._feed_batch.clear()
                self._threat_batch.clear()
                continue
            frames, self._feed_batch = self._feed_batch, []
            threats, self._threat_batch = self._threat_batch, []
            if not frames and not threats:
                continue
            msg = {"type": "batch", "frames": frames, "threats": threats,
                   "fps": self.fps()}
            for q in list(self.subscribers):
                try:
                    q.put_nowait(msg)
                except asyncio.QueueFull:
                    # Slow consumer — drop the frame; it will catch up on the next tick.
                    pass

    async def _loop_summary(self) -> None:
        while True:
            interval = int(self.cfg("summary_interval_seconds", 60))
            await asyncio.sleep(max(5, interval))
            summary = self.build_summary()
            self.store.insert_summary(summary)
            self.wazuh.send_summary(summary)

    async def _loop_prune(self) -> None:
        while True:
            await asyncio.sleep(300)  # every 5 min
            try:
                report = self.store.prune(
                    float(self.cfg("raw_retention_hours", 48)),
                    float(self.cfg("disk_guard_percent", 85)))
                if report["deleted"] or report["guard_deleted"]:
                    log.info("prune %s", report)
                self._prune_inventory()
            except Exception:  # noqa: BLE001
                log.exception("prune failed")

    def _prune_inventory(self) -> None:
        """Age out stale devices/APs from the DB and the in-memory maps so the
        inventory (and RAM) don't grow without bound as transient MACs pass by."""
        dev_purge = float(self.cfg("device_retention_hours", 24)) * 3600
        ap_purge = float(self.cfg("ap_retention_hours", 168)) * 3600
        muted = {str(m).upper() for m in (self.cfg("muted_devices", []) or [])}
        report = self.store.prune_inventory(dev_purge, ap_purge, muted)
        # Mirror the purge in the live maps (exempt muted clients / known APs).
        cut = now()
        for mac in [m for m, d in self._devices.items()
                    if cut - d["last_seen"] > dev_purge and m.upper() not in muted]:
            self._devices.pop(mac, None)
        for bssid in [b for b, a in self._aps.items()
                      if cut - a["last_seen"] > ap_purge and not a.get("is_known")]:
            self._aps.pop(bssid, None)
        if report["devices_purged"] or report["aps_purged"]:
            log.info("inventory prune %s", report)

    # ── derived views for the API ─────────────────────────────────────
    def fps(self) -> float:
        return round(self._fps_win.count(now()) / 5.0, 1)

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=SUBSCRIBER_QUEUE_CAP)
        self.subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self.subscribers.discard(q)

    def build_summary(self) -> dict:
        t = now()
        bands: dict[str, int] = {}
        types: dict[str, int] = {}
        for ev in self._recent:
            bands[ev.band] = bands.get(ev.band, 0) + 1
            types[ev.frame_type] = types.get(ev.frame_type, 0) + 1
        return {
            "ts": t,
            "fps": self.fps(),
            "total_frames": self.total_frames,
            "devices": len(self._devices),
            "access_points": len(self._aps),
            "threats_last_hour": self.store.count_threats_since(t - 3600),
            "band_breakdown": bands,
            "top_frame_types": dict(sorted(types.items(),
                                           key=lambda kv: kv[1], reverse=True)[:8]),
        }

    def overview(self) -> dict:
        t = now()
        # channel histogram + band breakdown from the recent ring (cheap).
        channels: dict[str, int] = {}
        bands: dict[str, int] = {}
        types: dict[str, int] = {}
        talkers: dict[str, int] = {}
        for ev in self._recent:
            bands[ev.band] = bands.get(ev.band, 0) + 1
            types[ev.frame_type] = types.get(ev.frame_type, 0) + 1
            if ev.ch is not None:
                channels[str(ev.ch)] = channels.get(str(ev.ch), 0) + 1
            if ev.src:
                talkers[ev.src] = talkers.get(ev.src, 0) + 1

        sensors = []
        for sid, s in self._sensor_last.items():
            win = self._sensor_fps.get(sid)
            sensors.append({
                "sensor": sid,
                "band": s["band"],
                "frames": s["frames"],
                "fps": round(win.count(t) / 5.0, 1) if win else 0.0,
                "online": (t - s["last_seen"]) < 15,
                "last_seen": round(s["last_seen"], 1),
            })

        return {
            "armed": True,
            "uptime_seconds": round(t - self.started_at, 1),
            "fps": self.fps(),
            "total_frames": self.total_frames,
            "devices": len(self._devices),
            "access_points": len(self._aps),
            "known_aps": sum(1 for a in self._aps.values() if a["is_known"]),
            "threats_last_hour": self.store.count_threats_since(t - 3600),
            "sensors": sorted(sensors, key=lambda x: x["band"]),
            "band_breakdown": bands,
            "frame_types": dict(sorted(types.items(),
                                       key=lambda kv: kv[1], reverse=True)),
            "channels": channels,
            "top_talkers": [{"mac": m, "frames": c} for m, c in
                            sorted(talkers.items(), key=lambda kv: kv[1],
                                   reverse=True)[:10]],
            "wazuh": self.wazuh.status(),
        }
