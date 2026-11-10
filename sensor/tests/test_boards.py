"""Board health summary and gated board control. Author: gurvinny"""
import json
import threading
import time
import unittest

from _support import TempDir

from fastapi.testclient import TestClient

from spectre import boards
from spectre.api import create_app
from spectre.config import Config
from spectre.pipeline import Pipeline
from spectre.sim.generate import TAG, SimSource
from spectre.store import Store

PASSWORD = "correct-horse-battery"

BOOT_V2 = {"chip": "ESP32-C5", "mode": "promiscuous", "band": "5GHz", "channels": "36-165",
           "dwell_ms": 200, "pin": 0, "filter": ["mgmt", "data"], "dedup": 0, "ap_info_s": 300,
           "fw": "spectre-sniffer", "ver": "2.0.0", "elf_sha": "abc123", "reset": "poweron",
           "baud": 460800, "caps": ["he"]}
TELEMETRY = {"uptime_ms": 60000, "rx_total": 1000, "emitted": 950, "drop_queue": 30,
             "drop_short": 15, "drop_dedup": 0, "drop_overflow": 5, "q_hwm": 4096,
             "q_size": 16384, "heap": 150000, "heap_min": 140000, "temp_dc": 415,
             "uart_bps": 23040}


def row(kind, payload, ts, sensor="ttyUSB1", band="5GHz"):
    return {"received_at": ts, "sensor_id": sensor, "band": band, "kind": kind,
            "payload": payload}


class TestControlFlag(unittest.TestCase):

    def test_only_true_enables_control(self):
        self.assertTrue(boards.control_enabled({"SPECTRE_BOARD_CONTROL": "true"}))
        self.assertTrue(boards.control_enabled({"SPECTRE_BOARD_CONTROL": " TRUE "}))
        for value in ("", "false", "0", "yes-please", "1"):
            self.assertFalse(boards.control_enabled({"SPECTRE_BOARD_CONTROL": value}), value)
        self.assertFalse(boards.control_enabled({}))


class TestHealth(unittest.TestCase):

    def test_v2_telemetry_gives_loss_uart_load_and_queue_fill(self):
        h = boards.health(BOOT_V2, TELEMETRY, None)
        # Lost = ring full + line overflow; short and dedup are not losses.
        self.assertEqual(h["lost"], 35)
        self.assertAlmostEqual(h["loss_pct"], 3.5)
        # 23040 B/s x 10 bits on the wire (8N1) over 460800 baud.
        self.assertAlmostEqual(h["uart_load"], 0.5)
        self.assertAlmostEqual(h["queue_fill"], 0.25)
        self.assertAlmostEqual(h["temp_c"], 41.5)
        self.assertEqual(h["heap_min"], 140000)
        self.assertEqual(h["rx_total"], 1000)
        self.assertEqual(h["emitted"], 950)

    def test_newer_sweep_counters_win_over_older_telemetry(self):
        tel = dict(TELEMETRY, rx_total=100, drop_queue=0, drop_overflow=0)
        sweep = dict(TELEMETRY, rx_total=2000, drop_queue=10, drop_overflow=10)
        h = boards.health(BOOT_V2, tel, sweep, sweep_newer=True)
        self.assertEqual(h["rx_total"], 2000)
        self.assertAlmostEqual(h["loss_pct"], 1.0)
        h = boards.health(BOOT_V2, tel, sweep, sweep_newer=False)
        self.assertEqual(h["rx_total"], 100)
        self.assertEqual(h["loss_pct"], 0.0)

    def test_old_firmware_has_emitted_only_and_no_loss(self):
        h = boards.health({"chip": "ESP32-C5", "band": "2.4GHz", "channels": "1-13"},
                          None, {"total_pkts": 4242}, sweep_newer=True)
        self.assertEqual(h["emitted"], 4242)
        self.assertIsNone(h["rx_total"])
        self.assertIsNone(h["loss_pct"])
        self.assertIsNone(h["uart_load"])
        self.assertIsNone(h["temp_c"])

    def test_zero_received_is_no_loss_figure_not_a_division_error(self):
        h = boards.health(BOOT_V2, dict(TELEMETRY, rx_total=0, drop_queue=0,
                                        drop_overflow=0), None)
        self.assertIsNone(h["loss_pct"])

    def test_non_numeric_board_values_are_ignored(self):
        bad = dict(TELEMETRY, rx_total="1000", uart_bps=True, temp_dc=None, q_size=0)
        h = boards.health(dict(BOOT_V2, baud="fast"), bad, None)
        self.assertIsNone(h["rx_total"])
        self.assertIsNone(h["loss_pct"])
        self.assertIsNone(h["uart_load"])
        self.assertIsNone(h["temp_c"])
        self.assertIsNone(h["queue_fill"])


    def test_a_bool_is_not_a_count(self):
        h = boards.health(BOOT_V2, dict(TELEMETRY, uart_bps=True, rx_total=True), None)
        self.assertIsNone(h["uart_load"])
        self.assertIsNone(h["rx_total"])


class TestSummarize(unittest.TestCase):

    def test_summary_carries_firmware_plan_and_last_seen(self):
        latest = {"boot": row("boot", BOOT_V2, 100.0),
                  "telemetry": row("telemetry", TELEMETRY, 160.0)}
        s = boards.summarize("ttyUSB1", latest, controllable=True)
        self.assertEqual(s["sensor_id"], "ttyUSB1")
        self.assertEqual(s["band"], "5GHz")
        self.assertEqual(s["last_seen"], 160.0)
        self.assertTrue(s["controllable"])
        self.assertEqual(s["firmware"]["ver"], "2.0.0")
        self.assertEqual(s["firmware"]["baud"], 460800)
        self.assertEqual(s["firmware"]["booted_at"], 100.0)
        self.assertEqual(s["plan"]["channels"], "36-165")
        self.assertEqual(s["plan"]["dwell_ms"], 200)
        self.assertEqual(s["health"]["uptime_ms"], 60000)
        self.assertAlmostEqual(s["health"]["loss_pct"], 3.5)

    def test_band_comes_from_the_newest_row(self):
        latest = {"boot": row("boot", BOOT_V2, 100.0, band="5GHz"),
                  "cmd_ack": row("cmd_ack", {"ok": True}, 200.0, band="2.4GHz")}
        self.assertEqual(boards.summarize("b", latest, False)["band"], "2.4GHz")

    def test_an_ok_ack_newer_than_boot_is_the_current_plan(self):
        ack = {"cmd": "set", "id": "c1", "ok": True,
               "config": {"band": "5GHz", "channels": "36,40", "dwell_ms": 400, "pin": 0}}
        latest = {"boot": row("boot", BOOT_V2, 100.0), "cmd_ack": row("cmd_ack", ack, 150.0)}
        s = boards.summarize("b", latest, True)
        self.assertEqual(s["plan"]["channels"], "36,40")
        self.assertEqual(s["plan"]["dwell_ms"], 400)
        self.assertEqual(s["last_ack"]["id"], "c1")
        self.assertEqual(s["last_ack"]["received_at"], 150.0)

    def test_a_failed_or_older_ack_leaves_the_boot_plan(self):
        bad = {"cmd": "set", "ok": False, "err": "bad dwell",
               "config": {"channels": "36", "dwell_ms": 1}}
        s = boards.summarize("b", {"boot": row("boot", BOOT_V2, 100.0),
                                   "cmd_ack": row("cmd_ack", bad, 150.0)}, True)
        self.assertEqual(s["plan"]["dwell_ms"], 200)
        ok = dict(bad, ok=True)
        s = boards.summarize("b", {"boot": row("boot", BOOT_V2, 100.0),
                                   "cmd_ack": row("cmd_ack", ok, 90.0)}, True)
        self.assertEqual(s["plan"]["dwell_ms"], 200)

    def test_a_newer_v2_sweep_supplies_the_counters(self):
        tel = dict(TELEMETRY, rx_total=100, drop_queue=0, drop_overflow=0)
        sweep = {"total_pkts": 1900, "sweep_ms": 5000, "rx_total": 2000, "emitted": 1900,
                 "drop_queue": 20, "drop_short": 0, "drop_dedup": 0, "drop_overflow": 0}
        latest = {"boot": row("boot", BOOT_V2, 100.0),
                  "telemetry": row("telemetry", tel, 150.0),
                  "channel_sweep_complete": row("channel_sweep_complete", sweep, 155.0)}
        self.assertEqual(boards.summarize("b", latest, True)["health"]["rx_total"], 2000)
        latest["channel_sweep_complete"] = row("channel_sweep_complete", sweep, 145.0)
        self.assertEqual(boards.summarize("b", latest, True)["health"]["rx_total"], 100)

    def test_a_board_with_no_rows_yet(self):
        s = boards.summarize("ttyUSB0", {}, True)
        self.assertIsNone(s["band"])
        self.assertIsNone(s["last_seen"])
        self.assertIsNone(s["firmware"])
        self.assertIsNone(s["last_cmd"])
        self.assertIsNone(s["health"]["loss_pct"])


class TestCommandValidation(unittest.TestCase):

    def test_known_commands_pass_and_get_an_id(self):
        for name in ("get_config", "set", "reset_config", "reboot"):
            cmd = boards.validate_command({"cmd": name})
            self.assertEqual(cmd["cmd"], name)
            self.assertRegex(cmd["id"], r"^c[0-9a-f]{8}$")
        self.assertNotEqual(boards.validate_command({"cmd": "set"})["id"],
                            boards.validate_command({"cmd": "set"})["id"])

    def test_a_given_id_is_kept_and_other_keys_pass_through(self):
        cmd = boards.validate_command({"cmd": "set", "id": "mine", "dwell_ms": 250})
        self.assertEqual(cmd, {"cmd": "set", "id": "mine", "dwell_ms": 250})

    def test_rejections(self):
        for body in (None, [], "get_config", {}, {"cmd": "erase_flash"}, {"cmd": 3},
                     {"cmd": "set", "id": 7}, {"cmd": "set", "id": ""},
                     {"cmd": "set", "id": "x" * 17}):
            with self.assertRaises(ValueError, msg=repr(body)):
                boards.validate_command(body)


class TestStoreQueries(unittest.TestCase):

    def setUp(self):
        self.tmp = TempDir()
        self.store = Store(self.tmp.file("s.db"))

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_latest_row_per_board_and_kind(self):
        for ts, sensor, kind, n in ((1.0, "a", "telemetry", 1), (2.0, "a", "telemetry", 2),
                                    (3.0, "a", "boot", 3), (4.0, "b", "telemetry", 4),
                                    (5.0, "b", "telemetry", 5)):
            self.store.insert_board_event(row(kind, {"n": n}, ts, sensor=sensor))
        latest = self.store.latest_board_events()
        got = {(r["sensor_id"], r["kind"]): r["payload"]["n"] for r in latest}
        self.assertEqual(got, {("a", "telemetry"): 2, ("a", "boot"): 3, ("b", "telemetry"): 5})

    def test_find_cmd_ack_matches_board_id_and_time(self):
        self.store.insert_board_event(row("cmd_ack", {"id": "c1", "ok": True}, 10.0, sensor="a"))
        self.store.insert_board_event(row("cmd_ack", {"id": "c1", "ok": False}, 20.0, sensor="b"))
        self.store.insert_board_event(row("telemetry", {"id": "c2"}, 30.0, sensor="a"))
        self.assertTrue(self.store.find_cmd_ack("a", "c1", 5.0)["ok"])
        self.assertEqual(self.store.find_cmd_ack("a", "c1", 5.0)["received_at"], 10.0)
        self.assertFalse(self.store.find_cmd_ack("b", "c1", 5.0)["ok"])
        self.assertIsNone(self.store.find_cmd_ack("a", "c1", 11.0))
        self.assertIsNone(self.store.find_cmd_ack("a", "c2", 0.0))
        self.assertIsNone(self.store.find_cmd_ack("a", "nope", 0.0))


class FakeBoard:
    """Records commands; optionally answers each with a cmd_ack row."""

    def __init__(self, store, sensor_id, answer=True, error=None):
        self.store, self.sensor_id, self.answer, self.error = store, sensor_id, answer, error
        self.sent = []

    def send(self, command):
        if self.error is not None:
            raise self.error
        self.sent.append(command)
        if self.answer:
            self.store.insert_board_event(row(
                "cmd_ack", {"cmd": command["cmd"], "id": command["id"], "ok": True,
                            "config": {"dwell_ms": 250}}, time.time(), sensor=self.sensor_id))
        return 42


class BoardApiCase(unittest.TestCase):
    control = True

    def setUp(self):
        self.tmp = TempDir()
        self.store = Store(self.tmp.file("spectre.db"))
        self.cfg = Config(self.store)
        self.pipe = Pipeline(self.store, self.cfg)
        self.board = FakeBoard(self.store, "ttyUSB1")
        self.senders = {"ttyUSB1": self.board.send}
        self.app = create_app(self.store, self.cfg, self.pipe, origins=[],
                              senders=self.senders, board_control=self.control,
                              ack_wait=0.2)
        self.client = TestClient(self.app)
        r = self.client.post("/api/setup", json={"password": PASSWORD})
        self.assertEqual(r.status_code, 200, r.text)

    def tearDown(self):
        self.client.close()
        self.store.close()
        self.tmp.cleanup()

    def cmd_rows(self):
        return [r for r in self.store.board_events() if r["kind"] == "cmd"]

    def post(self, body, board="ttyUSB1"):
        return self.client.post(f"/api/boards/{board}/cmd", json=body)


class TestBoardsRoute(BoardApiCase):

    def test_needs_a_session(self):
        self.client.cookies.clear()
        self.assertEqual(self.client.get("/api/boards").status_code, 401)
        self.assertEqual(self.post({"cmd": "get_config"}).status_code, 401)
        self.assertEqual(self.board.sent, [])

    def test_lists_boards_from_events_and_senders(self):
        self.store.insert_board_event(row("boot", BOOT_V2, 100.0, sensor="ttyUSB9"))
        body = self.client.get("/api/boards").json()
        self.assertTrue(body["control_enabled"])
        by_id = {b["sensor_id"]: b for b in body["boards"]}
        self.assertEqual(sorted(by_id), ["ttyUSB1", "ttyUSB9"])
        self.assertTrue(by_id["ttyUSB1"]["controllable"])
        self.assertIsNone(by_id["ttyUSB1"]["last_seen"])
        self.assertFalse(by_id["ttyUSB9"]["controllable"])
        self.assertEqual(by_id["ttyUSB9"]["firmware"]["ver"], "2.0.0")

    def test_senders_registered_after_startup_are_seen(self):
        self.senders["sim-5GHz"] = self.board.send
        ids = [b["sensor_id"] for b in self.client.get("/api/boards").json()["boards"]]
        self.assertIn("sim-5GHz", ids)


class TestBoardCommand(BoardApiCase):

    def test_command_is_sent_audited_and_acked(self):
        r = self.post({"cmd": "set", "dwell_ms": 250})
        self.assertEqual(r.status_code, 200, r.text)
        body = r.json()
        self.assertEqual(len(self.board.sent), 1)
        sent = self.board.sent[0]
        self.assertEqual(sent["dwell_ms"], 250)
        self.assertEqual(body["id"], sent["id"])
        self.assertEqual(body["sent"], 42)
        self.assertTrue(body["ack"]["ok"])
        self.assertEqual(body["ack"]["id"], sent["id"])
        audit = self.cmd_rows()
        self.assertEqual(len(audit), 1)
        self.assertEqual(audit[0]["sensor_id"], "ttyUSB1")
        self.assertEqual(audit[0]["payload"]["command"], sent)
        self.assertEqual(audit[0]["payload"]["user"], "admin")
        self.assertEqual(audit[0]["payload"]["sent"], 42)
        # The audit row is stamped before the ack arrives, so they sort in order.
        ack_row = [x for x in self.store.board_events() if x["kind"] == "cmd_ack"][0]
        self.assertLessEqual(audit[0]["received_at"], ack_row["received_at"])

    def test_no_ack_in_time_returns_null(self):
        self.board.answer = False
        t0 = time.monotonic()
        body = self.post({"cmd": "get_config"}).json()
        self.assertGreaterEqual(time.monotonic() - t0, 0.2)
        self.assertIsNone(body["ack"])
        self.assertEqual(len(self.cmd_rows()), 1)

    def test_an_older_ack_with_a_reused_id_is_not_this_answer(self):
        self.store.insert_board_event(row("cmd_ack", {"cmd": "get_config", "id": "dup",
                                                      "ok": True}, time.time() - 60))
        self.board.answer = False
        self.assertIsNone(self.post({"cmd": "get_config", "id": "dup"}).json()["ack"])

    def test_unknown_board_is_404_and_not_audited(self):
        self.assertEqual(self.post({"cmd": "get_config"}, board="ttyUSB7").status_code, 404)
        self.assertEqual(self.cmd_rows(), [])

    def test_bad_command_is_400_and_never_sent(self):
        for body in ({"cmd": "erase_flash"}, {"dwell_ms": 3}, {"cmd": "set", "id": 9}):
            self.assertEqual(self.post(body).status_code, 400, body)
        self.assertEqual(self.board.sent, [])
        self.assertEqual(self.cmd_rows(), [])

    def test_send_refusal_is_400_and_audited(self):
        self.board.error = ValueError("command is 300 bytes, limit 254")
        r = self.post({"cmd": "set", "channels": [1]})
        self.assertEqual(r.status_code, 400)
        self.assertIn("254", r.json()["detail"])
        audit = self.cmd_rows()
        self.assertEqual(len(audit), 1)
        self.assertIn("254", audit[0]["payload"]["error"])
        self.assertNotIn("sent", audit[0]["payload"])

    def test_port_failure_is_502_and_audited(self):
        for exc in (TimeoutError("did not drain"), RuntimeError("not open"), OSError(5, "EIO")):
            self.board.error = exc
            self.assertEqual(self.post({"cmd": "get_config"}).status_code, 502, exc)
        self.assertEqual(len(self.cmd_rows()), 3)


class TestControlDisabled(BoardApiCase):
    control = False

    def test_disabled_is_403_nothing_sent_nothing_audited(self):
        r = self.post({"cmd": "get_config"})
        self.assertEqual(r.status_code, 403)
        self.assertIn("SPECTRE_BOARD_CONTROL", r.json()["detail"])
        self.assertEqual(self.board.sent, [])
        self.assertEqual(self.cmd_rows(), [])

    def test_listing_still_works_and_says_disabled(self):
        body = self.client.get("/api/boards").json()
        self.assertFalse(body["control_enabled"])
        self.assertEqual([b["sensor_id"] for b in body["boards"]], ["ttyUSB1"])

    def test_default_reads_the_environment(self):
        from unittest import mock
        with mock.patch.dict("os.environ", {"SPECTRE_BOARD_CONTROL": "true"}):
            app = create_app(self.store, self.cfg, self.pipe, origins=[],
                             senders=self.senders)
        with TestClient(app) as client:
            client.post("/api/login", json={"password": PASSWORD})
            self.assertTrue(client.get("/api/boards").json()["control_enabled"])
        with mock.patch.dict("os.environ", {}, clear=True):
            app = create_app(self.store, self.cfg, self.pipe, origins=[])
        with TestClient(app) as client:
            client.post("/api/login", json={"password": PASSWORD})
            self.assertFalse(client.get("/api/boards").json()["control_enabled"])


class TestSimBoardControl(unittest.TestCase):
    """The API thread and the simulator's event-loop step share one Simulator."""

    def setUp(self):
        self.tmp = TempDir()
        self.store = Store(self.tmp.file("s.db"))
        self.cfg = Config(self.store)
        self.pipe = Pipeline(self.store, self.cfg)
        self.src = SimSource(self.pipe)
        self.src.prime()

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_send_waits_for_the_step_lock(self):
        board = self.src.boards["sim-5GHz"]
        done = threading.Event()
        with self.src.lock:
            t = threading.Thread(target=lambda: (board.send({"cmd": "get_config"}), done.set()))
            t.start()
            self.assertFalse(done.wait(0.2), "send ran while the step held the lock")
        self.assertTrue(done.wait(2.0))
        t.join()

    def test_step_takes_the_lock(self):
        done = threading.Event()
        with self.src.lock:
            t = threading.Thread(target=lambda: (self.src.step(), done.set()))
            t.start()
            self.assertFalse(done.wait(0.2), "step ran while send held the lock")
        self.assertTrue(done.wait(2.0))
        t.join()

    def test_api_round_trip_against_the_simulator(self):
        senders = {sid: b.send for sid, b in self.src.boards.items()}
        app = create_app(self.store, self.cfg, self.pipe, origins=[], senders=senders,
                         board_control=True, ack_wait=1.0)
        with TestClient(app) as client:
            client.post("/api/setup", json={"password": PASSWORD})
            r = client.post("/api/boards/sim-5GHz/cmd",
                            json={"cmd": "set", "id": "t1", "dwell_ms": 400})
            self.assertEqual(r.status_code, 200, r.text)
            ack = r.json()["ack"]
            self.assertTrue(ack["ok"])
            self.assertEqual(ack["config"]["dwell_ms"], 400)
            listed = {b["sensor_id"]: b for b in client.get("/api/boards").json()["boards"]}
            self.assertEqual(listed["sim-5GHz"]["plan"]["dwell_ms"], 400)
            self.assertEqual(listed["sim-2.4GHz"]["plan"]["dwell_ms"], 300)  # untouched
            self.assertEqual(listed["sim-5GHz"]["last_cmd"]["command"]["id"], "t1")
            bad = client.post("/api/boards/sim-5GHz/cmd",
                              json={"cmd": "set", "id": "t2", "dwell_ms": 1}).json()["ack"]
            self.assertFalse(bad["ok"])
            self.assertEqual(bad["err"], "bad dwell")



class TestMainWiring(unittest.TestCase):
    """The entrypoint registers each source's boards as senders."""

    def test_sim_source_boards_are_controllable(self):
        import importlib
        import sys
        from unittest import mock
        tmp = TempDir()
        env = {"SPECTRE_SOURCE": "sim", "SPECTRE_DB": tmp.file("main.db"),
               "SPECTRE_BOARD_CONTROL": "true"}
        try:
            with mock.patch.dict("os.environ", env):
                sys.modules.pop("spectre.main", None)
                main = importlib.import_module("spectre.main")
            with TestClient(main.app) as client:
                client.post("/api/setup", json={"password": PASSWORD})
                listed = client.get("/api/boards").json()
                self.assertTrue(listed["control_enabled"])
                ctl = {b["sensor_id"]: b["controllable"] for b in listed["boards"]}
                self.assertEqual(ctl, {"sim-2.4GHz": True, "sim-5GHz": True})
                r = client.post("/api/boards/sim-2.4GHz/cmd", json={"cmd": "get_config"})
                self.assertEqual(r.status_code, 200, r.text)
                self.assertTrue(r.json()["ack"]["ok"])
        finally:
            sys.modules.pop("spectre.main", None)
            tmp.cleanup()


    def test_open_serial_ports_are_controllable_and_failed_ones_are_not(self):
        import importlib
        import os
        import sys
        import tty
        from unittest import mock
        master, slave = os.openpty()
        tty.setraw(slave)
        name = os.ttyname(slave)
        tmp = TempDir()
        env = {"SPECTRE_SOURCE": "serial", "SPECTRE_DB": tmp.file("main.db"),
               "SERIAL_PORTS": f"{name},{tmp.file('ttyGONE')}", "SERIAL_BAUD": "460800",
               "SPECTRE_BOARD_CONTROL": "true"}

        def board():
            # Answer the first command the way the firmware does.
            buf = b""
            while b"\n" not in buf:
                buf += os.read(master, 512)
            cid = json.loads(buf.split(b"\n")[0])["id"]
            os.write(master, (TAG + json.dumps({"event": "cmd_ack", "cmd": "get_config",
                                                 "id": cid, "ok": True}) + "\n").encode())
        try:
            with mock.patch.dict("os.environ", env):
                sys.modules.pop("spectre.main", None)
                main = importlib.import_module("spectre.main")
            with mock.patch("spectre.reader.fcntl.ioctl"), TestClient(main.app) as client:
                client.post("/api/setup", json={"password": PASSWORD})
                ctl = {b["sensor_id"]: b["controllable"]
                       for b in client.get("/api/boards").json()["boards"]}
                self.assertEqual(ctl, {os.path.basename(name): True})
                t = threading.Thread(target=board, daemon=True)
                t.start()
                r = client.post(f"/api/boards/{os.path.basename(name)}/cmd",
                                json={"cmd": "get_config"})
                t.join(2.0)
                self.assertEqual(r.status_code, 200, r.text)
                self.assertTrue(r.json()["ack"]["ok"])
                self.assertEqual(client.post("/api/boards/ttyGONE/cmd",
                                             json={"cmd": "get_config"}).status_code, 404)
        finally:
            sys.modules.pop("spectre.main", None)
            os.close(master)
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
