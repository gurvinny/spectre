"""Beacon / probe flood."""
TARGET = "spectre/detect/flood.py"
TESTS = "tests/test_detect_flood.py"

MUTATIONS = [
    ("beacons-counted-not-distinct",
     "return len({b for _, b in ring})",
     "return len(ring)",
     "test_repeat_beacons_from_one_ap_do_not_count_as_distinct"),
    ("beacon-ring-never-evicts",
     "while ring and ring[0][0] < cutoff:", "while False:",
     "test_beacons_outside_the_window_are_forgotten"),
    ("beacon-threshold-off-by-one",
     "if distinct >= threshold and", "if distinct > threshold and",
     "test_40th_distinct_ap_raises_a_medium_beacon_flood"),
    ("beacon-cooldown-ignored",
     "if distinct >= threshold and ev.received_at - last_alert > cooldown:",
     "if distinct >= threshold:",
     "test_beacon_alert_respects_the_cooldown"),
    ("beacon-ring-shared-across-bands",
     "ring = self._beacon_rings.setdefault(band, deque())",
     "ring = self._beacon_rings.setdefault(None, deque())",
     "test_two_bands_under_threshold_each_do_not_add_up"),
    ("beacon-cooldown-shared-across-bands",
     "self._last_beacon_alert[ev.band] = ev.received_at",
     "self._last_beacon_alert = {b: ev.received_at for b in (\"2.4GHz\", \"5GHz\", None)}",
     "test_beacon_cooldown_is_per_band"),
    ("probe-threshold-off-by-one",
     "if count >= threshold and", "if count > threshold and",
     "test_120th_probe_raises_a_probe_flood"),
    ("probe-cooldown-ignored",
     "and ev.received_at - self._last_probe_alert > cooldown:", ":",
     "test_probe_alert_respects_the_cooldown"),
    ("probe-window-not-retuned",
     "if self._probe_win.window != window_s:", "if False:",
     "test_window_change_is_picked_up_live"),
]
SURVIVORS = {}
