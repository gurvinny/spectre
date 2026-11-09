"""Board lifecycle events: reader.py side."""
TARGET = "spectre/reader.py"
TESTS = "tests/test_board_events.py"

MUTATIONS = [
    ('serial-reader-unwired',
     'Parser(self.sensor_id, on_lifecycle=pipeline.record_board_event)',
     'Parser(self.sensor_id)',
     'test_serial_reader_stores_lifecycle_lines'),
]
SURVIVORS = {}
