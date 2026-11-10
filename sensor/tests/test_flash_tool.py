"""Tests for ``firmware/flash.py``, the scripted flash-and-verify tool.

The tool is only worth running if it refuses a board that came up wrong. So
most of these drive the real session code against a fake board that speaks
the firmware's line contract, and make that board misbehave one way at a time:
silent, rejecting, wrong version, wrong band, wrong plan, no boot line.

Author: gurvinny
Project: SPECTRE
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import struct
import sys
import tempfile
import termios
import unittest
from pathlib import Path
from unittest import mock

_PATH = Path(__file__).resolve().parents[2] / "firmware" / "flash.py"
_spec = importlib.util.spec_from_file_location("flash_tool", _PATH)
flash = importlib.util.module_from_spec(_spec)
sys.modules["flash_tool"] = flash
_spec.loader.exec_module(flash)

PREFIX = "<190>ESP32C5 wifi_sniffer: "
ELF = bytes(range(0xA0, 0xC0))           # a made-up 32-byte ELF sha256, hex letters
ELF_HEX = ELF.hex()

DEFAULTS = {
    "2.4GHz": {"band": "2.4GHz", "channels": "1-13", "dwell_ms": 300, "pin": 0,
               "filter": ["mgmt", "data"], "dedup": 0, "ap_info_s": 300},
    "5GHz": {"band": "5GHz", "channels": "36-165", "dwell_ms": 200, "pin": 0,
             "filter": ["mgmt", "data"], "dedup": 0, "ap_info_s": 300},
}


def app_image(version="2.0.0", project="spectre-sniffer", elf=ELF, idf="v5.5.4",
              magic=0xABCD5432, first=0xE9) -> bytes:
    """A minimal app image: header, segment header, esp_app_desc_t, padding."""
    def fixed(s, n):
        return s.encode().ljust(n, b"\0")
    desc = (struct.pack("<II", magic, 0) + b"\0" * 8 + fixed(version, 32)
            + fixed(project, 32) + fixed("12:00:00", 16) + fixed("Jan  1 2026", 16)
            + fixed(idf, 32) + elf)
    header = bytes([first, 3]) + b"\0" * 22
    return header + b"\0" * 8 + desc + b"\0" * 80


def boot_line(band="2.4GHz", ver="2.0.0", sha=ELF_HEX[:9], baud=460800,
              fw="spectre-sniffer", plan=None) -> dict:
    return {"event": "boot", "chip": "ESP32-C5", "mode": "promiscuous",
            **(plan or DEFAULTS[band]), "fw": fw, "ver": ver, "elf_sha": sha,
            "reset": "software", "baud": baud, "caps": ["counters", "cmd"]}


class FakeBoard:
    """Speaks the firmware's command contract over a line queue.

    Misbehaviours are switched on one at a time through keyword arguments.
    """

    def __init__(self, band="2.4GHz", plan=None, ver="2.0.0", sha=ELF_HEX[:9],
                 silent=False, reject=None, ack_band=None, no_boot=False,
                 no_started=False, boot_overrides=None, plan_missing=False):
        self.plan = dict(plan or {**DEFAULTS[band], "channels": "1,6,11"})
        self.ver, self.sha = ver, sha
        self.silent, self.reject, self.ack_band = silent, reject, ack_band
        self.no_boot, self.no_started = no_boot, no_started
        self.boot_overrides = boot_overrides or {}
        self.plan_missing = plan_missing
        self.queue: list[str] = []
        self.sent: list[dict] = []
        self.now = 0.0

    def clock(self):
        return self.now

    def emit(self, obj):
        self.queue.append(PREFIX + json.dumps(obj, separators=(",", ":")))

    def frame(self):
        self.emit({"seq": 1, "uptime_ms": 5, "ch": 1, "rssi": -50, "type": "BEACON"})

    def readline(self, timeout):
        if self.queue:
            return self.queue.pop(0)
        self.now += timeout
        return None

    def send(self, obj):
        self.sent.append(obj)
        if self.silent:
            return
        name = obj["cmd"]
        ack = {"event": "cmd_ack", "cmd": name, "id": obj.get("id"), "ok": True}
        if self.reject == name:
            ack.update(ok=False, err="bad band")
        elif name == "set" and "band" in obj:
            if obj["band"] != self.plan["band"]:
                self.plan = dict(DEFAULTS[obj["band"]])
        elif name == "reset_config":
            self.plan = dict(DEFAULTS[self.plan["band"]])
        config = dict(self.plan)
        if self.ack_band:
            config["band"] = self.ack_band
        if not (self.plan_missing and name == "reset_config"):
            ack["config"] = config
        self.frame()
        # an ack for someone else's command must not be taken for ours
        self.emit({"event": "cmd_ack", "cmd": name, "id": "other", "ok": True,
                   "config": {"band": "nope"}})
        self.emit(ack)
        if name == "reboot" and ack["ok"]:
            self.frame()
            if not self.no_boot:
                line = boot_line(self.plan["band"], self.ver, self.sha, plan=self.plan)
                line.update(self.boot_overrides)
                self.emit(line)
            if not self.no_started:
                self.emit({"event": "sniffer_started", "ch": 1})


def desc(**kw):
    return flash.read_app_desc(app_image(**kw))


class AppDescTests(unittest.TestCase):
    def test_reads_version_project_idf_and_full_elf_sha(self):
        d = desc()
        self.assertEqual((d.version, d.project, d.idf), ("2.0.0", "spectre-sniffer", "v5.5.4"))
        self.assertEqual(d.elf_sha256, ELF_HEX)

    def test_rejects_a_file_that_is_not_an_app_image(self):
        with self.assertRaisesRegex(flash.FlashError, "not an ESP app image"):
            flash.read_app_desc(app_image(first=0x7F))
        with self.assertRaisesRegex(flash.FlashError, "not an ESP app image"):
            flash.read_app_desc(app_image()[:100])

    def test_rejects_an_image_without_a_descriptor(self):
        with self.assertRaisesRegex(flash.FlashError, "descriptor"):
            flash.read_app_desc(app_image(magic=0x12345678))


class FlashArgsTests(unittest.TestCase):
    IDF = ("--flash_mode dio --flash_freq 80m --flash_size 4MB\n"
           "0x2000 bootloader/bootloader.bin\n"
           "0x10000 spectre-sniffer.bin\n"
           "0x8000 partition_table/partition-table.bin\n")

    def test_options_use_esptool5_dashes_and_parts_keep_order(self):
        opts, parts = flash.parse_flash_args(self.IDF)
        self.assertEqual(opts, ["--flash-mode", "dio", "--flash-freq", "80m",
                                "--flash-size", "4MB"])
        self.assertEqual(parts, [("0x2000", "bootloader/bootloader.bin"),
                                 ("0x10000", "spectre-sniffer.bin"),
                                 ("0x8000", "partition_table/partition-table.bin")])

    def test_values_keep_their_underscores(self):
        opts, _ = flash.parse_flash_args("--flash_mode keep_me\n0x0 a.bin\n")
        self.assertEqual(opts, ["--flash-mode", "keep_me"])

    def test_unknown_lines_and_empty_lists_fail(self):
        with self.assertRaisesRegex(flash.FlashError, "unexpected"):
            flash.parse_flash_args("0x2000\n")
        with self.assertRaisesRegex(flash.FlashError, "no images"):
            flash.parse_flash_args("--flash_mode dio\n\n")


class LoadImageTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        (self.dir / "bootloader").mkdir()
        (self.dir / "partition_table").mkdir()
        (self.dir / "bootloader" / "bootloader.bin").write_bytes(b"boot")
        (self.dir / "partition_table" / "partition-table.bin").write_bytes(b"pt")
        (self.dir / "spectre-sniffer.bin").write_bytes(app_image())
        (self.dir / "flash_args").write_text(FlashArgsTests.IDF)

    def tearDown(self):
        self._tmp.cleanup()

    def sums(self, **override):
        lines = []
        for rel in ("spectre-sniffer.bin", "bootloader/bootloader.bin",
                    "partition_table/partition-table.bin"):
            digest = override.get(rel) or hashlib.sha256((self.dir / rel).read_bytes()).hexdigest()
            lines.append(f"{digest}  {rel}")
        (self.dir / "SHA256SUMS").write_text("\n".join(lines) + "\n")

    def test_loads_descriptor_and_hashes_every_part(self):
        img = flash.load_image(self.dir)
        self.assertEqual(img.desc.version, "2.0.0")
        self.assertEqual(img.sha256["bootloader/bootloader.bin"],
                         hashlib.sha256(b"boot").hexdigest())
        self.assertEqual(len(img.sha256), 3)

    def test_matching_sha256sums_pass(self):
        self.sums()
        self.assertEqual(flash.load_image(self.dir).desc.version, "2.0.0")

    def test_a_tampered_part_fails_sha256sums(self):
        self.sums(**{"partition_table/partition-table.bin": "0" * 64})
        with self.assertRaisesRegex(flash.FlashError, "partition-table.bin does not match"):
            flash.load_image(self.dir)

    def test_binary_mode_sums_are_checked_too(self):
        (self.dir / "SHA256SUMS").write_text(f"{'0' * 64} *spectre-sniffer.bin\n")
        with self.assertRaisesRegex(flash.FlashError, "spectre-sniffer.bin does not match"):
            flash.load_image(self.dir)

    def test_missing_build_or_part_fails(self):
        with self.assertRaisesRegex(flash.FlashError, "build the firmware"):
            flash.load_image(self.dir / "nope")
        (self.dir / "bootloader" / "bootloader.bin").unlink()
        with self.assertRaisesRegex(flash.FlashError, "bootloader.bin not found"):
            flash.load_image(self.dir)

    def test_flash_args_without_the_app_fails(self):
        (self.dir / "flash_args").write_text("0x2000 bootloader/bootloader.bin\n")
        with self.assertRaisesRegex(flash.FlashError, "does not list"):
            flash.load_image(self.dir)

    def test_another_projects_image_is_refused(self):
        (self.dir / "spectre-sniffer.bin").write_bytes(app_image(project="hello_world"))
        with self.assertRaisesRegex(flash.FlashError, "hello_world"):
            flash.load_image(self.dir)

    def test_stub_follows_flasher_args_json(self):
        self.assertTrue(flash.load_image(self.dir).stub)
        self.assertNotIn("--no-stub", flash.esptool_argv("p", flash.load_image(self.dir)))
        extra = self.dir / "flasher_args.json"
        extra.write_text(json.dumps({"extra_esptool_args": {"chip": "esp32c5", "stub": False}}))
        argv = flash.esptool_argv("p", flash.load_image(self.dir))
        self.assertLess(argv.index("--no-stub"), argv.index("write-flash"))
        extra.write_text(json.dumps({"extra_esptool_args": {"chip": "esp32c5", "stub": True}}))
        self.assertNotIn("--no-stub", flash.esptool_argv("p", flash.load_image(self.dir)))

    def test_esptool_command_line(self):
        img = flash.load_image(self.dir)
        argv = flash.esptool_argv("/dev/ttyUSB1", img)
        self.assertEqual(argv[:4], ["uvx", "--from", "esptool==5.6.0", "esptool"])
        self.assertEqual(argv[argv.index("--chip") + 1], "esp32c5")
        self.assertEqual(argv[argv.index("--port") + 1], "/dev/ttyUSB1")
        self.assertEqual(argv[argv.index("--baud") + 1], "460800")
        self.assertEqual(argv[argv.index("--before") + 1], "default-reset")
        self.assertEqual(argv[argv.index("--after") + 1], "hard-reset")
        tail = argv[argv.index("write-flash") + 1:]
        self.assertEqual(tail[:6], ["--flash-mode", "dio", "--flash-freq", "80m",
                                    "--flash-size", "4MB"])
        self.assertEqual(tail[6:], ["0x2000", str(self.dir / "bootloader/bootloader.bin"),
                                    "0x10000", str(self.dir / "spectre-sniffer.bin"),
                                    "0x8000",
                                    str(self.dir / "partition_table/partition-table.bin")])


class ParseLineTests(unittest.TestCase):
    def test_event_and_frame_lines_parse(self):
        self.assertEqual(flash.parse_line(PREFIX + '{"event":"boot","ver":"2.0.0"}\r'),
                         {"event": "boot", "ver": "2.0.0"})
        self.assertEqual(flash.parse_line(PREFIX + '{"seq":3}')["seq"], 3)

    def test_noise_is_ignored(self):
        for text in ("", "ESP-ROM:esp32c5-20240829", PREFIX + "{broken",
                     PREFIX + "[1,2]", '{"event":"boot"}'):
            self.assertIsNone(flash.parse_line(text), text)


class CheckBootTests(unittest.TestCase):
    def setUp(self):
        self.d = desc()
        self.plan = DEFAULTS["5GHz"]

    def check(self, **boot):
        return flash.check_boot({**boot_line("5GHz"), **boot}, self.d, "5GHz", self.plan)

    def test_matching_boot_passes(self):
        self.assertEqual(self.check(), [])

    def test_full_or_uppercase_sha_prefix_passes(self):
        self.assertEqual(self.check(elf_sha=ELF_HEX[:16]), [])
        self.assertEqual(self.check(elf_sha=ELF_HEX[:9].upper()), [])

    def test_each_mismatch_is_reported(self):
        cases = {"fw": ("fw", "wifi_sniffer"), "version": ("ver", "1.9.0"),
                 "band": ("band", "2.4GHz"), "baud": ("baud", 115200),
                 "dwell_ms": ("dwell_ms", 300), "channels": ("channels", "36,40"),
                 "not the flashed image": ("elf_sha", "deadbeef0")}
        for word, (key, value) in cases.items():
            problems = self.check(**{key: value})
            self.assertEqual(len(problems), 1, (key, problems))
            self.assertIn(word, problems[0])

    def test_a_near_miss_sha_is_not_the_image(self):
        near = ELF_HEX[:8] + ("0" if ELF_HEX[8] != "0" else "1")
        self.assertIn("not the flashed image", self.check(elf_sha=near)[0])

    def test_short_or_missing_sha_proves_nothing(self):
        self.assertIn("too short", self.check(elf_sha=ELF_HEX[:7])[0])
        boot = boot_line("5GHz")
        del boot["elf_sha"]
        self.assertIn("too short", flash.check_boot(boot, self.d, "5GHz", self.plan)[0])

    def test_old_firmware_boot_line_fails_everything_it_lacks(self):
        old = {"event": "boot", "chip": "ESP32-C5", "band": "5GHz", "channels": "36-165"}
        problems = flash.check_boot(old, self.d, "5GHz", self.plan)
        self.assertGreaterEqual(len(problems), 5)


class SessionTests(unittest.TestCase):
    def run_board(self, board, band="2.4GHz", **kw):
        return flash.configure_and_verify(board, desc(), band, **kw)

    def test_good_board_is_set_reset_rebooted_and_verified(self):
        board = FakeBoard()
        result = self.run_board(board)
        self.assertEqual([c["cmd"] for c in board.sent], ["set", "reset_config", "reboot"])
        self.assertEqual(board.sent[0]["band"], "2.4GHz")
        self.assertEqual(len({c["id"] for c in board.sent}), 3)
        self.assertEqual(result["plan"], DEFAULTS["2.4GHz"])
        self.assertEqual(result["band"], "2.4GHz")

    def test_band_switch_to_5ghz(self):
        result = self.run_board(FakeBoard(), band="5GHz")
        self.assertEqual(result["plan"]["channels"], "36-165")

    def test_keep_config_skips_the_reset(self):
        board = FakeBoard()
        result = self.run_board(board, keep_config=True)
        self.assertEqual([c["cmd"] for c in board.sent], ["set", "reboot"])
        self.assertEqual(result["plan"]["channels"], "1,6,11")

    def test_settle_window_passes_before_the_first_command(self):
        board = FakeBoard()
        self.run_board(board, settle=1.5)
        self.assertGreaterEqual(board.now, 1.5)

    def test_unknown_band_is_refused_before_talking(self):
        board = FakeBoard()
        with self.assertRaisesRegex(flash.FlashError, "band must be"):
            self.run_board(board, band="6GHz")
        self.assertEqual(board.sent, [])

    def test_failures(self):
        cases = [
            ("no ack for set", dict(silent=True)),
            ("set rejected", dict(reject="set")),
            ("reset_config rejected", dict(reject="reset_config")),
            ("reboot rejected", dict(reject="reboot")),
            ("acknowledged band", dict(ack_band="5GHz")),
            ("did not report its plan", dict(plan_missing=True)),
            ("no boot line", dict(no_boot=True)),
            ("sniffer never started", dict(no_started=True)),
            ("version is '1.9.0'", dict(ver="1.9.0")),
            ("not the flashed image", dict(sha="ffffffffff")),
            ("band is '5GHz'", dict(boot_overrides={"band": "5GHz"})),
            ("dwell_ms is 250", dict(boot_overrides={"dwell_ms": 250})),
        ]
        for message, kw in cases:
            with self.subTest(message):
                with self.assertRaises(flash.FlashError) as ctx:
                    self.run_board(FakeBoard(**kw))
                self.assertIn(message, str(ctx.exception))

    def test_a_silent_board_times_out_instead_of_hanging(self):
        board = FakeBoard(silent=True)
        with self.assertRaises(flash.FlashError):
            self.run_board(board, settle=0.5)
        self.assertAlmostEqual(board.now, 0.5 + flash.ACK_TIMEOUT_S)


class PortTests(unittest.TestCase):
    def setUp(self):
        self.master, self.slave = os.openpty()

    def tearDown(self):
        for fd in (self.master, self.slave):
            try:
                os.close(fd)
            except OSError:
                pass

    def test_open_port_is_raw_460800_and_clears_dtr_rts_twice(self):
        with mock.patch.object(flash.fcntl, "ioctl") as ioctl:
            fd = flash.open_port(os.ttyname(self.slave))
        try:
            attrs = termios.tcgetattr(fd)
            self.assertEqual((attrs[4], attrs[5]), (termios.B460800, termios.B460800))
            self.assertEqual(attrs[3] & termios.ICANON, 0)
            self.assertTrue(os.get_blocking(fd) is False)
            bits = struct.pack("I", 0x002 | 0x004)
            self.assertEqual([c.args[1:] for c in ioctl.call_args_list],
                             [(0x5417, bits), (0x5417, bits)])
        finally:
            os.close(fd)

    def test_open_port_closes_the_fd_when_setup_fails(self):
        before = set(os.listdir("/proc/self/fd"))
        with mock.patch.object(flash.fcntl, "ioctl", side_effect=OSError("no modem lines")):
            with self.assertRaises(OSError):
                flash.open_port(os.ttyname(self.slave))
        self.assertEqual(set(os.listdir("/proc/self/fd")), before)

    def test_link_reads_lines_across_chunks_and_times_out(self):
        import tty
        tty.setraw(self.slave)
        link = flash.SerialLink(self.slave)
        os.write(self.master, b'first\r\nsec')
        self.assertEqual(link.readline(1.0), "first")
        self.assertIsNone(link.readline(0.05))
        os.write(self.master, b"ond\nthird\n")
        self.assertEqual(link.readline(1.0), "second")
        self.assertEqual(link.readline(1.0), "third")

    def test_link_sends_compact_json_lines(self):
        import tty
        tty.setraw(self.slave)
        link = flash.SerialLink(self.slave)
        link.send({"cmd": "set", "band": "5GHz", "id": "x"})
        self.assertEqual(os.read(self.master, 100), b'{"cmd":"set","band":"5GHz","id":"x"}\n')


class MainTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        build = Path(self._tmp.name)
        (build / "spectre-sniffer.bin").write_bytes(app_image())
        (build / "flash_args").write_text("--flash_mode dio\n0x10000 spectre-sniffer.bin\n")
        self.build = build
        self.board = FakeBoard()
        patches = [
            mock.patch.object(flash, "open_port", return_value=99),
            mock.patch.object(flash, "SerialLink", return_value=self.board),
            mock.patch.object(flash.os, "close"),
            mock.patch.object(flash.subprocess, "run"),
        ]
        self.open_port, _, self.close, self.esptool = [p.start() for p in patches]
        for p in patches:
            self.addCleanup(p.stop)
        self.addCleanup(self._tmp.cleanup)

    def main(self, *extra):
        args = ["--port", "/dev/ttyUSB0", "--band", "2.4GHz", "--build", str(self.build), *extra]
        with mock.patch("sys.stdout") as out, mock.patch("sys.stderr") as err:
            code = flash.main(args)
        printed = "".join(c.args[0] for c in out.write.call_args_list)
        errors = "".join(c.args[0] for c in err.write.call_args_list)
        return code, printed, errors

    def test_flashes_then_verifies_and_prints_the_report(self):
        code, printed, _ = self.main()
        self.assertEqual(code, 0)
        argv = self.esptool.call_args.args[0]
        self.assertIn("write-flash", argv)
        self.assertTrue(self.esptool.call_args.kwargs.get("check"))
        self.open_port.assert_called_once_with("/dev/ttyUSB0")
        self.close.assert_called_once_with(99)
        rep = json.loads(printed)
        self.assertEqual((rep["flashed"], rep["version"], rep["band"]), (True, "2.0.0", "2.4GHz"))
        self.assertEqual(rep["elf_sha256"], ELF_HEX)
        self.assertEqual(rep["image_sha256"]["spectre-sniffer.bin"],
                         hashlib.sha256(app_image()).hexdigest())

    def test_verify_only_never_runs_esptool(self):
        code, printed, _ = self.main("--verify-only")
        self.assertEqual(code, 0)
        self.esptool.assert_not_called()
        self.assertFalse(json.loads(printed)["flashed"])

    def test_failed_flash_never_opens_the_port(self):
        self.esptool.side_effect = flash.subprocess.CalledProcessError(2, "esptool")
        code, printed, errors = self.main()
        self.assertEqual((code, printed), (1, ""))
        self.assertIn("FAILED", errors)
        self.open_port.assert_not_called()

    def test_a_wrong_boot_fails_and_still_closes_the_port(self):
        self.board.ver = "1.9.0"
        code, printed, errors = self.main()
        self.assertEqual((code, printed), (1, ""))
        self.assertIn("version is '1.9.0'", errors)
        self.close.assert_called_once_with(99)

    def test_keep_config_is_passed_through(self):
        code, printed, _ = self.main("--keep-config")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(printed)["plan"]["channels"], "1,6,11")


if __name__ == "__main__":
    unittest.main()
