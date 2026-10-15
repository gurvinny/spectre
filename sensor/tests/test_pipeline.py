"""Ingest -> inventory -> detect -> store -> forward -> stream. Author: gurvinny"""
import asyncio
import dataclasses
import json
import time
import unittest

from _support import TempDir, UdpSink, frame, sim_events

from spectre.config import Config
from spectre.pipeline import Pipeline
from spectre.store import Store

AP = "00:00:5E:00:53:01"
ROGUE = "00:00:5E:00:53:66"
DEV = "00:00:5E:00:53:10"


class PipelineCase(unittest.TestCase):

    def setUp(self):
        self.tmp = TempDir()
        self.sink = UdpSink()
        self.store = Store(self.tmp.file("spectre.db"))
        self.cfg = Config(self.store)
        # Never let a test reach the default SIEM address.
        self.cfg.set("wazuh_host", "127.0.0.1")
        self.cfg.set("wazuh_port", self.sink.port)
        # The simulator draws random RSSI per frame, which the RSSI-jump rule
        # rightly flags; park it so each test sees only the rule it is about.
        self.cfg.set("rssi_jump_db", 999)
        self.pipe = Pipeline(self.store, self.cfg)

    def tearDown(self):
        self.store.close()
        self.sink.close()
        self.tmp.cleanup()

    def now_events(self, events):
        """Re-stamp scenario events to the present so cooldowns behave as live."""
        base = time.time()
        return [dataclasses.replace(e, received_at=base + i * 0.01)
                for i, e in enumerate(events)]


class TestInventory(PipelineCase):

    def test_beacon_from_its_own_bssid_becomes_an_ap(self):
        t = time.time()
        self.pipe.ingest(frame(t, type="BEACON", ch=6, rssi=-40, src=AP,
                               dst="FF:FF:FF:FF:FF:FF", bssid=AP, ssid="ExampleNet"))
        self.pipe.ingest(frame(t + 1, type="BEACON", ch=11, rssi=-45, src=AP,
                               dst="FF:FF:FF:FF:FF:FF", bssid=AP, ssid="?"))
        self.pipe._flush_inventory()
        [row] = self.store.list_aps()
        self.assertEqual((row["bssid"], row["ssid"], row["channels"], row["beacons"],
                          row["last_rssi"]), (AP, "ExampleNet", "6,11", 2, -45))

    def test_client_frame_is_a_device_not_an_ap(self):
        t = time.time()
        for i, rssi in enumerate((-70, -40, -55)):
            self.pipe.ingest(frame(t + i, type="PROBE_REQ", rssi=rssi, src=DEV,
                                   dst="FF:FF:FF:FF:FF:FF", bssid=AP, ssid="Home"))
        self.pipe._flush_inventory()
        self.assertEqual(self.store.list_aps(), [])
        [d] = self.store.list_devices()
        self.assertEqual((d["mac"], d["frames"], d["min_rssi"], d["max_rssi"],
                          d["last_rssi"], d["last_ssid"], d["bands"]),
                         (DEV, 3, -70, -40, -55, "Home", "2.4GHz"))

    def test_broadcast_source_is_not_inventoried(self):
        self.pipe.ingest(frame(time.time(), type="DATA", src="ff:ff:ff:ff:ff:ff"))
        self.pipe._flush_inventory()
        self.assertEqual(self.store.list_devices(), [])

    def test_known_ap_is_flagged_after_refresh(self):
        self.store.add_known_network("ExampleNet", AP.lower(), None)
        self.pipe.refresh_known_networks()
        self.pipe.ingest(frame(time.time(), type="BEACON", src=AP, bssid=AP,
                               ssid="ExampleNet"))
        self.pipe._flush_inventory()
        self.assertEqual(self.store.list_aps()[0]["is_known"], 1)
        self.assertEqual(self.pipe.overview()["known_aps"], 1)

    def test_frames_are_buffered_then_flushed(self):
        self.pipe.ingest(frame(time.time(), type="BEACON", src=AP, bssid=AP))
        self.assertEqual(self.store.recent_frames(), [])
        self.pipe._flush_frames()
        self.assertEqual(len(self.store.recent_frames()), 1)

    def test_prune_inventory_drops_stale_but_keeps_muted(self):
        old = time.time() - 3 * 86400
        self.cfg.set("muted_devices", [DEV])
        for mac in (DEV, "00:00:5E:00:53:11"):
            self.pipe.ingest(frame(old, type="PROBE_REQ", src=mac))
        self.pipe._flush_inventory()
        self.pipe._prune_inventory()
        self.assertEqual(set(self.pipe._devices), {DEV})
        self.assertEqual([d["mac"] for d in self.store.list_devices()], [DEV])


class TestThreats(PipelineCase):

    @staticmethod
    def _body(line):
        return line[line.index("] {") + 2:]

    def test_flood_is_stored_and_forwarded_once_per_cooldown(self):
        for ev in self.now_events(sim_events("deauth_flood")):
            self.pipe.ingest(ev)
        threats = self.store.list_threats()
        self.assertEqual([(t["rule"], t["wazuh_sent"]) for t in threats],
                         [("deauth_flood", 1)])
        self.assertEqual(json.loads(self._body(self.sink.recv()))["rule"],
                         "deauth_flood")
        self.assertTrue(self.sink.empty())

    def test_allowlist_from_the_store_drives_evil_twin(self):
        self.store.add_known_network("ExampleNet", AP, None)
        self.pipe.refresh_known_networks()
        for ev in self.now_events(sim_events("evil_twin")):
            self.pipe.ingest(ev)
        self.assertEqual([(t["rule"], t["bssid"]) for t in self.store.list_threats()],
                         [("evil_twin", ROGUE)])

    def test_failed_forward_is_recorded_not_lost(self):
        self.cfg.set("wazuh_enabled", False)
        for ev in self.now_events(sim_events("deauth_flood")):
            self.pipe.ingest(ev)
        self.assertEqual([t["wazuh_sent"] for t in self.store.list_threats()], [0])

    def test_muted_devices_reach_the_engine(self):
        self.cfg.set("new_device_alerts", True)
        self.cfg.set("new_device_warmup_seconds", 0)
        self.cfg.set("muted_devices", [DEV.lower()])
        self.pipe.refresh_muted_devices()
        t = time.time()
        self.pipe.ingest(frame(t, type="PROBE_REQ", src=DEV))
        self.pipe.ingest(frame(t, type="PROBE_REQ", src="00:00:5E:00:53:11"))
        self.assertEqual([r["src"] for r in self.store.list_threats()],
                         ["00:00:5E:00:53:11"])


class TestViewsAndStream(PipelineCase):

    def test_overview_and_summary_reflect_ingest(self):
        t = time.time()
        self.pipe.ingest(frame(t, type="BEACON", ch=6, src=AP, bssid=AP))
        self.pipe.ingest(frame(t, band="5GHz", sensor="s5", type="PROBE_REQ",
                               ch=36, src=DEV))
        ov = self.pipe.overview()
        self.assertEqual((ov["total_frames"], ov["devices"], ov["access_points"]),
                         (2, 2, 1))
        self.assertEqual(ov["channels"], {"6": 1, "36": 1})
        self.assertEqual(ov["band_breakdown"], {"2.4GHz": 1, "5GHz": 1})
        self.assertEqual({s["sensor"] for s in ov["sensors"]}, {"sensor-test", "s5"})
        self.assertTrue(all(s["online"] for s in ov["sensors"]))
        self.assertEqual(self.pipe.build_summary()["top_frame_types"],
                         {"BEACON": 1, "PROBE_REQ": 1})

    def test_subscribers_receive_frames_and_threats_in_a_batch(self):
        async def run():
            q = self.pipe.subscribe()
            task = asyncio.create_task(self.pipe._loop_broadcast())
            for ev in self.now_events(sim_events("deauth_flood")):
                self.pipe.ingest(ev)
            msg = await asyncio.wait_for(q.get(), 2)
            task.cancel()
            self.pipe.unsubscribe(q)
            return msg

        msg = asyncio.run(run())
        self.assertEqual(msg["type"], "batch")
        self.assertEqual(len(msg["frames"]), 40)
        self.assertEqual([t["rule"] for t in msg["threats"]], ["deauth_flood"])

    def test_no_subscribers_means_batches_are_dropped(self):
        async def run():
            task = asyncio.create_task(self.pipe._loop_broadcast())
            self.pipe.ingest(frame(time.time(), type="BEACON", src=AP, bssid=AP))
            await asyncio.sleep(0.4)
            task.cancel()

        asyncio.run(run())
        self.assertEqual(self.pipe._feed_batch, [])


if __name__ == "__main__":
    unittest.main()
