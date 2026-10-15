"""Evil-twin / rogue AP rule. Author: gurvinny"""
import unittest

from _support import frame, make_cfg, sim_events

from spectre.detect.evil_twin import EvilTwin

GOOD = "00:00:5E:00:53:01"
ROGUE = "00:00:5E:00:53:66"
ROGUE2 = "00:00:5E:00:53:67"


def beacon(ts, bssid, ssid="ExampleNet", band="2.4GHz", kind="BEACON"):
    return frame(ts, band=band, type=kind, ch=6, rssi=-40, src=bssid,
                 dst="FF:FF:FF:FF:FF:FF", bssid=bssid, ssid=ssid)


class TestEvilTwin(unittest.TestCase):

    def setUp(self):
        self.cfg = make_cfg(evil_twin_learn=False)
        self.rule = EvilTwin(self.cfg)

    def allow(self, *rows):
        self.rule.set_known_networks(list(rows))

    def test_without_an_allowlist_nothing_fires(self):
        self.assertEqual(self.rule.process(beacon(1, ROGUE)), [])

    def test_allowed_bssid_is_silent(self):
        self.allow({"ssid": "ExampleNet", "bssid": GOOD})
        self.assertEqual(self.rule.process(beacon(1, GOOD)), [])

    def test_known_ssid_from_unlisted_bssid_is_critical(self):
        self.allow({"ssid": "ExampleNet", "bssid": GOOD})
        [t] = self.rule.process(beacon(1, ROGUE))
        self.assertEqual((t.rule, t.severity, t.bssid, t.ssid),
                         ("evil_twin", "critical", ROGUE, "ExampleNet"))
        self.assertEqual(t.detail["known_bssids"], [GOOD])
        self.assertEqual(t.detail["rogue_bssid"], ROGUE)

    def test_probe_response_is_checked_too(self):
        self.allow({"ssid": "ExampleNet", "bssid": GOOD})
        self.assertEqual(len(self.rule.process(beacon(1, ROGUE, kind="PROBE_RESP"))), 1)

    def test_client_frames_are_ignored(self):
        self.allow({"ssid": "ExampleNet", "bssid": GOOD})
        self.assertEqual(self.rule.process(beacon(1, ROGUE, kind="PROBE_REQ")), [])
        self.assertEqual(self.rule.process(beacon(2, ROGUE, kind="ASSOC_REQ")), [])

    def test_unknown_ssid_is_not_judged(self):
        self.allow({"ssid": "ExampleNet", "bssid": GOOD})
        self.assertEqual(self.rule.process(beacon(1, ROGUE, ssid="Other")), [])

    def test_a_rogue_alerts_once_not_per_beacon(self):
        self.allow({"ssid": "ExampleNet", "bssid": GOOD})
        out = [t for i in range(5) for t in self.rule.process(beacon(i, ROGUE))]
        self.assertEqual([t.bssid for t in out], [ROGUE])

    def test_each_rogue_bssid_alerts_separately(self):
        self.allow({"ssid": "ExampleNet", "bssid": GOOD})
        out = self.rule.process(beacon(1, ROGUE)) + self.rule.process(beacon(2, ROGUE2))
        self.assertEqual({t.bssid for t in out}, {ROGUE, ROGUE2})

    def test_allowlist_bssid_matches_regardless_of_case(self):
        self.allow({"ssid": "ExampleNet", "bssid": GOOD.lower()})
        self.assertEqual(self.rule.process(beacon(1, GOOD)), [])

    def test_several_allowed_bssids_for_one_ssid(self):
        self.allow({"ssid": "ExampleNet", "bssid": GOOD},
                   {"ssid": "ExampleNet", "bssid": ROGUE2})
        self.assertEqual(self.rule.process(beacon(1, ROGUE2)), [])
        [t] = self.rule.process(beacon(2, ROGUE))
        self.assertEqual(t.detail["known_bssids"], sorted([GOOD, ROGUE2]))

    def test_pinned_band_mismatch_is_high(self):
        self.allow({"ssid": "ExampleNet", "bssid": GOOD, "band": "2.4GHz"})
        [t] = self.rule.process(beacon(1, GOOD, band="5GHz"))
        self.assertEqual((t.severity, t.detail),
                         ("high", {"expected_band": "2.4GHz", "seen_band": "5GHz"}))
        self.assertEqual(self.rule.process(beacon(2, GOOD, band="5GHz")), [])

    def test_matching_band_is_silent(self):
        self.allow({"ssid": "ExampleNet", "bssid": GOOD, "band": "2.4GHz"})
        self.assertEqual(self.rule.process(beacon(1, GOOD, band="2.4GHz")), [])

    def test_ssid_only_entry_with_band_still_checks_band(self):
        # No BSSID pinned: band pin alone, and every BSSID is "unlisted".
        self.allow({"ssid": "ExampleNet", "band": "2.4GHz"})
        self.assertEqual(self.rule.process(beacon(1, GOOD, band="2.4GHz")), [])

    def test_refreshing_the_allowlist_rearms_alerts(self):
        self.allow({"ssid": "ExampleNet", "bssid": GOOD})
        self.assertEqual(len(self.rule.process(beacon(1, ROGUE))), 1)
        self.allow({"ssid": "ExampleNet", "bssid": GOOD})
        self.assertEqual(len(self.rule.process(beacon(2, ROGUE))), 1)

    def test_learn_mode_baselines_the_first_bssid(self):
        self.cfg.values["evil_twin_learn"] = True
        self.assertEqual(self.rule.process(beacon(1, GOOD)), [])
        self.assertEqual(self.rule.process(beacon(2, GOOD)), [])
        [t] = self.rule.process(beacon(3, ROGUE))
        self.assertEqual(t.detail["known_bssids"], [GOOD])

    def test_hidden_ssid_is_ignored(self):
        self.allow({"ssid": "ExampleNet", "bssid": GOOD})
        self.assertEqual(self.rule.process(beacon(1, ROGUE, ssid="?")), [])

    def test_simulated_twin_is_flagged_once(self):
        self.allow({"ssid": "ExampleNet", "bssid": GOOD})
        out = [t for ev in sim_events("evil_twin") for t in self.rule.process(ev)]
        self.assertEqual([(t.bssid, t.severity) for t in out], [(ROGUE, "critical")])


if __name__ == "__main__":
    unittest.main()
