"""Store queries behind the board panel."""
TARGET = "spectre/store.py"
TESTS = "tests/test_boards.py"

MUTATIONS = [
    ("latest-groups-by-board-only",
     " JOIN (SELECT MAX(id) AS id FROM board_events GROUP BY sensor_id, kind) m",
     " JOIN (SELECT MAX(id) AS id FROM board_events GROUP BY sensor_id) m",
     "test_latest_row_per_board_and_kind"),
    ("latest-takes-oldest",
     " JOIN (SELECT MAX(id) AS id FROM board_events GROUP BY sensor_id, kind) m",
     " JOIN (SELECT MIN(id) AS id FROM board_events GROUP BY sensor_id, kind) m",
     "test_latest_row_per_board_and_kind"),
    ("ack-any-board",
     '"SELECT received_at,payload FROM board_events WHERE sensor_id=?"\n            " AND kind',
     '"SELECT received_at,payload FROM board_events WHERE ?<>\'\'"\n            " AND kind',
     "test_find_cmd_ack_matches_board_id_and_time"),
    ("ack-any-kind",
     " AND kind='cmd_ack' AND received_at>=?",
     " AND received_at>=?",
     "test_find_cmd_ack_matches_board_id_and_time"),
    ("ack-ignores-since",
     " AND kind='cmd_ack' AND received_at>=? AND",
     " AND kind='cmd_ack' AND ?>=0 AND",
     "test_find_cmd_ack_matches_board_id_and_time"),
    ("ack-ignores-id",
     " AND json_extract(payload,'$.id')=?\"",
     " AND ?<>''\"",
     "test_find_cmd_ack_matches_board_id_and_time"),
    ("ack-loses-timestamp",
     '        return dict(json.loads(r["payload"] or "{}"), received_at=r["received_at"])',
     '        return json.loads(r["payload"] or "{}")',
     "test_find_cmd_ack_matches_board_id_and_time"),
]
SURVIVORS = {}
