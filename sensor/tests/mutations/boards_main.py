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
     "                senders.add_reader(r)\n",
     "                senders[r.sensor_id] = r.send\n",
     "test_open_serial_ports_are_controllable_and_failed_ones_are_not"),
    ("serial-unregistered",
     "                senders.add_reader(r)\n",
     "",
     "test_open_serial_ports_are_controllable_and_failed_ones_are_not"),
    ("closed-reader-controllable", "        if r is not None and r.is_open:\n            return r.send",
     "        if r is not None:\n            return r.send",
     "test_a_reader_is_controllable_only_while_its_port_is_open"),
    ("closed-reader-listed", "live = [k for k, r in self._readers.items() if r.is_open]",
     "live = list(self._readers)",
     "test_a_reader_is_controllable_only_while_its_port_is_open"),
]
SURVIVORS = {}
