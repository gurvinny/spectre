"""Board lifecycle events: pipeline.py side."""
TARGET = "spectre/pipeline.py"
TESTS = "tests/test_board_events.py"

MUTATIONS = [
    ('record-board-event-noop',
     '        self.store.insert_board_event(rec)\n',
     '        pass\n',
     'test_pipeline_records_board_events'),
]
SURVIVORS = {}
