"""New-device / RSSI anomaly rule. Author: gurvinny"""
import unittest

import json

from _support import frame, make_cfg

from spectre.parser import Parser
from spectre.sim.generate import TAG

from spectre.detect.anomaly import AnomalyRule, _is_random_mac

DEV = "00:00:5E:00:53:10"
DEV2 = "00:00:5E:00:53:11"
RAND = "36:00:5E:00:53:13"
AP = "00:00:5E:00:53:01"
# Real epoch seconds: per-device cooldowns start from 0.0, so a test clock near
# zero would sit inside a cooldown that production never sees.
T0 = 1_700_000_000.0


def seen(ts, mac=DEV, rssi=-60, bssid=AP, ch=6, band="2.4GHz"):
    return frame(T0 + ts, type="PROBE_REQ", ch=ch, rssi=rssi, src=mac, band=band,
                 dst="FF:FF:FF:FF:FF:FF", bssid=bssid)


def ap_info(bssid=AP, ds_ch=6, band="2.4GHz"):
    """An ap_info record as the parser hands it to the pipeline."""
    fields = {"event": "ap_info", "why": "changed", "bssid": bssid, "ch": ds_ch,
              "ssid": "LabNet"}
    if ds_ch is not None:
        fields["ds_ch"] = ds_ch
    recs = []
    Parser("sensor-test", default_band=band, on_ap_info=recs.append).parse_line(
        TAG + json.dumps(fields))
    return recs[0]


def beacon(ts, rssi, ch=6, ap=AP, band="2.4GHz"):
    return frame(T0 + ts, type="BEACON", ch=ch, rssi=rssi, src=ap, band=band,
                 dst="FF:FF:FF:FF:FF:FF", bssid=ap, ssid="LabNet")


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
                            rssi_jump_cooldown_seconds=60,
                            rssi_jump_max_age_seconds=10)
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
        self.assertEqual(self.feed(seen(100), seen(101, rssi=-1), seen(101.1, rssi=-1)), [])

    def test_broadcast_source_is_ignored(self):
        # FF:.. has the locally-administered bit set, so randomized alerts must
        # be on or the random-MAC filter would hide a broken broadcast check.
        self.cfg.values["alert_randomized_devices"] = True
        self.assertEqual(self.feed(seen(100, mac="ff:ff:ff:ff:ff:ff")), [])

    # ── RSSI jump ──────────────────────────────────────────────────────
    def test_rssi_jump_at_threshold_alerts_with_both_values(self):
        self.feed(seen(30, rssi=-90))
        [t] = self.feed(seen(31, rssi=-35), seen(31.1, rssi=-35))
        self.assertEqual(t.detail, {"previous_rssi": -90, "current_rssi": -35,
                                    "delta": 55})

    def test_rssi_drop_counts_as_a_jump(self):
        self.feed(seen(30, rssi=-30))
        [t] = self.feed(seen(31, rssi=-90), seen(31.1, rssi=-90))
        self.assertEqual(t.detail["delta"], -60)

    def test_rssi_change_below_threshold_is_silent(self):
        self.feed(seen(30, rssi=-90))
        self.assertEqual(self.feed(seen(31, rssi=-36), seen(31.1, rssi=-36)), [])

    def test_rssi_jump_cooldown_is_per_device(self):
        self.feed(seen(30, rssi=-90), seen(30, mac=DEV2, rssi=-90))
        a = self.feed(seen(31, rssi=-30), seen(31.1, rssi=-30))
        b = self.feed(seen(32, rssi=-90), seen(32.1, rssi=-90))  # inside DEV's cooldown
        c = self.feed(seen(32, mac=DEV2, rssi=-30),
                      seen(32.1, mac=DEV2, rssi=-30))           # DEV2 has its own
        self.feed(seen(94, rssi=-90))                # fresh same-channel baseline
        d = self.feed(seen(95, rssi=-30), seen(95.1, rssi=-30))  # DEV cooldown expired
        self.assertEqual([len(a), len(b), len(c), len(d)], [1, 0, 1, 1])

    # Channel hopping: a strong AP leaks onto neighbouring channels at a much
    # lower RSSI, so readings are only comparable on the same band + channel.
    def test_reading_on_another_channel_is_not_a_jump(self):
        self.feed(seen(30, rssi=-19, ch=9))
        self.assertEqual(self.feed(seen(31, rssi=-77, ch=4), seen(31.1, rssi=-77, ch=4)), [])

    def test_reading_on_another_band_is_not_a_jump(self):
        self.feed(seen(30, rssi=-19, ch=6))
        self.assertEqual(self.feed(seen(31, rssi=-77, ch=6, band="5GHz"),
                                   seen(31.1, rssi=-77, ch=6, band="5GHz")), [])

    def test_jump_is_measured_against_the_same_channel_reading(self):
        self.feed(seen(30, rssi=-20, ch=9), seen(30.5, rssi=-77, ch=4))
        [t] = self.feed(seen(31, rssi=-80, ch=9), seen(31.1, rssi=-80, ch=9))
        self.assertEqual(t.detail, {"previous_rssi": -20, "current_rssi": -80,
                                    "delta": -60})

    def test_reading_older_than_max_age_is_not_compared(self):
        self.feed(seen(30, rssi=-20))
        self.assertEqual(self.feed(seen(40.5, rssi=-80), seen(40.6, rssi=-80)), [])

    def test_reading_at_max_age_is_still_compared(self):
        self.feed(seen(30, rssi=-20))
        self.assertEqual(len(self.feed(seen(40, rssi=-80), seen(40.1, rssi=-80))), 1)

    def test_stale_reading_is_replaced_by_the_new_one(self):
        self.feed(seen(30, rssi=-20), seen(45, rssi=-80))
        self.assertEqual(len(self.feed(seen(46, rssi=-20), seen(46.1, rssi=-20))), 1)

    def test_max_age_change_is_picked_up_live(self):
        self.cfg.values["rssi_jump_max_age_seconds"] = 30
        self.feed(seen(30, rssi=-20))
        self.assertEqual(len(self.feed(seen(55, rssi=-80), seen(55.1, rssi=-80))), 1)

    def test_first_reading_is_never_a_jump(self):
        self.cfg.values["new_device_alerts"] = False
        self.assertEqual(self.feed(seen(100, rssi=-10)), [])

    # A hopping radio can stamp a frame heard on the channel it is leaving with
    # the channel it is tuning to: one far-off reading, then the next frame on
    # that channel is back at the old level. A jump must hold for two readings.
    def test_jump_that_does_not_hold_for_the_next_reading_is_silent(self):
        self.feed(seen(30, rssi=-4, ch=1))
        self.assertEqual(self.feed(seen(33.9, rssi=-61, ch=1),
                                   seen(34.0, rssi=-5, ch=1)), [])

    def test_jump_confirmed_by_the_next_reading_alerts_once(self):
        self.feed(seen(30, rssi=-90))
        self.assertEqual(self.feed(seen(31, rssi=-35)), [])
        [t] = self.feed(seen(31.1, rssi=-34), seen(31.2, rssi=-34))
        self.assertEqual((t.ts, t.detail), (T0 + 31.1, {
            "previous_rssi": -90, "current_rssi": -34, "delta": 56}))

    def test_confirming_reading_is_measured_against_the_pre_jump_level(self):
        self.feed(seen(30, rssi=-90), seen(31, rssi=-30))
        [t] = self.feed(seen(31.1, rssi=-35))       # -35 vs -30 is no jump
        self.assertEqual(t.detail["previous_rssi"], -90)

    def test_confirming_reading_after_max_age_does_not_alert(self):
        self.feed(seen(30, rssi=-20), seen(31, rssi=-80))
        self.assertEqual(self.feed(seen(41.5, rssi=-80)), [])

    def test_confirming_reading_at_max_age_still_alerts(self):
        self.feed(seen(30, rssi=-20), seen(31, rssi=-80))
        self.assertEqual(len(self.feed(seen(41, rssi=-80))), 1)

    def test_rejected_straggler_does_not_become_the_baseline(self):
        self.feed(seen(30, rssi=-4), seen(31, rssi=-61), seen(31.1, rssi=-5))
        self.assertEqual(self.feed(seen(31.2, rssi=-6)), [])

    def test_rejected_straggler_does_not_block_a_later_jump(self):
        self.feed(seen(30, rssi=-4), seen(31, rssi=-61), seen(31.1, rssi=-5),
                  seen(50, rssi=-5))
        self.assertEqual(len(self.feed(seen(51, rssi=-70), seen(51.1, rssi=-70))), 1)

    def test_unconfirmed_jump_on_another_channel_does_not_confirm_here(self):
        self.feed(seen(30, rssi=-20, ch=1), seen(30, rssi=-20, ch=6),
                  seen(31, rssi=-80, ch=1))
        self.assertEqual(self.feed(seen(31.1, rssi=-80, ch=6)), [])



class TestApOperatingChannel(unittest.TestCase):
    """An auto-channel AP is heard on-air or as leakage depending on where it
    operates, and its own off-channel probe requests arrive on-air anywhere."""

    def setUp(self):
        self.cfg = make_cfg(new_device_warmup_seconds=0)
        self.rule = AnomalyRule(self.cfg)

    def feed(self, *events):
        out = []
        for ev in events:
            out.extend(self.rule.process(ev))
        return out

    def test_jump_on_an_unchanged_operating_channel_still_fires(self):
        self.rule.set_ap_info(ap_info(ds_ch=6))
        self.feed(beacon(30, -15))
        [t] = self.feed(beacon(31, -75), beacon(31.1, -75))
        self.assertEqual(t.detail["delta"], -60)

    def test_readings_across_an_operating_channel_move_are_not_compared(self):
        self.rule.set_ap_info(ap_info(ds_ch=6))
        self.feed(beacon(30, -15))
        self.rule.set_ap_info(ap_info(ds_ch=11))
        self.assertEqual(self.feed(beacon(31, -75), beacon(31.1, -75)), [])

    def test_moving_back_compares_with_the_reading_from_that_channel(self):
        self.rule.set_ap_info(ap_info(ds_ch=6))
        self.feed(beacon(30, -15))
        self.rule.set_ap_info(ap_info(ds_ch=11))
        self.feed(beacon(31, -75))
        self.rule.set_ap_info(ap_info(ds_ch=6))
        [t] = self.feed(beacon(32, -80), beacon(32.1, -80))
        self.assertEqual(t.detail["previous_rssi"], -15)

    def test_ap_probe_request_is_not_compared(self):
        self.rule.set_ap_info(ap_info(ds_ch=6))
        self.feed(beacon(30, -88, ch=11))
        self.assertEqual(self.feed(seen(31, mac=AP, rssi=-22, ch=11),
                                   seen(31.1, mac=AP, rssi=-22, ch=11)), [])

    def test_ap_probe_request_does_not_become_the_baseline(self):
        self.rule.set_ap_info(ap_info(ds_ch=6))
        self.feed(seen(30, mac=AP, rssi=-22, ch=11))
        self.assertEqual(self.feed(beacon(31, -88, ch=11), beacon(31.1, -88, ch=11)), [])

    def test_client_probe_requests_are_still_compared(self):
        self.rule.set_ap_info(ap_info(ds_ch=6))
        self.feed(seen(30, rssi=-90, ch=6))
        self.assertEqual(len(self.feed(seen(31, rssi=-30, ch=6), seen(31.1, rssi=-30, ch=6))), 1)

    def test_ap_info_on_another_band_does_not_change_this_band(self):
        self.rule.set_ap_info(ap_info(ds_ch=36, band="5GHz"))
        self.feed(seen(30, mac=AP, rssi=-88, ch=11))
        self.assertEqual(len(self.feed(seen(31, mac=AP, rssi=-22, ch=11),
                                       seen(31.1, mac=AP, rssi=-22, ch=11))), 1)

    def test_ap_info_without_operating_channel_keeps_the_board_channel_key(self):
        self.rule.set_ap_info(ap_info(ds_ch=None))
        self.feed(beacon(30, -15))
        self.assertEqual(len(self.feed(beacon(31, -75), beacon(31.1, -75))), 1)

    def test_ap_info_bssid_case_is_normalised(self):
        self.rule.set_ap_info(ap_info(bssid=AP.lower(), ds_ch=6))
        self.feed(beacon(30, -15))
        self.rule.set_ap_info(ap_info(bssid=AP.lower(), ds_ch=11))
        self.assertEqual(self.feed(beacon(31, -75), beacon(31.1, -75)), [])


if __name__ == "__main__":
    unittest.main()
