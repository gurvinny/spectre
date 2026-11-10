"""Firmware v2 ingest: pipeline.py side."""
TARGET = "spectre/pipeline.py"
TESTS = "tests/test_ingest_v2.py"

MUTATIONS = [
    ('ap-info-stored-as-board-event',
     '        self.store.insert_ap_info(rec)\n',
     '        self.store.insert_board_event(rec)\n',
     'test_pipeline_records_ap_info'),
]
SURVIVORS = {}
