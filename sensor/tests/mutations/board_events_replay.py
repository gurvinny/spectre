"""Board lifecycle events: replay.py side."""
TARGET = "spectre/sim/replay.py"
TESTS = "tests/test_board_events.py"

MUTATIONS = [
    ('replay-unwired',
     'Parser("replay", on_lifecycle=pipeline.record_board_event,',
     'Parser("replay",',
     'test_replay_stores_lifecycle_lines'),
]
SURVIVORS = {}
