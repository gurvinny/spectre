"""Deauth flood: the rule SECURITY.md and the README lead with."""
TARGET = "spectre/detect/deauth_flood.py"
TESTS = "tests/test_detect_deauth.py"

MUTATIONS = [
    ("disassoc-stops-counting",
     'if ev.frame_type not in ("DEAUTH", "DISASSOC"):',
     'if ev.frame_type not in ("DEAUTH",):',
     "test_disassoc_counts_toward_the_same_window"),
    ("off-by-one-threshold",
     "if count < threshold:", "if count <= threshold:",
     "test_threshold_frame_raises_one_high_threat_with_the_count"),
    ("all-bssids-share-one-window",
     'key = ev.bssid or ev.src or "unknown"', 'key = "unknown"',
     "test_bssids_are_counted_independently"),
    ("severity-downgraded",
     'severity="high",', 'severity="medium",',
     "test_threshold_frame_raises_one_high_threat_with_the_count"),
    ("threshold-ignores-config",
     'threshold = int(self.cfg("deauth_threshold", 20))', "threshold = 20",
     "test_threshold_is_read_live"),
    ("rate-uses-wrong-divisor",
     "rate = round(count / window_s, 1)", "rate = round(count / 5, 1)",
     "test_threshold_frame_raises_one_high_threat_with_the_count"),
    ("victim-dropped-from-detail",
     '"target_dst": ev.dst,', '"target_dst": None,',
     "test_threshold_frame_raises_one_high_threat_with_the_count"),
]
SURVIVORS = {}
