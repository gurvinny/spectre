"""Board lifecycle events: parser.py side."""
TARGET = "spectre/parser.py"
TESTS = "tests/test_board_events.py"

MUTATIONS = [
    ('lifecycle-callback-never-called',
     'sink = self.on_lifecycle\n',
     'sink = None\n',
     'test_each_lifecycle_line_is_handed_over'),
    ('event-key-leaks-into-payload',
     'if k != "event"}',
     '}',
     'test_record_carries_board_band_and_payload'),
    ('record-band-not-latched',
     '"band": self.band, "kind": kind,',
     '"band": "unknown", "kind": kind,',
     'test_record_carries_board_band_and_payload'),
]
SURVIVORS = {}
