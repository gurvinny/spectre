"""Pipeline: the event loop never takes the store's write lock (#124)."""
TARGET = "spectre/pipeline.py"
TESTS = "tests/test_store_concurrency.py"

MUTATIONS = [
    ("threat-written-on-the-loop",
     "self._threat_buffer.append((t, sent))",
     "self.store.insert_threat(t, wazuh_sent=sent)",
     "test_ingest_and_lifecycle_lines_return_while_the_lock_is_held"),
    ("board-event-written-on-the-loop",
     "        self._board_buffer.append(rec)\n", "        self.store.insert_board_event(rec)\n",
     "test_ingest_and_lifecycle_lines_return_while_the_lock_is_held"),
    ("flush-on-the-loop",
     "await self._off_loop(self._write_pending, pending)",
     "self._write_pending(pending)",
     "test_background_writes_do_not_block_the_event_loop"),
    ("inventory-on-the-loop",
     "await self._off_loop(self._write_inventory, devices, aps)",
     "self._write_inventory(devices, aps)",
     "test_background_writes_do_not_block_the_event_loop"),
    ("prune-on-the-loop",
     "report = await self._off_loop(\n                    self.store.prune,",
     "report = (lambda f, *a: f(*a))(\n                    self.store.prune,",
     "test_background_writes_do_not_block_the_event_loop"),
    ("flush-keeps-the-buffer",
     "        self._frame_buffer, self._board_buffer = [], []\n", "",
     "test_flush_writes_everything_in_arrival_order"),
    ("stop-ignores-writes-in-flight",
     "        if self._in_flight:\n            await asyncio.gather(*self._in_flight, return_exceptions=True)\n", "",
     "test_stop_waits_for_a_write_already_in_flight"),
    ("write-not-shielded",
     "        return await asyncio.shield(fut)\n", "        return await fut\n",
     "test_stop_waits_for_a_write_already_in_flight"),
]
