"""Firmware v2 ingest: pipeline.py side."""
TARGET = "spectre/pipeline.py"
TESTS = "tests/test_ingest_v2.py"

MUTATIONS = [
    ('ap-info-stored-as-board-event',
     '        self._ap_info_buffer.append(rec)\n',
     '        self._board_buffer.append(rec)\n',
     'test_pipeline_records_ap_info'),
    ('ap-info-never-reaches-detection',
     '        self.engine.set_ap_info(rec)\n',
     '',
     'test_pipeline_ap_info_reaches_the_detection_engine'),
]
SURVIVORS = {}
