"""Board lifecycle events: parser callback, storage, retention, wiring. Author: gurvinny"""
import asyncio
import os
import time
import unittest
from unittest import mock

from _support import TempDir, UdpSink

from spectre.config import Config
from spectre.parser import Parser
from spectre.pipeline import Pipeline
from spectre.reader import SerialReader
from spectre.sim.generate import SimSource
from spectre.sim.replay import ReplaySource
from spectre.store import Store

BOOT_5 = ('<190>ESP32C5 wifi_sniffer_5g: {"event":"boot","chip":"ESP32-C5",'
          '"mode":"promiscuous","band":"5GHz","channels":"36-165"}')
STARTED = '<190>ESP32C5 wifi_sniffer_5g: {"event":"sniffer_started","ch":36,"usb_cdc":true}'
SWEEP = ('<190>ESP32C5 wifi_sniffer_5g: {"event":"channel_sweep_complete",'
         '"total_pkts":84,"uptime_ms":16570}')
FRAME = ('<190>ESP32C5 wifi_sniffer_5g: {"seq":7,"uptime_ms":2728,"ch":36,"rssi":-55,'
         '"type":"BEACON","src":"00:00:5E:00:53:01","dst":"FF:FF:FF:FF:FF:FF",'
         '"bssid":"00:00:5E:00:53:01","ssid":"ExampleNet"}')


class TestParserCallback(unittest.TestCase):

    def setUp(self):
        self.got = []
        self.parser = Parser("ttyUSB1", on_lifecycle=self.got.append)

    def test_each_lifecycle_line_is_handed_over(self):
        for line in (BOOT_5, STARTED, SWEEP):
            self.assertIsNone(self.parser.parse_line(line))
        self.assertEqual([r["kind"] for r in self.got],
                         ["boot", "sniffer_started", "channel_sweep_complete"])

    def test_record_carries_board_band_and_payload(self):
        before = time.time()
        self.parser.parse_line(BOOT_5)
        self.parser.parse_line(SWEEP)
        boot, sweep = self.got
        self.assertEqual((boot["sensor_id"], boot["band"]), ("ttyUSB1", "5GHz"))
        self.assertEqual(sweep["band"], "5GHz")
        self.assertEqual(sweep["payload"], {"total_pkts": 84, "uptime_ms": 16570})
        self.assertNotIn("event", boot["payload"])
        self.assertEqual(boot["payload"]["channels"], "36-165")
        self.assertGreaterEqual(sweep["received_at"], before)

    def test_frames_do_not_reach_the_callback(self):
        ev = self.parser.parse_line(FRAME)
        self.assertEqual(ev.seq, 7)
        self.assertEqual(self.got, [])

    def test_parser_without_a_callback_still_drops_lifecycle_lines(self):
        p = Parser("ttyUSB1")
        self.assertIsNone(p.parse_line(BOOT_5))
        self.assertEqual(p.band, "5GHz")


class StoreCase(unittest.TestCase):

    def setUp(self):
        self.tmp = TempDir()
        self.store = Store(self.tmp.file("spectre.db"))

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def rec(self, ts, kind="channel_sweep_complete", **payload):
        return {"received_at": ts, "sensor_id": "ttyUSB0", "band": "2.4GHz",
                "kind": kind, "payload": payload}


class TestStore(StoreCase):

    def test_round_trip_in_time_order(self):
        self.store.insert_board_event(self.rec(20.0, total_pkts=9))
        self.store.insert_board_event(self.rec(10.0, kind="boot", channels="1-13"))
        rows = self.store.board_events()
        self.assertEqual([(r["received_at"], r["kind"]) for r in rows],
                         [(10.0, "boot"), (20.0, "channel_sweep_complete")])
        self.assertEqual(rows[1]["payload"], {"total_pkts": 9})
        self.assertEqual((rows[0]["sensor_id"], rows[0]["band"]), ("ttyUSB0", "2.4GHz"))

    def test_since_filters(self):
        for ts in (10.0, 20.0, 30.0):
            self.store.insert_board_event(self.rec(ts))
        self.assertEqual([r["received_at"] for r in self.store.board_events(since=20.0)],
                         [20.0, 30.0])

    def test_prune_follows_raw_retention(self):
        now = time.time()
        self.store.insert_board_event(self.rec(now - 3 * 3600))
        self.store.insert_board_event(self.rec(now - 60))
        with mock.patch.object(self.store, "_disk_used_percent", return_value=10.0):
            self.store.prune(raw_retention_hours=2, disk_guard_percent=85)
        self.assertEqual([r["received_at"] for r in self.store.board_events()], [now - 60])

    def test_disk_guard_trims_board_events_too(self):
        now = time.time()
        for h in (0, 5, 10, 20):
            self.store.insert_board_event(self.rec(now - h * 3600 - 60))
        usage = iter([95.0, 95.0, 50.0])
        with mock.patch.object(self.store, "_disk_used_percent",
                               side_effect=lambda: next(usage)):
            self.store.prune(raw_retention_hours=24, disk_guard_percent=85)
        self.assertEqual(len(self.store.board_events()), 2)


class TestWiring(StoreCase):

    def setUp(self):
        super().setUp()
        self.sink = UdpSink()
        self.cfg = Config(self.store)
        self.cfg.set("wazuh_host", "127.0.0.1")
        self.cfg.set("wazuh_port", self.sink.port)
        self.pipe = Pipeline(self.store, self.cfg)

    def tearDown(self):
        self.sink.close()
        super().tearDown()

    def test_pipeline_records_board_events(self):
        self.pipe.record_board_event(self.rec(5.0, kind="boot"))
        self.assertEqual([r["kind"] for r in self.store.board_events()], ["boot"])

    def test_serial_reader_stores_lifecycle_lines(self):
        reader = SerialReader("/dev/ttyUSB1", 115200, self.pipe)
        r, w = os.pipe()
        try:
            os.set_blocking(r, False)
            reader._fd = r
            os.write(w, (BOOT_5 + "\n" + FRAME + "\n" + SWEEP + "\n").encode())
            reader._on_readable()
        finally:
            os.close(r)
            os.close(w)
        rows = self.store.board_events()
        self.assertEqual([(r["sensor_id"], r["kind"]) for r in rows],
                         [("ttyUSB1", "boot"), ("ttyUSB1", "channel_sweep_complete")])
        self.assertEqual(self.pipe.total_frames, 1)

    def test_replay_stores_lifecycle_lines(self):
        path = self.tmp.file("capture.log")
        with open(path, "w") as fh:
            fh.write(BOOT_5 + "\n" + FRAME + "\n" + SWEEP + "\n")
        src = ReplaySource(self.pipe, path, speed=100.0, loop=False)
        asyncio.run(src.run())
        self.assertEqual([r["kind"] for r in self.store.board_events()],
                         ["boot", "channel_sweep_complete"])

    def test_simulator_parsers_are_wired(self):
        src = SimSource(self.pipe)
        for band, parser in src._parsers.items():
            parser.parse_line(BOOT_5 if band == "5GHz" else BOOT_5.replace("5GHz", "2.4GHz"))
        self.assertEqual(sorted(r["sensor_id"] for r in self.store.board_events()),
                         ["sim-2.4GHz", "sim-5GHz"])


if __name__ == "__main__":
    unittest.main()
