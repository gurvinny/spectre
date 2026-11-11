"""The event loop and API reads never wait on the store's write lock. Author: gurvinny"""
import asyncio
import threading
import time
import unittest

from _support import TempDir, UdpSink, frame, sim_events

from spectre import store as store_mod
from spectre.config import Config
from spectre.pipeline import Pipeline
from spectre.store import Store

AP = "00:00:5E:00:53:01"


_THREADS: list[threading.Thread] = []


def run_in_thread(fn, timeout=2.0):
    """Run *fn* in a thread; return (finished, result). A thread still running
    when this returns is joined in tearDown, before the store closes under it."""
    out = {}

    def target():
        out["r"] = fn()

    t = threading.Thread(target=target, daemon=True)
    _THREADS.append(t)
    t.start()
    t.join(timeout)
    return (not t.is_alive()), out.get("r")


class CountingLock:
    """A lock that counts how often it was taken and, given the writer
    connection, the most rows changed during any one hold."""

    def __init__(self, db=None):
        self._lock = threading.Lock()
        self._db = db
        self.acquired = 0
        self.max_changes = 0

    def __enter__(self):
        self._lock.acquire()
        self.acquired += 1
        self._start = self._db.total_changes if self._db else 0
        return self

    def __exit__(self, *exc):
        if self._db:
            try:
                self.max_changes = max(self.max_changes,
                                       self._db.total_changes - self._start)
            except Exception:       # the hold that closed the connection
                pass
        self._lock.release()

    def acquire(self, *a, **k):
        ok = self._lock.acquire(*a, **k)
        if ok:
            self.acquired += 1
        return ok

    def release(self):
        self._lock.release()


class Case(unittest.TestCase):

    def setUp(self):
        self.tmp = TempDir()
        self.sink = UdpSink()
        self.store = Store(self.tmp.file("spectre.db"))
        self.cfg = Config(self.store)
        self.cfg.set("wazuh_host", "127.0.0.1")
        self.cfg.set("wazuh_port", self.sink.port)
        self.cfg.set("rssi_jump_db", 999)
        self.pipe = Pipeline(self.store, self.cfg)

    def tearDown(self):
        while _THREADS:
            _THREADS.pop().join(10)
        self.store.close()
        self.sink.close()
        self.tmp.cleanup()


class TestReadsDoNotWaitForWrites(Case):

    def test_api_reads_complete_while_a_write_holds_the_lock(self):
        self.store.upsert_devices([{
            "mac": AP, "first_seen": 1.0, "last_seen": 2.0, "bands": "2.4GHz",
            "last_rssi": -40, "min_rssi": -40, "max_rssi": -40, "frames": 1,
            "is_random": 0, "last_ssid": "ExampleNet"}])
        self.store.create_session("tok", "admin", 3600)
        self.store._lock.acquire()          # a long write in progress
        try:
            done, r = run_in_thread(lambda: (
                len(self.store.list_devices()), self.store.get_config("deauth_threshold"),
                self.store.get_session("tok")["username"], len(self.store.search("ExampleNet")),
                self.store.recent_frames(), self.store.latest_board_events(),
                self.store.count_threats_since(0)))
        finally:
            self.store._lock.release()
        self.assertTrue(done, "a read waited for the write lock")
        self.assertEqual(r[:4], (1, 20, "admin", 1))

    def test_a_reader_sees_writes_committed_after_it_first_read(self):
        self.assertIsNone(self.store.get_session("late"))
        self.store.create_session("late", "admin", 3600)
        self.assertEqual(self.store.get_session("late")["username"], "admin")
        done, r = run_in_thread(lambda: self.store.get_session("late"))
        self.assertTrue(done)
        self.assertEqual(r["username"], "admin")

    def test_reader_connections_cannot_write(self):
        import sqlite3
        with self.assertRaises(sqlite3.OperationalError):
            self.store._read().execute("DELETE FROM config")


class TestIngestNeverTakesTheWriteLock(Case):

    def test_ingest_and_lifecycle_lines_return_while_the_lock_is_held(self):
        events = sim_events("deauth_flood")
        def feed():
            for ev in events:
                self.pipe.ingest(ev)
            self.pipe.record_board_event({"received_at": 5.0, "sensor_id": "s",
                                          "band": "2.4GHz", "kind": "telemetry",
                                          "payload": {"rx_total": 1}})
            self.pipe.record_ap_info({"received_at": 5.0, "sensor_id": "s", "band": "2.4GHz",
                                      "kind": "ap_info", "payload": {"bssid": AP, "ssid": "x"}})

        self.store._lock.acquire()
        done, _ = run_in_thread(feed, timeout=1.0)
        self.store._lock.release()
        self.assertTrue(done, "ingest waited for the write lock")
        self.pipe.flush()
        self.assertEqual(len(self.store.recent_frames(limit=10_000)), len(events))
        self.assertEqual([e["kind"] for e in self.store.board_events()], ["telemetry"])
        self.assertEqual(len(self.store.ap_info()), 1)
        self.assertTrue(any(t["rule"] == "deauth_flood" for t in self.store.list_threats()))

    def test_flush_writes_everything_in_arrival_order(self):
        for i in range(3):
            self.pipe.record_board_event({"received_at": float(i), "sensor_id": "s",
                                          "band": "2.4GHz", "kind": f"k{i}", "payload": {}})
        self.pipe.flush()
        self.assertEqual([e["kind"] for e in self.store.board_events()], ["k0", "k1", "k2"])
        self.pipe.flush()                   # nothing pending: no duplicates
        self.assertEqual(len(self.store.board_events()), 3)


class TestLoopKeepsRunning(Case):

    def test_background_writes_do_not_block_the_event_loop(self):
        for i in range(50):
            self.pipe.ingest(frame(time.time(), type="BEACON", src=AP, bssid=AP, ssid="x"))
        self.store.insert_frames([frame(time.time() - 100 * 3600, type="BEACON")])
        # every background write fires several times while the lock is held
        self.pipe.flush_seconds = self.pipe.inventory_seconds = 0.05
        self.pipe.prune_seconds = 0.05

        async def scenario():
            self.store._lock.acquire()      # every write now has to wait
            # Released from another thread, so a blocked loop cannot hang the test.
            threading.Timer(1.6, self.store._lock.release).start()
            self.pipe.start()
            ticks = 0
            t_end = time.monotonic() + 1.6
            while time.monotonic() < t_end:
                await asyncio.sleep(0.01)
                ticks += 1
            await asyncio.sleep(0.2)
            await self.pipe.stop()
            return ticks

        ticks = asyncio.run(scenario())
        # 1.6 s at 10 ms is ~160 ticks; a loop blocked on the lock manages a handful.
        self.assertGreater(ticks, 80)
        self.assertEqual(len(self.store.recent_frames(limit=1000)), 50)   # old one pruned
        self.assertEqual([a["bssid"] for a in self.store.list_aps()], [AP])


class TestShutdown(Case):

    def test_stop_waits_for_a_write_already_in_flight(self):
        events = [frame(time.time() + i * 0.001, type="BEACON", src=AP, bssid=AP, ssid="x")
                  for i in range(20)]
        real_write = self.store.write_batch
        in_flight, proceed = threading.Event(), threading.Event()

        def slow_first_write(*args):
            if not in_flight.is_set():
                in_flight.set()
                proceed.wait(5)             # the first flush is stuck in its thread
            real_write(*args)

        self.store.write_batch = slow_first_write

        async def scenario():
            self.pipe.flush_seconds = 0.05
            self.pipe.start()
            for ev in events[:10]:
                self.pipe.ingest(ev)
            while not in_flight.is_set():
                await asyncio.sleep(0.01)
            for ev in events[10:]:
                self.pipe.ingest(ev)        # still in the buffer at stop()
            stopping = asyncio.create_task(self.pipe.stop())
            await asyncio.sleep(0.3)
            returned_early = stopping.done()
            proceed.set()
            await stopping
            return returned_early

        returned_early = asyncio.run(scenario())
        self.assertFalse(returned_early, "stop() returned with a write still in flight")
        rows = self.store.recent_frames(limit=100)
        self.assertEqual(len(rows), 20)
        # arrival order survives: the in-flight batch commits before the final flush
        self.assertEqual([r["received_at"] for r in rows][::-1],
                         [e.received_at for e in events])


class TestReaderConnections(Case):

    def test_dead_threads_readers_do_not_pile_up(self):
        self.store.list_devices()           # this thread's reader
        for _ in range(5):
            done, _ = run_in_thread(lambda: self.store.list_devices())
            self.assertTrue(done)
        # each new reader closes the ones dead threads left: this thread's, plus
        # the last worker's (closed when the next reader opens)
        self.assertEqual(len(self.store._readers), 2)
        dead = [db for t, db in self.store._readers if not t.is_alive()]
        self.assertEqual(len(dead), 1)


class TestPruneReleasesTheLock(Case):

    def test_old_frames_are_deleted_in_chunks(self):
        old = time.time() - 100 * 3600
        self.store.insert_frames([frame(old + i * 0.001, type="BEACON")
                                  for i in range(2 * store_mod.PRUNE_CHUNK + 7)])
        self.store._lock = CountingLock(self.store._db)
        report = self.store.prune(48, 100)
        self.assertEqual(report["deleted"], 2 * store_mod.PRUNE_CHUNK + 7)
        self.assertEqual(self.store.recent_frames(limit=10), [])
        # no single lock hold deletes more than one chunk
        self.assertEqual(self.store._lock.max_changes, store_mod.PRUNE_CHUNK)

    def test_inventory_upserts_commit_in_chunks(self):
        rows = [{"mac": f"02:00:00:00:{i // 256:02X}:{i % 256:02X}", "first_seen": 1.0,
                 "last_seen": 2.0, "bands": "2.4GHz", "last_rssi": -50, "min_rssi": -50,
                 "max_rssi": -50, "frames": 1, "is_random": 1, "last_ssid": None}
                for i in range(2 * store_mod.UPSERT_CHUNK + 1)]
        self.store._lock = CountingLock()
        self.store.upsert_devices(rows)
        self.assertEqual(self.store._lock.acquired, 3)
        self.assertEqual(len(self.store.list_devices(limit=10_000)), len(rows))


if __name__ == "__main__":
    unittest.main()
