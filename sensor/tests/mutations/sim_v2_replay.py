"""Simulator v2: replay's standalone lifecycle output."""
TARGET = "spectre/sim/replay.py"
TESTS = "tests/test_sim_v2.py"

MUTATIONS = [
    ('events-flag-prints-nothing',
     'parser = Parser("replay", on_lifecycle=show)',
     'parser = Parser("replay")',
     'test_standalone_replay_can_print_lifecycle_records'),
    ('events-always-printed',
     'if args.events else None',
     'if True else None',
     'test_standalone_replay_prints_frames_only_by_default'),
]
SURVIVORS = {}
