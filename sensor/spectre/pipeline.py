"""The SPECTRE pipeline: ingest → inventory → detect → store → forward → stream.

One :class:`Pipeline` instance owns the live in-memory state (recent-frame ring,
device / AP inventory, rolling counters, WebSocket subscribers) and coordinates
the periodic background tasks (frame flush, inventory flush, summary tick,
retention prune). Reader tasks call :meth:`ingest` synchronously per frame — it
does no awaiting, so it stays fast under load.

The event loop never takes the store's write lock: everything ingest produces
(frames, board lifecycle lines, ap_info, threats) is buffered and written in one
transaction from a worker thread, as are the inventory, summary and prune writes.
The serial readers share this loop, so a write waiting for the lock must never
stall it.

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
        self._board_buffer: list[dict] = []
        self._ap_info_buffer: list[dict] = []
        self._threat_buffer: list[tuple[Threat, bool]] = []
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
        self.ws_dropped = 0                           # batches discarded for slow clients

        self._tasks: list[asyncio.Task] = []
        self._in_flight: set[asyncio.Future] = set()  # worker-thread writes not yet done
        # background cadence, seconds
        self.flush_seconds = 1.0
        self.inventory_seconds = 3.0
        self.prune_seconds = 300.0
        self.refresh_known_networks()
        self.refresh_muted_devices()
        self.restore_ap_info()

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

    # ── AP parameters across a restart ────────────────────────────────
    def restore_ap_info(self) -> None:
        """Seed detection with each AP's newest stored ap_info. A board sends it on
        first sighting after its own boot, then periodically, so a sensor-only
        restart would otherwise forget what an AP advertises until the next one."""
        for row in self.store.latest_ap_info():
            self.engine.set_ap_info(row)

    # ── board lifecycle (boot, sweep counters) ─────────────────────────
    def record_board_event(self, rec: dict) -> None:
        self._board_buffer.append(rec)

    def record_ap_info(self, rec: dict) -> None:
        self._ap_info_buffer.append(rec)
        # Detection sees ap_info now, in order with the frames; only the write waits.
        self.engine.set_ap_info(rec)

    def pending_cmd_ack(self, sensor_id: str, cmd_id: str, since: float) -> Optional[dict]:
        """A ``cmd_ack`` received but not yet written, shaped like
        :meth:`Store.find_cmd_ack`. Safe from another thread: it reads a copy."""
        for rec in reversed(list(self._board_buffer)):
            p = rec.get("payload") or {}
            if (rec.get("kind") == "cmd_ack" and rec.get("sensor_id") == sensor_id
                    and p.get("id") == cmd_id and rec.get("received_at", 0.0) >= since):
                return dict(p, received_at=rec.get("received_at"))
        return None

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
        self._threat_buffer.append((t, sent))
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
        # A cancelled task stops waiting, but its write keeps running in the
        # worker thread. Let it finish first, so nothing is lost or reordered
        # and the store is not closed underneath it.
        if self._in_flight:
            await asyncio.gather(*self._in_flight, return_exceptions=True)
        self.flush()

    # ── ingest writes (buffered on the loop, written off it) ──────────
    def _take_pending(self) -> Optional[tuple]:
        """Swap out everything waiting to be written. Runs on the loop."""
        if not (self._frame_buffer or self._board_buffer or self._ap_info_buffer
                or self._threat_buffer):
            return None
        pending = (self._frame_buffer, self._board_buffer, self._ap_info_buffer,
                   self._threat_buffer)
        self._frame_buffer, self._board_buffer = [], []
        self._ap_info_buffer, self._threat_buffer = [], []
        return pending

    def _write_pending(self, pending: tuple) -> None:
        try:
            self.store.write_batch(*pending)
        except Exception:  # noqa: BLE001 - never let a write kill the loop
            log.exception("ingest flush failed")

    def flush(self) -> None:
        """Write everything pending now, on the calling thread (shutdown, tests)."""
        pending = self._take_pending()
        if pending:
            self._write_pending(pending)

    async def _off_loop(self, fn, *args):
        """Run a store write in a worker thread. Shielded, so cancelling the
        caller never cancels the write itself; stop() waits for it."""
        fut = asyncio.ensure_future(asyncio.to_thread(fn, *args))
        self._in_flight.add(fut)
        fut.add_done_callback(self._in_flight.discard)
        return await asyncio.shield(fut)

    async def _loop_flush_frames(self) -> None:
        while True:
            await asyncio.sleep(self.flush_seconds)
            pending = self._take_pending()
            if pending:
                await self._off_loop(self._write_pending, pending)

    async def _loop_flush_inventory(self) -> None:
        while True:
            await asyncio.sleep(self.inventory_seconds)
            devices, aps = self._take_inventory()
            await self._off_loop(self._write_inventory, devices, aps)

    def _take_inventory(self) -> tuple[list[dict], list[dict]]:
        """Snapshot the dirty inventory rows. Runs on the loop."""
        devices = [self._device_row(m) for m in self._dirty_devices if m in self._devices]
        aps = [self._ap_row(b) for b in self._dirty_aps if b in self._aps]
        self._dirty_devices.clear()
        self._dirty_aps.clear()
        return devices, aps

    def _write_inventory(self, devices: list[dict], aps: list[dict]) -> None:
        try:
            self.store.upsert_devices(devices)
            self.store.upsert_aps(aps)
        except Exception:  # noqa: BLE001
            log.exception("inventory flush failed")

    def _flush_inventory(self) -> None:
        self._write_inventory(*self._take_inventory())

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
            self._publish({"type": "batch", "frames": frames, "threats": threats,
                           "fps": self.fps()})

    def _publish(self, msg: dict) -> None:
        """Queue *msg* for every subscriber. A full queue (a slow link, a throttled
        background tab) drops its OLDEST batch, so the client stays current and
        memory stays bounded at SUBSCRIBER_QUEUE_CAP per client. Runs on the loop."""
        for q in list(self.subscribers):
            if q.full():
                with contextlib.suppress(asyncio.QueueEmpty):
                    q.get_nowait()
                self.ws_dropped += 1
            q.put_nowait(msg)

    async def _loop_summary(self) -> None:
        while True:
            interval = int(self.cfg("summary_interval_seconds", 60))
            await asyncio.sleep(max(5, interval))
            summary = self.build_summary()
            await self._off_loop(self.store.insert_summary, summary)
            self.wazuh.send_summary(summary)

    async def _loop_prune(self) -> None:
        while True:
            await asyncio.sleep(self.prune_seconds)
            try:
                report = await self._off_loop(
                    self.store.prune,
                    float(self.cfg("raw_retention_hours", 48)),
                    float(self.cfg("disk_guard_percent", 85)))
                if report["deleted"] or report["guard_deleted"]:
                    log.info("prune %s", report)
                args = self._inventory_purge_args()
                inv = await self._off_loop(self.store.prune_inventory, *args)
                self._prune_inventory_maps(*args, inv)
            except Exception:  # noqa: BLE001
                log.exception("prune failed")

    def _inventory_purge_args(self) -> tuple[float, float, set[str]]:
        dev_purge = float(self.cfg("device_retention_hours", 24)) * 3600
        ap_purge = float(self.cfg("ap_retention_hours", 168)) * 3600
        muted = {str(m).upper() for m in (self.cfg("muted_devices", []) or [])}
        return dev_purge, ap_purge, muted

    def _prune_inventory(self) -> None:
        """Age out stale devices/APs from the DB and the in-memory maps so the
        inventory (and RAM) don't grow without bound as transient MACs pass by."""
        args = self._inventory_purge_args()
        self._prune_inventory_maps(*args, self.store.prune_inventory(*args))

    def _prune_inventory_maps(self, dev_purge: float, ap_purge: float,
                              muted: set[str], report: dict) -> None:
        """Mirror a DB purge in the live maps (muted clients and known APs are
        exempt). Runs on the loop."""
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
            "ws_dropped": self.ws_dropped,
        }
