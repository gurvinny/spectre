"""Board lifecycle events: store.py side."""
TARGET = "spectre/store.py"
TESTS = "tests/test_board_events.py"

MUTATIONS = [
    ('board-events-never-pruned',
     '            self._db.execute("DELETE FROM board_events WHERE received_at < ?", (cutoff,))\n',
     '',
     'test_prune_follows_raw_retention'),
    ('board-events-in-insert-order',
     '" WHERE received_at>=? ORDER BY received_at LIMIT ?"',
     '" WHERE received_at>=? ORDER BY id LIMIT ?"',
     'test_round_trip_in_time_order'),
    ('board-events-since-ignored',
     '" WHERE received_at>=? ORDER BY received_at LIMIT ?"',
     '" WHERE ?<1e18 ORDER BY received_at LIMIT ?"',
     'test_since_filters'),
    ('board-event-payload-dropped',
     'json.dumps(rec.get("payload") or {})',
     '"{}"',
     'test_round_trip_in_time_order'),
]
SURVIVORS = {}
