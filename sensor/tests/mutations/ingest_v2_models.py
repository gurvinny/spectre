"""Firmware v2 ingest: models.py row order (Event.to_row vs FRAME_COLUMNS)."""
TARGET = "spectre/models.py"
TESTS = "tests/test_ingest_v2.py"

MUTATIONS = [
    ('row-tuple-misordered',
     'self.ts_us, self.sn, self.fc_flags',
     'self.sn, self.ts_us, self.fc_flags',
     'test_row_tuple_lines_up_with_the_insert'),
    ('column-list-misordered',
     '"rate", "ts_us", "sn",',
     '"rate", "sn", "ts_us",',
     'test_v2_fields_round_trip'),
]
SURVIVORS = {}
