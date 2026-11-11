"""Simulator and replay emit the v2 firmware's lines: rich frame keys,
``ap_info``, sweep counters, telemetry, clock syncs and command acks, so the
hardware-free paths (CI, Browser QA, sim mode) exercise the same data a flashed
board produces. Author: gurvinny"""
import asyncio
import contextlib
import io
import json
import re
import unittest
from unittest import mock

from _support import TempDir

from spectre.config import Config
from spectre.parser import Parser
from spectre.pipeline import Pipeline
from spectre.reader import MAX_COMMAND_BYTES
from spectre.sim import generate
from spectre.sim import replay
from spectre.sim.generate import TAG, SimSource, Simulator
from spectre.sim.replay import ReplaySource
from spectre.store import Store

V1_KEYS = {"seq", "uptime_ms", "ch", "rssi", "type", "src", "dst", "bssid", "ssid"}
V2_FIELDS = ("sub", "nf", "phy", "mcs", "bw", "rate", "ts_us", "sn", "fc_flags", "dur",
             "reason", "auth_alg", "auth_seq", "status", "eapol", "probe_fp", "ouis")
SCENARIOS = ("deauth_flood", "evil_twin", "beacon_flood", "probe_flood", "reconnect")
CH_5G_DEFAULT = [36, 40, 44, 48, 52, 56, 60, 64, 100, 104, 108, 112, 116, 120, 124, 128,
                 132, 136, 140, 144, 149, 153, 157, 161, 165]


class Clock:
    def __init__(self, t: float = 1000.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t

    def advance(self, seconds: float) -> None:
        self.t += seconds


def body(line: str) -> dict:
    assert line.startswith(TAG), line
    return json.loads(line[len(TAG):])


def frames(lines):
    return [body(ln) for ln in lines if "type" in body(ln)]


def events(lines, kind=None):
    out = [body(ln) for ln in lines if "event" in body(ln)]
    return [o for o in out if kind is None or o["event"] == kind]


def sim(band="2.4GHz", seed=7, **kw):
    clock = kw.pop("clock", None) or Clock()
    kw.setdefault("drop_rate", 0.0)
    return Simulator(band, seed=seed, clock=clock, **kw), clock


def run_bg(s, n):
    out = []
    for _ in range(n):
        out += s.background()
    return out


class TestV1Mode(unittest.TestCase):

    def test_v1_boot_lines_keep_the_original_shape(self):
        s, _ = sim(fw="v1")
        self.assertEqual([body(ln) for ln in s.boot_lines()], [
            {"event": "boot", "chip": "ESP32-C5", "mode": "promiscuous", "band": "2.4GHz",
             "channels": "1-13"},
            {"event": "sniffer_started", "ch": 1, "usb_cdc": True}])

    def test_v1_frames_carry_only_original_keys(self):
        s, _ = sim(fw="v1")
        lines = run_bg(s, 200) + [ln for n in SCENARIOS for ln in s.scenario(n)]
        self.assertTrue(lines)
        for f in frames(lines):
            self.assertLessEqual(set(f), V1_KEYS, f)
        self.assertEqual(events(lines), [])

    def test_v1_has_no_ticks_and_no_command_interface(self):
        s, clock = sim(fw="v1")
        clock.advance(60)
        self.assertEqual(s.ticks(), [])
        self.assertEqual(s.command({"cmd": "get_config"}), [])

    def test_v2_frames_project_onto_the_v1_stream(self):
        """The v2 extras use their own RNG: seeded v1 traffic, and so every
        detector fixture built from it, is the same in both modes."""
        for band, seed in (("2.4GHz", 7), ("5GHz", 5)):
            a, _ = sim(band, seed, fw="v1")
            b, _ = sim(band, seed, fw="v2")
            for step in range(300):
                fa = frames(a.background())
                fb = [{k: v for k, v in f.items() if k in V1_KEYS}
                      for f in frames(b.background())]
                self.assertEqual(fa, fb, (band, step))
            for name in SCENARIOS:
                fa = frames(a.scenario(name))
                fb = [{k: v for k, v in f.items() if k in V1_KEYS}
                      for f in frames(b.scenario(name))]
                self.assertEqual(fa, fb, (band, name))


class TestV2Frames(unittest.TestCase):

    def setUp(self):
        self.s, self.clock = sim()
        self.lines = []
        for _ in range(400):
            self.lines += self.s.background()
            self.clock.advance(0.05)
        for name in SCENARIOS:
            self.lines += self.s.scenario(name)

    def parsed(self, lines=None, band="2.4GHz"):
        p = Parser("t", default_band=band)
        return [e for e in (p.parse_line(ln) for ln in (lines or self.lines)) if e is not None]

    def test_every_frame_key_is_a_known_column(self):
        evs = self.parsed()
        self.assertGreater(len(evs), 500)
        for ev in evs:
            self.assertEqual(ev.extra, {}, ev)

    def test_every_v2_field_is_populated_somewhere(self):
        evs = self.parsed()
        for field in V2_FIELDS:
            self.assertTrue(any(getattr(e, field) is not None for e in evs), field)

    def test_seq_counts_frame_lines_only(self):
        self.assertTrue(events(self.lines, "ap_info"))
        self.assertEqual([f["seq"] for f in frames(self.lines)],
                         list(range(1, len(frames(self.lines)) + 1)))
        for e in events(self.lines):
            self.assertNotIn("seq", e)

    def test_legacy_mgmt_reports_rate_and_ht_data_reports_mcs(self):
        for f in frames(self.lines):
            if f["type"] in ("BEACON", "PROBE_REQ", "PROBE_RESP", "DEAUTH", "DISASSOC", "AUTH"):
                self.assertEqual((f["phy"], f["rate"], "mcs" in f), ("g", 11, False), f)
            if f["type"] == "DATA":
                self.assertIn(f["phy"], ("n", "ax"))
                self.assertIn(f["mcs"], range(0, 12))
                self.assertNotIn("rate", f)
            self.assertEqual(f["bw"], 20)
            self.assertIn(f["nf"], range(-97, -89))

    def test_five_ghz_frames_never_claim_a_2_4_only_phy(self):
        s, clock = sim("5GHz", 5)
        fs = frames(run_bg(s, 300))
        self.assertTrue(fs)
        self.assertEqual({f["phy"] for f in fs} - {"a", "n", "ac", "ax"}, set())
        self.assertIn("a", {f["phy"] for f in fs})
        for f in fs:
            self.assertGreaterEqual(f["ch"], 36)

    def test_subtypes_match_the_frame_type(self):
        want = {"BEACON": {8}, "PROBE_REQ": {4}, "PROBE_RESP": {5}, "DEAUTH": {12},
                "DISASSOC": {10}, "AUTH": {11}, "DATA": {0, 8}}
        seen = set()
        for f in frames(self.lines):
            self.assertIn(f["sub"], want[f["type"]], f)
            seen.add(f["type"])
        self.assertEqual(seen, set(want))

    def test_deauth_and_disassoc_carry_a_reason(self):
        fs = [f for f in frames(self.lines) if f["type"] in ("DEAUTH", "DISASSOC")]
        self.assertTrue(fs)
        self.assertEqual({f["reason"] for f in fs}, {7})
        self.assertFalse(any("reason" in f for f in frames(self.lines)
                             if f["type"] not in ("DEAUTH", "DISASSOC")))

    def test_reconnect_is_an_auth_pair_then_a_four_way_handshake(self):
        s, _ = sim()
        fs = frames(s.scenario("reconnect"))
        self.assertEqual([(f["type"], f.get("aseq"), f.get("eapol")) for f in fs],
                         [("AUTH", 1, None), ("AUTH", 2, None), ("DATA", None, 1),
                          ("DATA", None, 2), ("DATA", None, 3), ("DATA", None, 4)])
        self.assertEqual([(f["aalg"], f["st"]) for f in fs[:2]], [(0, 0), (0, 0)])
        self.assertEqual([f["fl"] & 0x40 for f in fs[2:]], [0, 0, 0, 0])
        client, ap = fs[0]["src"], fs[0]["dst"]
        self.assertEqual([f["src"] for f in fs], [client, ap, ap, client, ap, client])

    def test_probe_requests_carry_a_fingerprint_and_vendor_ouis(self):
        fs = [f for f in frames(self.lines) if f["type"] == "PROBE_REQ"]
        self.assertTrue(fs)
        for f in fs:
            self.assertRegex(f["fp"], r"^[0-9a-f]{8}$")
            self.assertTrue(all(re.fullmatch(r"[0-9A-F]{6}", o) for o in f["ouis"]), f)
        self.assertFalse(any("fp" in f or "ouis" in f for f in frames(self.lines)
                             if f["type"] != "PROBE_REQ"))

    def test_a_device_keeps_its_fingerprint(self):
        fps = {}
        for f in frames(run_bg(self.s, 400)):
            if f["type"] == "PROBE_REQ":
                fps.setdefault(f["src"], set()).add(f["fp"])
        self.assertTrue(fps)
        for src, seen in fps.items():
            self.assertEqual(len(seen), 1, src)

    def test_sequence_numbers_step_per_transmitter_and_wrap(self):
        last = {}
        for f in frames(self.lines):
            src = f.get("src")
            if src in last:
                self.assertEqual(f["sn"], (last[src] + 1) % 4096, f)
            last[src] = f["sn"]
        s, _ = sim()
        s._sn["00:00:5E:00:53:01"] = 4095
        fs = [f for f in frames(s.scenario("deauth_flood"))]
        self.assertEqual([f["sn"] for f in fs[:2]], [0, 1])

    def test_radio_timestamp_follows_uptime_and_wraps_at_32_bits(self):
        s, clock = sim()
        clock.advance(1.2345)
        (f,) = frames(s.background())
        self.assertEqual((f["ts"], f["uptime_ms"]), (1234500, 1234))
        clock.advance(2 ** 32 / 1e6)
        (later,) = frames(s.background())
        self.assertEqual((later["ts"], later["uptime_ms"]), (1234500, 4296201))

    def test_frame_control_flags(self):
        fs = frames(self.lines)
        data = [f for f in fs if f["type"] == "DATA"]
        for f in data:
            self.assertEqual(f["fl"] & 0x03, 0x01 if f["dst"] == f["bssid"] else 0x02, f)
        self.assertTrue(any(f["fl"] & 0x40 for f in data))
        self.assertTrue(any(f["fl"] & 0x08 for f in fs))
        self.assertFalse(any(f["fl"] & 0x08 for f in fs if f["dst"] == "FF:FF:FF:FF:FF:FF"))
        for f in fs:
            if f["type"] != "DATA":
                self.assertEqual(f["fl"] & 0x43, 0, f)

    def test_broadcast_frames_have_zero_duration(self):
        for f in frames(self.lines):
            if f["dst"] == "FF:FF:FF:FF:FF:FF":
                self.assertEqual(f["dur"], 0, f)
            else:
                self.assertGreater(f["dur"], 0, f)


class TestApInfo(unittest.TestCase):

    def beacons_with_info(self, lines):
        """(bssid of each ap_info, bssid of the frame line right after it)."""
        out = []
        for i, ln in enumerate(lines):
            b = body(ln)
            if b.get("event") == "ap_info":
                out.append((b["bssid"], body(lines[i + 1]).get("bssid")))
        return out

    def test_first_sighting_precedes_the_frame_and_is_sent_once(self):
        s, _ = sim()
        lines = run_bg(s, 400)
        infos = events(lines, "ap_info")
        self.assertTrue(infos)
        self.assertEqual({i["why"] for i in infos}, {"new"})
        bssids = [i["bssid"] for i in infos]
        self.assertEqual(len(bssids), len(set(bssids)))
        for info, nxt in self.beacons_with_info(lines):
            self.assertEqual(info, nxt)

    def test_periodic_resend_after_ap_info_s(self):
        s, clock = sim()
        run_bg(s, 200)
        clock.advance(299)
        self.assertEqual(events(run_bg(s, 100), "ap_info"), [])
        clock.advance(2)
        again = events(run_bg(s, 200), "ap_info")
        self.assertTrue(again)
        self.assertEqual({i["why"] for i in again}, {"periodic"})

    def test_zero_interval_sends_on_change_only(self):
        s, clock = sim()
        s.command({"cmd": "set", "ap_info_s": 0})
        run_bg(s, 200)
        clock.advance(3600)
        self.assertEqual(events(run_bg(s, 200), "ap_info"), [])

    def test_a_changed_element_set_is_reported_as_changed(self):
        s, _ = sim()
        run_bg(s, 200)
        bssid = s._aps[0]["bssid"]
        before = s.ap_info_line(s._aps[0], "x")
        s.set_ap(bssid, sec="WPA2", akm=["PSK"], pmf="none")
        lines = run_bg(s, 200)
        changed = [i for i in events(lines, "ap_info") if i["why"] == "changed"]
        self.assertEqual([i["bssid"] for i in changed], [bssid])
        self.assertEqual(changed[0]["sec"], "WPA2")
        self.assertNotEqual(changed[0]["hash"], body(before)["hash"])

    def test_evil_twin_advertises_weaker_security_under_the_same_ssid(self):
        s, _ = sim()
        legit = s._aps[0]
        infos = events(s.scenario("evil_twin"), "ap_info")
        self.assertEqual(len(infos), 1)
        self.assertEqual((infos[0]["ssid"], infos[0]["sec"], infos[0]["pmf"]),
                         (legit["ssid"], "OPEN", "none"))
        self.assertNotEqual(infos[0]["bssid"], legit["bssid"])

    def test_ap_info_shape_matches_the_firmware(self):
        s, _ = sim()
        info = body(s.ap_info_line(s._aps[0], "new"))
        self.assertEqual(list(info)[:10], ["event", "uptime_ms", "why", "bssid", "ch", "ds_ch",
                                           "ssid", "bi", "cap", "sec"])
        self.assertEqual(info["hash"], body(s.ap_info_line(s._aps[0], "periodic"))["hash"])
        self.assertRegex(info["hash"], r"^[0-9a-f]{8}$")
        for k in ("wpa1", "ht", "vht", "he", "eht", "wps"):
            self.assertIsInstance(info[k], bool, k)
        self.assertEqual(info["ch"], info["ds_ch"])
        self.assertEqual(info["cap"], 0x0011)
        (rogue,) = events(s.scenario("evil_twin"), "ap_info")
        self.assertEqual(rogue["cap"], 0x0001)

    def test_ap_info_lands_in_the_store_with_typed_flags(self):
        tmp = TempDir()
        self.addCleanup(tmp.cleanup)
        store = Store(tmp.file("s.db"))
        self.addCleanup(store.close)
        s, _ = sim()
        p = Parser("sim-2.4GHz", default_band="2.4GHz", on_ap_info=store.insert_ap_info)
        for ln in run_bg(s, 200):
            p.parse_line(ln)
        rows = store.ap_info()
        self.assertTrue(rows)
        by = {r["bssid"]: r for r in rows}
        ap = s._aps[0]
        row = by[ap["bssid"]]
        self.assertEqual((row["sec"], row["pmf"], row["ht"], row["wps"]),
                         (ap["sec"], ap["pmf"], int(ap["ht"]), int(ap["wps"])))


class TestTicks(unittest.TestCase):

    def test_a_sweep_line_per_sweep_with_consistent_counters(self):
        s, clock = sim()
        lines = run_bg(s, 120)
        self.assertEqual(s.ticks(), [])
        clock.advance(3.9)
        (sweep,) = events(s.ticks(), "channel_sweep_complete")
        n = len(frames(lines))
        self.assertEqual((sweep["total_pkts"], sweep["emitted"], sweep["sweep_ms"]), (n, n, 3900))
        drops = sum(sweep[k] for k in ("drop_queue", "drop_short", "drop_dedup", "drop_overflow"))
        self.assertEqual(sweep["rx_total"], sweep["emitted"] + drops)

    def test_five_ghz_sweep_is_25_channels_of_200_ms(self):
        s, clock = sim("5GHz", 5)
        clock.advance(4.9)
        self.assertEqual(events(s.ticks(), "channel_sweep_complete"), [])
        clock.advance(0.1)
        (sweep,) = events(s.ticks(), "channel_sweep_complete")
        self.assertEqual(sweep["sweep_ms"], 5000)

    def test_a_stall_yields_one_sweep_not_a_burst(self):
        s, clock = sim()
        clock.advance(60)
        self.assertEqual(len(events(s.ticks(), "channel_sweep_complete")), 1)
        self.assertEqual(events(s.ticks(), "channel_sweep_complete"), [])
        clock.advance(3.9)
        self.assertEqual(len(events(s.ticks(), "channel_sweep_complete")), 1)

    def test_telemetry_and_clock_sync_every_ten_seconds(self):
        s, clock = sim()
        clock.advance(9.9)
        self.assertEqual([e["event"] for e in events(s.ticks())], ["channel_sweep_complete"])
        clock.advance(0.1)
        kinds = [e["event"] for e in events(s.ticks())]
        self.assertEqual(sorted(kinds), ["clock_sync", "telemetry"])
        clock.advance(10)
        self.assertEqual(sorted(e["event"] for e in events(s.ticks())
                                if e["event"] != "channel_sweep_complete"),
                         ["clock_sync", "telemetry"])

    def test_telemetry_reports_throughput_and_memory(self):
        s, clock = sim()
        run_bg(s, 20)
        clock.advance(10)
        first = s.ticks()
        lines = run_bg(s, 100)
        clock.advance(10)
        (tel,) = events(s.ticks(), "telemetry")
        # every byte on the wire since the last snapshot, the last ticks included
        sent = sum(len(ln) + 1 for ln in first + lines)
        self.assertEqual(tel["uart_bps"], sent // 10)
        self.assertEqual(tel["q_size"], 65536)
        self.assertLessEqual(tel["q_hwm"], tel["q_size"])
        self.assertLessEqual(tel["heap_min"], tel["heap"])
        self.assertIn(tel["temp_dc"], range(350, 500))
        self.assertEqual(tel["emitted"], len(frames(lines)) + 20)

    def test_clock_sync_maps_uptime_to_microseconds(self):
        s, clock = sim()
        clock.advance(10.0004)
        (cs,) = events(s.ticks(), "clock_sync")
        self.assertEqual(cs["uptime_ms"], 10000)
        self.assertEqual(cs["mono_us"], 10000400)

    def test_dropped_frames_are_counted_not_emitted(self):
        s, clock = sim(drop_rate=1.0)
        self.assertEqual(frames(run_bg(s, 50)), [])
        clock.advance(10)
        (tel,) = events(s.ticks(), "telemetry")
        self.assertEqual((tel["rx_total"], tel["emitted"]), (50, 0))
        self.assertEqual(tel["drop_queue"] + tel["drop_short"], 50)
        self.assertGreater(tel["drop_queue"], 0)
        self.assertGreater(tel["drop_short"], 0)

    def test_scenarios_are_never_dropped(self):
        s, _ = sim(drop_rate=1.0)
        self.assertEqual(len(frames(s.scenario("deauth_flood"))), 40)

    def test_the_default_simulator_drops_a_few(self):
        s = Simulator("2.4GHz", seed=7, clock=Clock())
        run_bg(s, 3000)
        self.assertGreater(s.counters["drop_queue"], 0)
        self.assertLess(s.counters["drop_queue"], 60)


class TestBoot(unittest.TestCase):

    def test_v2_boot_reports_the_radio_plan(self):
        s, _ = sim("5GHz", 5)
        boot, started = [body(ln) for ln in s.boot_lines()]
        self.assertEqual(list(boot), ["event", "chip", "mode", "band", "channels", "dwell_ms",
                                      "pin", "filter", "dedup", "ap_info_s", "fw", "ver",
                                      "elf_sha", "reset", "baud", "caps"])
        self.assertEqual((boot["band"], boot["channels"], boot["dwell_ms"], boot["baud"]),
                         ("5GHz", "36-165", 200, 460800))
        self.assertEqual(boot["reset"], "poweron")
        self.assertEqual(boot["caps"], ["counters", "cmd", "ap_info", "phy", "telemetry"])
        self.assertEqual(started, {"event": "sniffer_started", "ch": 36})

    def test_a_pinned_board_starts_on_its_pin(self):
        s, _ = sim()
        s.command({"cmd": "set", "pin": 6})
        self.assertEqual(body(s.boot_lines()[1]), {"event": "sniffer_started", "ch": 6})


class TestCommands(unittest.TestCase):

    def setUp(self):
        self.s, self.clock = sim()

    def ack(self, cmd):
        lines = self.s.command(cmd)
        acks = events(lines, "cmd_ack")
        self.assertEqual(len(acks), 1, lines)
        return acks[0]

    def assertFails(self, cmd, err):
        before = self.ack({"cmd": "get_config"})["config"]
        a = self.ack(cmd)
        self.assertEqual((a["ok"], a.get("err")), (False, err), cmd)
        self.assertEqual(a["config"], before)

    def test_get_config_echoes_the_id_and_the_defaults(self):
        a = self.ack({"cmd": "get_config", "id": "q1"})
        self.assertEqual(list(a), ["event", "cmd", "id", "ok", "config"])
        self.assertEqual((a["cmd"], a["id"], a["ok"]), ("get_config", "q1", True))
        self.assertEqual(a["config"], {"band": "2.4GHz", "channels": "1-13", "dwell_ms": 300,
                                       "pin": 0, "filter": ["mgmt", "data"], "dedup": 0,
                                       "ap_info_s": 300})

    def test_set_dwell_changes_the_sweep_period(self):
        a = self.ack({"cmd": "set", "dwell_ms": 100})
        self.assertEqual((a["ok"], a["config"]["dwell_ms"]), (True, 100))
        self.clock.advance(1.3)
        (sweep,) = events(self.s.ticks(), "channel_sweep_complete")
        self.assertEqual(sweep["sweep_ms"], 1300)

    def test_set_channels_restricts_frames(self):
        a = self.ack({"cmd": "set", "channels": [1, 6, 11]})
        self.assertEqual(a["config"]["channels"], "1,6,11")
        chans = {f["ch"] for f in frames(run_bg(self.s, 300))}
        self.assertTrue(chans)
        self.assertLessEqual(chans, {1, 6, 11})

    def test_the_default_list_reads_as_a_range_again(self):
        self.ack({"cmd": "set", "channels": [1, 6, 11]})
        a = self.ack({"cmd": "set", "channels": list(range(1, 14))})
        self.assertEqual(a["config"]["channels"], "1-13")

    def test_pin_holds_every_frame_on_one_channel(self):
        self.ack({"cmd": "set", "pin": 3})
        fs = frames(run_bg(self.s, 200))
        self.assertEqual({f["ch"] for f in fs}, {3})
        # only the AP that lives on channel 3 is heard beaconing
        self.assertEqual({f["bssid"] for f in fs if f["type"] == "BEACON"},
                         {"00:00:5E:00:53:04"})
        self.ack({"cmd": "set", "pin": 9})   # no AP lives on 9
        self.assertEqual({f["ch"] for f in frames(run_bg(self.s, 200))}, {9})

    def test_a_pin_outside_a_new_list_lapses(self):
        self.ack({"cmd": "set", "pin": 3})
        a = self.ack({"cmd": "set", "channels": [1, 6]})
        self.assertEqual(a["config"]["pin"], 0)
        b = self.ack({"cmd": "set", "pin": 6})
        c = self.ack({"cmd": "set", "channels": [6, 11]})
        self.assertEqual((b["config"]["pin"], c["config"]["pin"]), (6, 6))

    def test_band_switch_resets_the_plan(self):
        self.ack({"cmd": "set", "dwell_ms": 100})
        a = self.ack({"cmd": "set", "band": "5GHz"})
        self.assertEqual((a["config"]["band"], a["config"]["channels"], a["config"]["dwell_ms"]),
                         ("5GHz", "36-165", 200))
        fs = frames(run_bg(self.s, 200))
        self.assertTrue(fs)
        self.assertTrue(all(f["ch"] in CH_5G_DEFAULT for f in fs))
        self.assertIn("a", {f["phy"] for f in fs})

    def test_band_switch_with_channels_uses_the_new_band(self):
        a = self.ack({"cmd": "set", "band": "5GHz", "channels": [36, 149]})
        self.assertEqual((a["ok"], a["config"]["channels"]), (True, "36,149"))

    def test_filter_drops_data_or_adds_control(self):
        self.ack({"cmd": "set", "filter": ["mgmt"]})
        types = {f["type"] for f in frames(run_bg(self.s, 300))}
        self.assertNotIn("DATA", types)
        self.assertIn("BEACON", types)
        self.ack({"cmd": "set", "filter": ["mgmt", "ctrl", "data"]})
        fs = frames(run_bg(self.s, 600))
        ctrl = [f for f in fs if f["type"] == "CTRL"]
        self.assertTrue(ctrl)
        self.assertIn("DATA", {f["type"] for f in fs})
        for f in ctrl:
            self.assertEqual((f["sub"], "src" in f, "sn" in f), (13, False, False))
        self.ack({"cmd": "set", "filter": ["data"]})
        self.assertEqual({f["type"] for f in frames(run_bg(self.s, 300))}, {"DATA"})
        a = self.ack({"cmd": "set", "filter": ["data", "mgmt"]})
        self.assertEqual(a["config"]["filter"], ["mgmt", "data"])

    def test_filtered_frames_are_not_counted(self):
        self.ack({"cmd": "set", "filter": ["data"]})
        run_bg(self.s, 300)
        self.assertEqual(self.s.counters["rx_total"], self.s.counters["emitted"])

    def test_dedup_emits_one_beacon_per_bssid_per_dwell(self):
        self.ack({"cmd": "set", "dedup": 1})
        lines = run_bg(self.s, 300)
        beacons = [f["bssid"] for f in frames(lines) if f["type"] == "BEACON"]
        self.assertEqual(len(beacons), len(set(beacons)))
        self.assertGreater(self.s.counters["drop_dedup"], 0)
        self.clock.advance(0.3)
        again = [f["bssid"] for f in frames(run_bg(self.s, 50)) if f["type"] == "BEACON"]
        self.assertTrue(set(again) & set(beacons))

    def test_reset_config_restores_the_band_defaults(self):
        self.ack({"cmd": "set", "band": "5GHz"})
        self.ack({"cmd": "set", "dwell_ms": 999, "dedup": 1})
        a = self.ack({"cmd": "reset_config"})
        self.assertEqual((a["ok"], a["config"]["band"], a["config"]["dwell_ms"],
                          a["config"]["dedup"]), (True, "5GHz", 200, 0))

    def test_reboot_acks_then_boots_with_a_fresh_run_and_the_saved_plan(self):
        self.ack({"cmd": "set", "dwell_ms": 150})
        run_bg(self.s, 50)
        self.clock.advance(5)
        lines = self.s.command({"cmd": "reboot", "id": "r"})
        self.assertEqual([body(ln)["event"] for ln in lines],
                         ["cmd_ack", "boot", "sniffer_started"])
        boot = body(lines[1])
        self.assertEqual((boot["reset"], boot["dwell_ms"]), ("software", 150))
        self.assertEqual(frames(self.s.background())[0]["seq"], 1)
        self.assertLess(frames(self.s.background())[0]["uptime_ms"], 100)
        self.assertEqual(self.s.counters["emitted"], 2)
        (info,) = events(run_bg(self.s, 30), "ap_info")[:1] or [None]
        self.assertEqual(info["why"], "new")

    def test_rejected_input(self):
        self.assertFails({"cmd": "fly"}, "unknown cmd")
        self.assertFails({"id": "x"}, "missing cmd")
        self.assertFails({"cmd": "set", "colour": 1}, "unknown key")
        self.assertFails({"cmd": "set", "band": "6GHz"}, "bad band")
        self.assertFails({"cmd": "set", "channels": [36]}, "bad channel")
        self.assertFails({"cmd": "set", "channels": [1, 1]}, "bad channel")
        self.assertFails({"cmd": "set", "channels": []}, "bad channel")
        self.assertFails({"cmd": "set", "dwell_ms": 49}, "bad dwell")
        self.assertFails({"cmd": "set", "dwell_ms": 5001}, "bad dwell")
        self.assertFails({"cmd": "set", "pin": 36}, "bad pin")
        self.assertFails({"cmd": "set", "filter": []}, "bad filter")
        self.assertFails({"cmd": "set", "filter": ["beacons"]}, "bad filter")
        self.assertFails({"cmd": "set", "dedup": 2}, "bad value")
        self.assertFails({"cmd": "set", "ap_info_s": 3601}, "bad value")
        self.assertFails("not json", "bad json")
        self.assertFails('{"cmd":"set","dwell_ms":1.5}', "bad json")
        self.assertFails({"cmd": "set", "csa": {"ch": 1}}, "bad json")
        self.assertFails({"cmd": "set", "band": 5}, "bad json")
        self.assertFails({"cmd": "get_config", "id": "x" * 17}, "bad json")
        self.assertFails({"cmd": "set", "channels": [1, "6"]}, "bad json")
        self.assertFails({"cmd": "set", "channels": [1, 6], "dwell_ms": 1}, "bad dwell")

    def test_boundaries_are_accepted(self):
        for cmd in ({"cmd": "set", "dwell_ms": 50}, {"cmd": "set", "dwell_ms": 5000},
                    {"cmd": "set", "ap_info_s": 3600}, {"cmd": "set", "ap_info_s": 0},
                    {"cmd": "set", "pin": 14}, {"cmd": "get_config", "id": "x" * 16}):
            self.assertTrue(self.ack(cmd)["ok"], cmd)

    def test_an_overlong_line_is_refused(self):
        a = self.ack('{"cmd":"get_config","id":"' + "x" * 300 + '"}')
        self.assertEqual((a["ok"], a["err"], a["cmd"]), (False, "line too long", ""))

    def test_failed_commands_keep_the_unknown_name(self):
        a = self.ack({"cmd": "fly", "id": "z"})
        self.assertEqual((a["cmd"], a["id"]), ("fly", "z"))
        self.assertEqual(self.ack("nope")["cmd"], "")


class TestSimSource(unittest.TestCase):

    def setUp(self):
        self.tmp = TempDir()
        self.store = Store(self.tmp.file("s.db"))
        self.pipe = Pipeline(self.store, Config(self.store))
        self.clock = Clock()
        self.src = SimSource(self.pipe, clock=self.clock)
        self.src.prime()

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def kinds(self):
        self.pipe.flush()
        return [r["kind"] for r in self.store.board_events()]

    def test_boards_are_the_two_sim_sensors(self):
        self.assertEqual(sorted(self.src.boards), ["sim-2.4GHz", "sim-5GHz"])
        self.assertEqual(self.kinds(), ["boot", "sniffer_started", "boot", "sniffer_started"])

    def test_send_feeds_the_ack_back_through_the_parser(self):
        board = self.src.boards["sim-5GHz"]
        n = board.send({"cmd": "get_config", "id": "a"})
        self.assertEqual(n, len('{"cmd":"get_config","id":"a"}') + 1)
        self.pipe.flush()
        (ack,) = [r for r in self.store.board_events() if r["kind"] == "cmd_ack"]
        self.assertEqual((ack["sensor_id"], ack["payload"]["id"], ack["payload"]["ok"]),
                         ("sim-5GHz", "a", True))

    def test_send_refuses_what_the_serial_reader_refuses(self):
        board = self.src.boards["sim-2.4GHz"]
        with self.assertRaises(ValueError):
            board.send('{"cmd":"get_config"}\n{"cmd":"reboot"}')
        with self.assertRaises(ValueError):
            board.send({"cmd": "get_config", "id": "x" * MAX_COMMAND_BYTES})
        self.assertNotIn("cmd_ack", self.kinds())

    def test_a_band_switch_relabels_later_frames(self):
        self.src.boards["sim-2.4GHz"].send({"cmd": "set", "band": "5GHz"})
        self.assertEqual(self.src.boards["sim-2.4GHz"].parser.band, "5GHz")
        for _ in range(50):
            self.src.step()
        self.pipe.flush()
        rows = self.store._db.execute(
            "SELECT DISTINCT band FROM frames WHERE sensor_id = 'sim-2.4GHz'").fetchall()
        self.assertEqual([r[0] for r in rows], ["5GHz"])

    def test_step_runs_traffic_and_periodic_lines_on_both_boards(self):
        # traffic only ever on the 2.4 GHz board: the 5 GHz one still ticks
        with mock.patch.object(generate.random, "random", return_value=0.0):
            for _ in range(100):
                self.src.step()
                self.clock.advance(0.11)
        self.pipe.flush()
        evs = self.store.board_events()
        for sensor in ("sim-2.4GHz", "sim-5GHz"):
            kinds = {r["kind"] for r in evs if r["sensor_id"] == sensor}
            self.assertLessEqual({"telemetry", "clock_sync", "channel_sweep_complete"}, kinds)
        self.assertTrue(self.store.ap_info())
        (n,) = self.store._db.execute(
            "SELECT COUNT(*) FROM frames WHERE phy IS NOT NULL").fetchone()
        self.assertGreater(n, 0)

    def test_scenarios_rotate_on_the_2_4_board(self):
        self.src.next_scenario = self.clock.t
        self.src.step()
        self.assertEqual(self.src.scenario_idx, 1)
        self.clock.advance(44)
        self.src.step()
        self.assertEqual(self.src.scenario_idx, 1)
        self.clock.advance(1)
        self.src.step()
        self.assertEqual(self.src.scenario_idx, 2)
        self.assertIn("reconnect", SimSource.ROTATION)

    def test_run_primes_and_loops(self):
        src = SimSource(self.pipe, fps=500.0, clock=self.clock)

        async def go():
            task = asyncio.ensure_future(src.run())
            await asyncio.sleep(0.05)
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        asyncio.run(go())
        self.assertGreater(self.pipe.total_frames, 3)


class TestCli(unittest.TestCase):

    def run_main(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(generate._main(list(argv)), 0)
        return out.getvalue().splitlines()

    def test_cli_prints_v2_lines_that_parse(self):
        lines = self.run_main("--duration", "0.2", "--fps", "200", "--band", "5GHz")
        self.assertGreater(len(lines), 5)
        self.assertEqual(body(lines[0])["ver"], generate.FW_VERSION)
        p = Parser("cli")
        evs = [e for e in (p.parse_line(ln) for ln in lines) if e is not None]
        self.assertTrue(evs)
        self.assertEqual({e.band for e in evs}, {"5GHz"})
        self.assertTrue(all(e.phy for e in evs))

    def test_cli_can_still_print_v1(self):
        lines = self.run_main("--duration", "0.1", "--fps", "200", "--fw", "v1")
        self.assertNotIn("ver", body(lines[0]))


class TestReplayV2(unittest.TestCase):

    def setUp(self):
        self.tmp = TempDir()
        self.store = Store(self.tmp.file("s.db"))
        self.pipe = Pipeline(self.store, Config(self.store))
        s, clock = sim("5GHz", 5)
        lines = list(s.boot_lines())
        for _ in range(120):
            lines += s.background()
            clock.advance(0.1)
            lines += s.ticks()
        lines += s.command({"cmd": "get_config", "id": "c"})
        self.lines = lines
        self.path = self.tmp.file("capture.log")
        with open(self.path, "w") as fh:
            fh.write("\n".join(lines) + "\n")

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()

    def test_a_v2_capture_replays_into_every_table(self):
        asyncio.run(ReplaySource(self.pipe, self.path, speed=1000.0, loop=False).run())
        self.pipe.flush()
        kinds = {r["kind"] for r in self.store.board_events()}
        self.assertEqual(kinds, {"boot", "sniffer_started", "channel_sweep_complete",
                                 "telemetry", "clock_sync", "cmd_ack"})
        self.assertEqual({r["band"] for r in self.store.ap_info()}, {"5GHz"})
        (n, nulls) = self.store._db.execute(
            "SELECT COUNT(*), SUM(phy IS NULL) FROM frames").fetchone()
        self.assertEqual((n, nulls), (len(frames(self.lines)), 0))

    def test_standalone_replay_can_print_lifecycle_records(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(replay._main([self.path, "--events"]), 0)
        recs = [json.loads(ln) for ln in out.getvalue().splitlines()]
        kinds = [r["kind"] for r in recs if "kind" in r]
        self.assertEqual(kinds[:2], ["boot", "sniffer_started"])
        self.assertIn("ap_info", kinds)
        self.assertEqual(len([r for r in recs if "kind" not in r]), len(frames(self.lines)))
        self.assertTrue(all(r["band"] == "5GHz" for r in recs))

    def test_standalone_replay_prints_frames_only_by_default(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            replay._main([self.path])
        recs = [json.loads(ln) for ln in out.getvalue().splitlines()]
        self.assertEqual(len(recs), len(frames(self.lines)))
        self.assertFalse(any("kind" in r for r in recs))


if __name__ == "__main__":
    unittest.main()
