"""Store: reads never wait for the write lock; big writes release it (#124)."""
TARGET = "spectre/store.py"
TESTS = "tests/test_store_concurrency.py"

MUTATIONS = [
    ("reads-take-the-write-lock",
     '        db = getattr(self._local, "db", None)\n',
     '        with self._lock:\n            pass\n        db = getattr(self._local, "db", None)\n',
     "test_api_reads_complete_while_a_write_holds_the_lock"),
    ("reader-can-write",
     '+ "?mode=ro"', '+ ""',
     "test_reader_connections_cannot_write"),
    ("prune-stops-after-one-chunk",
     "            if n < PRUNE_CHUNK:\n", "            if True:\n",
     "test_old_frames_are_deleted_in_chunks"),
    ("prune-in-one-lock-hold",
     "                    (cutoff, PRUNE_CHUNK)).rowcount", "                    (cutoff, -1)).rowcount",
     "test_old_frames_are_deleted_in_chunks"),
    ("upsert-in-one-lock-hold",
     "for i in range(0, len(devices), UPSERT_CHUNK):",
     "for i in range(0, len(devices), len(devices)):",
     "test_inventory_upserts_commit_in_chunks"),
    ("batch-drops-threats",
     "                self._insert_threat(t, sent)\n", "                pass\n",
     "test_ingest_and_lifecycle_lines_return_while_the_lock_is_held"),
    ("dead-readers-kept",
     "                self._readers = [r for r in self._readers if r[0].is_alive()]\n", "",
     "test_dead_threads_readers_do_not_pile_up"),
]
