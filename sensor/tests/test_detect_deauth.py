"""Deauth / disassoc flood rule. Author: gurvinny"""
import unittest

from _support import frame, make_cfg, sim_events

from spectre.detect.deauth_flood import DeauthFlood

AP = "00:00:5E:00:53:01"
AP2 = "00:00:5E:00:53:02"
VICTIM = "00:00:5E:00:53:10"


def deauth(ts, bssid=AP, kind="DEAUTH", **v2):
    return frame(ts, type=kind, ch=6, rssi=-50, src=bssid, dst=VICTIM, bssid=bssid, **v2)


RETRY, PROTECTED = 0x08, 0x40


class TestDeauthFlood(unittest.TestCase):

    def setUp(self):
        self.cfg = make_cfg(deauth_window_seconds=10, deauth_threshold=20)
        self.rule = DeauthFlood(self.cfg)

    def feed(self, events):
        out = []
        for ev in events:
            out.extend(self.rule.process(ev))
        return out

    def test_below_threshold_is_silent(self):
        self.assertEqual(self.feed(deauth(100 + i * 0.1) for i in range(19)), [])

    def test_threshold_frame_raises_one_high_threat_with_the_count(self):
        threats = self.feed(deauth(100 + i * 0.1) for i in range(20))
        self.assertEqual(len(threats), 1)
        t = threats[0]
        self.assertEqual((t.rule, t.severity, t.bssid), ("deauth_flood", "high", AP))
        self.assertEqual(t.detail["frames_in_window"], 20)
        self.assertEqual(t.detail["threshold"], 20)
        self.assertEqual(t.detail["target_dst"], VICTIM)
        self.assertEqual(t.detail["rate_per_sec"], 2.0)
        self.assertIn(AP, t.title)

    def test_disassoc_counts_toward_the_same_window(self):
        evs = [deauth(100 + i * 0.1, kind="DISASSOC" if i % 2 else "DEAUTH")
               for i in range(20)]
        self.assertEqual(len(self.feed(evs)), 1)

    def test_other_frame_types_do_not_count(self):
        evs = [deauth(100 + i * 0.1) for i in range(19)]
        evs += [frame(102 + i * 0.1, type=t, src=AP, bssid=AP, dst=VICTIM)
                for i, t in enumerate(["BEACON", "AUTH", "ASSOC_REQ", "PROBE_RESP"])]
        self.assertEqual(self.feed(evs), [])

    def test_frames_older_than_the_window_are_evicted(self):
        early = [deauth(100 + i * 0.1) for i in range(19)]
        late = [deauth(111)]  # 11s later: the first 19 are out of a 10s window
        self.assertEqual(self.feed(early + late), [])

    def test_frame_exactly_at_the_window_edge_still_counts(self):
        evs = [deauth(100)] + [deauth(110) for _ in range(19)]
        self.assertEqual(len(self.feed(evs)), 1)

    def test_bssids_are_counted_independently(self):
        evs = []
        for i in range(19):
            evs += [deauth(100 + i * 0.1, AP), deauth(100 + i * 0.1, AP2)]
        self.assertEqual(self.feed(evs), [])

    def test_threshold_is_read_live(self):
        self.cfg.values["deauth_threshold"] = 5
        threats = self.feed(deauth(100 + i * 0.1) for i in range(5))
        self.assertEqual([t.detail["threshold"] for t in threats], [5])

    def test_simulated_attack_is_detected_against_the_scenario_ap(self):
        threats = self.feed(sim_events("deauth_flood"))
        self.assertTrue(threats)
        self.assertEqual({t.bssid for t in threats}, {AP})
        self.assertEqual({t.rule for t in threats}, {"deauth_flood"})
        # 40 frames, threshold 20: frames 20..40 are all at-or-over threshold.
        self.assertEqual(len(threats), 21)


if __name__ == "__main__":
    unittest.main()


class TestDeauthRetransmissions(unittest.TestCase):
    """An AP retransmits one unacknowledged frame many times: same sn, Retry set."""

    def setUp(self):
        self.cfg = make_cfg(deauth_window_seconds=10, deauth_threshold=20)
        self.rule = DeauthFlood(self.cfg)

    def feed(self, events):
        out = []
        for ev in events:
            out.extend(self.rule.process(ev))
        return out

    def test_retransmissions_of_one_frame_count_once(self):
        evs = [deauth(100, sn=1475, fl=0)]
        evs += [deauth(100 + i * 0.005, sn=1475, fl=RETRY) for i in range(1, 31)]
        self.assertEqual(self.feed(evs), [])

    def test_distinct_frames_still_count(self):
        evs = [deauth(100 + i * 0.1, sn=i, fl=0) for i in range(20)]
        self.assertEqual(len(self.feed(evs)), 1)

    def test_retry_with_a_new_sequence_number_counts(self):
        # Retry bit alone is not a duplicate: the receiver acts on a new sn.
        evs = [deauth(100 + i * 0.1, sn=i, fl=RETRY) for i in range(20)]
        self.assertEqual(len(self.feed(evs)), 1)

    def test_same_sequence_number_without_retry_counts(self):
        # Only a Retry-flagged repeat is a duplicate to the receiver.
        evs = [deauth(100 + i * 0.1, sn=7, fl=0) for i in range(20)]
        self.assertEqual(len(self.feed(evs)), 1)

    def test_duplicate_is_judged_per_source_and_destination(self):
        # Same sn from the AP to two different stations: two distinct frames.
        other = "00:00:5E:00:53:11"
        evs = []
        for i in range(10):
            evs.append(deauth(100 + i * 0.1, sn=i, fl=RETRY))
            evs.append(frame(100 + i * 0.1 + 0.01, type="DEAUTH", ch=6, rssi=-50, src=AP,
                             dst=other, bssid=AP, sn=i, fl=RETRY))
        self.assertEqual(len(self.feed(evs)), 1)

    def test_constant_sequence_retry_flood_counts_once(self):
        # Crafted Retry + constant sn: the victim discards all but the first,
        # so it is not a flood, and the rule counts it once.
        evs = [deauth(100 + i * 0.01, sn=0, fl=RETRY) for i in range(200)]
        self.assertEqual(self.feed(evs), [])
        later = [deauth(101 + i * 0.1, sn=1 + i, fl=0) for i in range(19)]
        self.assertEqual(len(self.feed(later)), 1)

    def test_protected_frames_do_not_count(self):
        evs = [deauth(100 + i * 0.1, sn=i, fl=PROTECTED) for i in range(40)]
        self.assertEqual(self.feed(evs), [])

    def test_protected_frames_leave_the_unprotected_count_alone(self):
        evs = [deauth(100 + i * 0.05, sn=i, fl=PROTECTED) for i in range(30)]
        evs += [deauth(102 + i * 0.1, sn=100 + i, fl=0) for i in range(19)]
        self.assertEqual(self.feed(evs), [])
        self.assertEqual(len(self.feed([deauth(104, sn=200, fl=0)])), 1)

    def test_v1_frames_without_sequence_fields_count_as_before(self):
        self.assertEqual(len(self.feed(deauth(100 + i * 0.1) for i in range(20))), 1)

    def test_simulated_flood_with_retries_still_fires(self):
        evs = sim_events("deauth_flood")
        self.assertTrue(any((e.fc_flags or 0) & RETRY for e in evs),
                        "scenario should carry some Retry-flagged frames")
        self.assertTrue(self.feed(evs))
