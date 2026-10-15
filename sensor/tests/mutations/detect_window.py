"""SlidingWindow, shared by deauth, probe flood and the fps counters."""
TARGET = "spectre/detect/__init__.py"
TESTS = "tests/test_detect_deauth.py"

MUTATIONS = [
    ("window-never-evicts",
     "while self._ts and self._ts[0] < cutoff:", "while False:",
     "test_frames_older_than_the_window_are_evicted"),
    ("edge-frame-evicted",
     "while self._ts and self._ts[0] < cutoff:",
     "while self._ts and self._ts[0] <= cutoff:",
     "test_frame_exactly_at_the_window_edge_still_counts"),
]
SURVIVORS = {}
