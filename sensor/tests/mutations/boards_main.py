"""Entrypoint registers each source's boards for control."""
TARGET = "spectre/main.py"
TESTS = "tests/test_boards.py"

MUTATIONS = [
    ("sim-boards-unregistered",
     '            senders.update({sid: b.send for sid, b in state["source_obj"].boards.items()})\n',
     "",
     "test_sim_source_boards_are_controllable"),
    ("senders-not-passed",
     "    app = create_app(store, config, pipeline, senders=senders)",
     "    app = create_app(store, config, pipeline)",
     "test_sim_source_boards_are_controllable"),
    ("failed-port-registered",
     '                    log.error("could not open %s: %s", r.path, exc)\n                    continue\n',
     '                    log.error("could not open %s: %s", r.path, exc)\n',
     "test_open_serial_ports_are_controllable_and_failed_ones_are_not"),
    ("serial-unregistered",
     "                senders[r.sensor_id] = r.send\n",
     "",
     "test_open_serial_ports_are_controllable_and_failed_ones_are_not"),
]
SURVIVORS = {}
