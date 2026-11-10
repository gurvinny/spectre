"""Firmware v2 ingest: simulator parser wiring."""
TARGET = "spectre/sim/generate.py"
TESTS = "tests/test_ingest_v2.py"

MUTATIONS = [
    ('simulator-ap-info-unwired',
     'on_ap_info=pipeline.record_ap_info)',
     'on_ap_info=None)',
     'test_simulator_parsers_route_ap_info'),
]
SURVIVORS = {}
