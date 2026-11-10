"""Firmware v2 ingest: replay parser wiring."""
TARGET = "spectre/sim/replay.py"
TESTS = "tests/test_ingest_v2.py"

MUTATIONS = [
    ('replay-ap-info-unwired',
     'on_ap_info=pipeline.record_ap_info)',
     'on_ap_info=None)',
     'test_replay_routes_ap_info'),
]
SURVIVORS = {}
