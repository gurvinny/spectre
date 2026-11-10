"""Board lifecycle events: generate.py side."""
TARGET = "spectre/sim/generate.py"
TESTS = "tests/test_board_events.py"

MUTATIONS = [
    ('simulator-unwired',
     'default_band=sim.band,\n                             on_lifecycle=pipeline.record_board_event,',
     'default_band=sim.band,',
     'test_simulator_parsers_are_wired'),
]
SURVIVORS = {}
