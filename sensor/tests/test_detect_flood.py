"""Beacon / probe flood rule. Author: gurvinny"""
import unittest

from _support import frame, make_cfg, sim_events

from spectre.detect.flood import FloodRule


def beacon(ts, i):
    mac = f"AA:BB:CC:00:00:{i:02X}"
    return frame(ts, type="BEACON", ch=6, rssi=-60, src=mac,
                 dst="FF:FF:FF:FF:FF:FF", bssid=mac, ssid=f"Net{i}")


def probe(ts, i=0):
    return frame(ts, type="PROBE_REQ", ch=6, rssi=-60,
                 src=f"3A:00:00:00:00:{i % 256:02X}", dst="FF:FF:FF:FF:FF:FF")


class TestFloodRule(unittest.TestCase):

    def setUp(self):
        self.cfg = make_cfg(flood_window_seconds=5, flood_cooldown_seconds=30,
                            beacon_flood_distinct_bssids=40,
                            probe_flood_threshold=120)
        self.rule = FloodRule(self.cfg)

    def feed(self, events):
        return [t for ev in events for t in self.rule.process(ev)]

    # ── beacon flood ───────────────────────────────────────────────────
    def test_39_distinct_aps_is_normal(self):
        self.assertEqual(self.feed(beacon(100 + i * 0.01, i) for i in range(39)), [])

    def test_40th_distinct_ap_raises_a_medium_beacon_flood(self):
        [t] = self.feed(beacon(100 + i * 0.01, i) for i in range(40))
        self.assertEqual((t.rule, t.severity), ("beacon_probe_flood", "medium"))
        self.assertEqual(t.detail["distinct_bssids"], 40)
        self.assertTrue(t.title.startswith("Beacon flood"))

    def test_repeat_beacons_from_one_ap_do_not_count_as_distinct(self):
        evs = [beacon(100 + i * 0.01, i % 10) for i in range(200)]
        self.assertEqual(self.feed(evs), [])

    def test_beacons_outside_the_window_are_forgotten(self):
        evs = [beacon(100 + i * 0.01, i) for i in range(30)]
        evs += [beacon(110 + i * 0.01, 100 + i) for i in range(30)]
        self.assertEqual(self.feed(evs), [])

    def test_beacon_alert_respects_the_cooldown(self):
        first = self.feed(beacon(100 + i * 0.01, i) for i in range(40))
        again = self.feed(beacon(110 + i * 0.01, 100 + i) for i in range(40))
        later = self.feed(beacon(140 + i * 0.01, 200 + i) for i in range(40))
        self.assertEqual((len(first), len(again), len(later)), (1, 0, 1))

    # ── probe flood ────────────────────────────────────────────────────
    def test_119_probes_is_normal(self):
        self.assertEqual(self.feed(probe(100 + i * 0.01, i) for i in range(119)), [])

    def test_120th_probe_raises_a_probe_flood(self):
        [t] = self.feed(probe(100 + i * 0.01, i) for i in range(120))
        self.assertEqual(t.detail["probe_reqs"], 120)
        self.assertTrue(t.title.startswith("Probe-request flood"))

    def test_probes_outside_the_window_are_forgotten(self):
        evs = [probe(100 + i * 0.01, i) for i in range(100)]
        evs += [probe(110 + i * 0.01, i) for i in range(100)]
        self.assertEqual(self.feed(evs), [])

    def test_probe_alert_respects_the_cooldown(self):
        first = self.feed(probe(100 + i * 0.001, i) for i in range(120))
        again = self.feed(probe(110 + i * 0.001, i) for i in range(120))
        later = self.feed(probe(140 + i * 0.001, i) for i in range(120))
        self.assertEqual((len(first), len(again), len(later)), (1, 0, 1))

    def test_window_change_is_picked_up_live(self):
        self.cfg.values["flood_window_seconds"] = 1
        evs = [probe(100 + i * 0.02, i) for i in range(120)]  # spans 2.4s
        self.assertEqual(self.feed(evs), [])

    # ── simulator ──────────────────────────────────────────────────────
    def test_simulated_beacon_flood_is_detected(self):
        out = self.feed(sim_events("beacon_flood"))
        self.assertEqual([t.title.split(":")[0] for t in out], ["Beacon flood"])

    def test_simulated_probe_flood_is_detected(self):
        out = self.feed(sim_events("probe_flood", step=0.001))
        self.assertEqual([t.detail["probe_reqs"] for t in out], [120])


if __name__ == "__main__":
    unittest.main()
