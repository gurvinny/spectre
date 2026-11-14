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
    ('malformed-not-counted-per-board',
     'self.malformed_lines[sensor_id] = self.malformed_lines.get(sensor_id, 0) + 1',
     'self.malformed_lines[sensor_id] = 1',
     'test_a_dropped_lifecycle_line_is_logged_once_a_minute_per_board'),
    ('malformed-warning-not-rate-limited',
     '(last is None or t - last >= MALFORMED_WARN_S)', 'True',
     'test_a_dropped_lifecycle_line_is_logged_once_a_minute_per_board'),
    ('malformed-warning-never-repeats',
     '(last is None or t - last >= MALFORMED_WARN_S)', 'last is None',
     'test_a_dropped_lifecycle_line_is_logged_once_a_minute_per_board'),
    ('malformed-warning-for-frame-lines-too',
     """if '"event"' in line and (last""", "if (last",
     'test_a_dropped_lifecycle_line_is_logged_once_a_minute_per_board'),
    ('malformed-warning-rate-shared-across-boards',
     'self._malformed_warned[sensor_id] = t', 'self._malformed_warned = dict.fromkeys(("ttyUSB0", "ttyUSB1"), t)',
     'test_a_dropped_lifecycle_line_is_logged_once_a_minute_per_board'),
]
SURVIVORS = {}
