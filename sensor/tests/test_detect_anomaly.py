"""New-device / RSSI anomaly rule. Author: gurvinny"""
import unittest

from _support import frame, make_cfg

from spectre.detect.anomaly import AnomalyRule, _is_random_mac

DEV = "00:00:5E:00:53:10"
DEV2 = "00:00:5E:00:53:11"
RAND = "36:00:5E:00:53:13"
AP = "00:00:5E:00:53:01"
# Real epoch seconds: per-device cooldowns start from 0.0, so a test clock near
# zero would sit inside a cooldown that production never sees.
T0 = 1_700_000_000.0


def seen(ts, mac=DEV, rssi=-60, bssid=AP):
    return frame(T0 + ts, type="PROBE_REQ", ch=6, rssi=rssi, src=mac,
                 dst="FF:FF:FF:FF:FF:FF", bssid=bssid)


class TestRandomMac(unittest.TestCase):

    def test_locally_administered_bit(self):
        for mac in ("02:00:00:00:00:00", "36:00:5E:00:53:13", "AE:11:22:33:44:55",
                    "FA:00:00:00:00:00"):
            self.assertTrue(_is_random_mac(mac), mac)
        for mac in ("00:00:5E:00:53:10", "01:00:00:00:00:00", "FC:00:00:00:00:00"):
            self.assertFalse(_is_random_mac(mac), mac)

    def test_garbage_is_not_random(self):
        self.assertFalse(_is_random_mac("zz:00"))
        self.assertFalse(_is_random_mac(""))


class TestAnomalyRule(unittest.TestCase):

    def setUp(self):
        self.cfg = make_cfg(new_device_alerts=True, alert_randomized_devices=False,
                            new_device_warmup_seconds=60, rssi_jump_db=55,
                            rssi_jump_cooldown_seconds=60)
        self.rule = AnomalyRule(self.cfg)
        # Anchor the warm-up clock at t=0 with an unrelated station.
        self.rule.process(seen(0, mac="00:00:5E:00:53:FE"))

    def feed(self, *events):
        return [t for ev in events for t in self.rule.process(ev)]

    # ── new device ─────────────────────────────────────────────────────
    def test_new_device_after_warmup_is_low(self):
        [t] = self.feed(seen(100))
        self.assertEqual((t.rule, t.severity, t.src), ("anomaly", "low", DEV))
        self.assertEqual(t.detail["randomized_mac"], False)

    def test_a_device_is_new_only_once(self):
        self.assertEqual(len(self.feed(seen(100), seen(101), seen(102))), 1)

    def test_devices_seen_during_warmup_are_learned_silently(self):
        self.assertEqual(self.feed(seen(30)), [])
        self.assertEqual(self.feed(seen(100)), [])

    def test_alerts_off_by_config(self):
        self.cfg.values["new_device_alerts"] = False
        self.assertEqual(self.feed(seen(100)), [])

    def test_randomized_mac_is_suppressed_by_default(self):
        self.assertEqual(self.feed(seen(100, mac=RAND)), [])

    def test_randomized_mac_alert_is_info_when_enabled(self):
        self.cfg.values["alert_randomized_devices"] = True
        [t] = self.feed(seen(100, mac=RAND))
        self.assertEqual((t.severity, t.detail["randomized_mac"]), ("info", True))
        self.assertIn("randomized", t.title)

    def test_ap_transmitting_as_itself_is_not_a_new_device(self):
        self.assertEqual(self.feed(seen(100, mac=AP, bssid=AP)), [])

    def test_muted_device_is_silent(self):
        self.rule.set_muted_devices([DEV.lower()])
        self.assertEqual(self.feed(seen(100), seen(101, rssi=-1)), [])

    def test_broadcast_source_is_ignored(self):
        self.assertEqual(self.feed(seen(100, mac="ff:ff:ff:ff:ff:ff")), [])

    # ── RSSI jump ──────────────────────────────────────────────────────
    def test_rssi_jump_at_threshold_alerts_with_both_values(self):
        self.feed(seen(30, rssi=-90))
        [t] = self.feed(seen(31, rssi=-35))
        self.assertEqual(t.detail, {"previous_rssi": -90, "current_rssi": -35,
                                    "delta": 55})

    def test_rssi_drop_counts_as_a_jump(self):
        self.feed(seen(30, rssi=-30))
        [t] = self.feed(seen(31, rssi=-90))
        self.assertEqual(t.detail["delta"], -60)

    def test_rssi_change_below_threshold_is_silent(self):
        self.feed(seen(30, rssi=-90))
        self.assertEqual(self.feed(seen(31, rssi=-36)), [])

    def test_rssi_jump_cooldown_is_per_device(self):
        self.feed(seen(30, rssi=-90), seen(30, mac=DEV2, rssi=-90))
        a = self.feed(seen(31, rssi=-30))
        b = self.feed(seen(32, rssi=-90))            # inside DEV's cooldown
        c = self.feed(seen(32, mac=DEV2, rssi=-30))  # DEV2 has its own
        d = self.feed(seen(95, rssi=-30))            # DEV cooldown expired
        self.assertEqual([len(a), len(b), len(c), len(d)], [1, 0, 1, 1])

    def test_first_reading_is_never_a_jump(self):
        self.cfg.values["new_device_alerts"] = False
        self.assertEqual(self.feed(seen(100, rssi=-10)), [])


if __name__ == "__main__":
    unittest.main()
