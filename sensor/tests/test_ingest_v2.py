"""Firmware v2 ingest: typed frame fields, ap_info routing, schema migration,
high baud rates and the reader's write path. Author: gurvinny"""
import asyncio
import os
import select
import sqlite3
import termios
import threading
import time
import tty
import unittest
from unittest import mock

from _support import TempDir

from spectre.config import Config
from spectre.models import Event
from spectre.parser import Parser
from spectre.pipeline import Pipeline
from spectre import reader as reader_mod
from spectre.reader import SerialReader, _open_serial
from spectre.sim.generate import SimSource
from spectre.sim.replay import ReplaySource
from spectre.store import Store

P = "<190>ESP32C5 wifi_sniffer: "
# Lines as the v2 firmware's host tests write them (`make samples`).
BEACON = P + ('{"seq":47,"uptime_ms":2728,"ch":6,"rssi":-52,"type":"BEACON","sub":8,'
              '"src":"00:00:5E:00:53:01","dst":"FF:FF:FF:FF:FF:FF","bssid":"00:00:5E:00:53:01",'
              '"ssid":"LabNet","nf":-95,"phy":"g","bw":20,"rate":11,"ts":123456789,"sn":100,'
              '"fl":0,"dur":314}')
DEAUTH = P + ('{"seq":2,"uptime_ms":3,"ch":36,"rssi":-52,"type":"DEAUTH","sub":12,'
              '"src":"00:00:5E:00:53:01","dst":"00:00:5E:00:53:02","bssid":"00:00:5E:00:53:01",'
              '"nf":-95,"phy":"n","mcs":5,"bw":20,"ts":123456789,"sn":9,"fl":8,"dur":314,"reason":7}')
AUTH = P + ('{"seq":3,"uptime_ms":4,"ch":36,"rssi":-52,"type":"AUTH","sub":11,'
            '"src":"00:00:5E:00:53:02","dst":"00:00:5E:00:53:01","bssid":"00:00:5E:00:53:01",'
            '"nf":-95,"phy":"n","mcs":5,"bw":20,"ts":123456789,"sn":2,"fl":0,"dur":314,'
            '"aalg":3,"aseq":1,"st":0}')
DATA = P + ('{"seq":4,"uptime_ms":5,"ch":36,"rssi":-52,"type":"DATA","sub":8,'
            '"src":"00:00:5E:00:53:01","dst":"00:00:5E:00:53:02","bssid":"00:00:5E:00:53:01",'
            '"nf":-95,"phy":"n","mcs":5,"bw":20,"ts":123456789,"sn":5,"fl":2,"dur":314,"eapol":1}')
PROBE = P + ('{"seq":5,"uptime_ms":6,"ch":11,"rssi":-52,"type":"PROBE_REQ","sub":4,'
             '"src":"00:00:5E:00:53:02","dst":"FF:FF:FF:FF:FF:FF","bssid":"FF:FF:FF:FF:FF:FF",'
             '"ssid":"?","nf":-95,"phy":"g","bw":20,"rate":11,"ts":123456789,"sn":77,"fl":0,'
             '"dur":314,"fp":"13adc91c","ouis":["0050F2","00163E"]}')
MAXED = P + ('{"seq":4294967295,"uptime_ms":4294967295,"ch":165,"rssi":-128,"type":"PROBE_REQ",'
             '"sub":4,"src":"00:00:5E:00:53:02","dst":"FF:FF:FF:FF:FF:FF","bssid":"FF:FF:FF:FF:FF:FF",'
             '"nf":-128,"phy":"a","bw":20,"rate":11,"ts":4294967295,"sn":4095,"fl":255,'
             '"dur":65535,"fp":"811c9dc5"}')
V1_FRAME = ('<190>ESP32C5 wifi_sniffer_5g: {"seq":7,"uptime_ms":2728,"ch":36,"rssi":-55,'
            '"type":"BEACON","src":"00:00:5E:00:53:01","dst":"FF:FF:FF:FF:FF:FF",'
            '"bssid":"00:00:5E:00:53:01","ssid":"ExampleNet"}')

BOOT_5 = P + ('{"event":"boot","chip":"ESP32-C5","mode":"promiscuous","band":"5GHz",'
              '"channels":"36-165","dwell_ms":200,"pin":0,"filter":["mgmt","data"],"dedup":0,'
              '"ap_info_s":300,"fw":"spectre-sniffer","ver":"v2.0.0","elf_sha":"0123456789abcdef",'
              '"reset":"poweron","baud":460800,"caps":["counters","cmd","ap_info","phy","telemetry"]}')
AP_INFO = P + ('{"event":"ap_info","uptime_ms":5000,"why":"new","bssid":"00:00:5E:00:53:01",'
               '"ch":36,"ds_ch":36,"ssid":"LabNet","bi":100,"cap":17,"sec":"WPA2/WPA3",'
               '"akm":["PSK","SAE"],"pairwise":["CCMP"],"group":["CCMP"],"pmf":"capable",'
               '"wpa1":false,"ht":true,"vht":false,"he":true,"eht":false,"wps":true,'
               '"csa":{"mode":1,"ch":149,"count":5},"ouis":["0050F2"],"hash":"40a7e2da"}')
AP_INFO_HIDDEN = P + ('{"event":"ap_info","uptime_ms":9000,"why":"periodic",'
                      '"bssid":"00:00:5e:00:53:09","ch":1,"ds_ch":1,"ssid":"?","sec":"OPEN",'
                      '"pmf":"none","wpa1":true,"ht":false,"vht":true,"he":false,"eht":true,'
                      '"wps":false,"hash":"0000beef"}')
TELEMETRY = P + ('{"event":"telemetry","uptime_ms":20000,"rx_total":1000,"emitted":990,'
                 '"drop_queue":4,"drop_short":3,"drop_dedup":2,"drop_overflow":1,"q_hwm":2048,'
                 '"q_size":32768,"heap":150000,"heap_min":120000,"temp_dc":412,"uart_bps":23040}')
CLOCK = P + '{"event":"clock_sync","uptime_ms":30000,"mono_us":30000123456}'
ACK_24 = P + ('{"event":"cmd_ack","cmd":"set","id":"a1","ok":true,"config":{"band":"2.4GHz",'
              '"channels":"1,6,11","dwell_ms":300,"pin":0,"filter":["mgmt","data"],"dedup":0,'
              '"ap_info_s":300}}')
ACK_FAILED_24 = P + ('{"event":"cmd_ack","cmd":"set","ok":false,"err":"bad dwell",'
                     '"config":{"band":"2.4GHz","channels":"1-13","dwell_ms":300}}')

V2_FIELDS = ("sub", "nf", "phy", "mcs", "bw", "rate", "ts_us", "sn", "fc_flags", "dur",
             "reason", "auth_alg", "auth_seq", "status", "eapol", "probe_fp", "ouis")

# The frames table exactly as every release before firmware v2 created it.
OLD_FRAMES_DDL = """
CREATE TABLE frames (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    received_at REAL    NOT NULL,
    sensor_id  TEXT,
    band       TEXT,
    frame_type TEXT,
    ch         INTEGER,
    rssi       INTEGER,
    seq        INTEGER,
    uptime_ms  INTEGER,
    src        TEXT,
    dst        TEXT,
    bssid      TEXT,
    ssid       TEXT
);
CREATE INDEX idx_frames_ts ON frames(received_at);
"""


def parse(line, band_line=None):
    p = Parser("ttyUSB0")
    if band_line:
        p.parse_line(band_line)
    return p.parse_line(line)


class TestParserV2Fields(unittest.TestCase):

    def test_beacon_radio_fields_are_typed(self):
        ev = parse(BEACON)
        self.assertEqual((ev.sub, ev.nf, ev.phy, ev.bw, ev.rate), (8, -95, "g", 20, 11))
        self.assertEqual((ev.ts_us, ev.sn, ev.fc_flags, ev.dur), (123456789, 100, 0, 314))
        self.assertIsNone(ev.mcs)
        self.assertIsNone(ev.reason)

    def test_deauth_carries_reason_mcs_and_retry_flag(self):
        ev = parse(DEAUTH)
        self.assertEqual((ev.reason, ev.mcs, ev.phy, ev.fc_flags, ev.sn), (7, 5, "n", 8, 9))
        self.assertIsNone(ev.rate)

    def test_auth_fields(self):
        ev = parse(AUTH)
        self.assertEqual((ev.auth_alg, ev.auth_seq, ev.status), (3, 1, 0))

    def test_eapol_message_on_a_data_frame(self):
        ev = parse(DATA)
        self.assertEqual((ev.frame_type, ev.eapol, ev.fc_flags), ("DATA", 1, 2))

    def test_probe_fingerprint_and_vendor_ouis(self):
        ev = parse(PROBE)
        self.assertEqual(ev.probe_fp, "13adc91c")
        self.assertEqual(ev.ouis, "0050F2,00163E")
        self.assertIsNone(ev.ssid)

    def test_v2_keys_do_not_linger_in_extra(self):
        for line in (BEACON, DEAUTH, AUTH, DATA, PROBE, MAXED):
            self.assertEqual(parse(line).extra, {}, line)

    def test_unknown_keys_still_land_in_extra(self):
        ev = parse(BEACON.replace('"dur":314', '"dur":314,"new_key":1'))
        self.assertEqual(ev.extra, {"new_key": 1})

    def test_a_v1_line_leaves_every_v2_field_null(self):
        ev = parse(V1_FRAME)
        self.assertEqual(ev.seq, 7)
        for name in V2_FIELDS:
            self.assertIsNone(getattr(ev, name), name)

    def test_field_limits_survive(self):
        ev = parse(MAXED)
        self.assertEqual((ev.seq, ev.ts_us, ev.sn, ev.fc_flags, ev.dur, ev.nf),
                         (4294967295, 4294967295, 4095, 255, 65535, -128))

    def test_wrongly_typed_values_become_null(self):
        bad = BEACON.replace('"nf":-95', '"nf":"loud"').replace('"phy":"g"', '"phy":5')
        bad = bad.replace('"dur":314', '"dur":314,"fp":7,"ouis":"0050F2"')
        ev = parse(bad)
        self.assertIsNone(ev.nf)
        self.assertIsNone(ev.phy)
        self.assertIsNone(ev.probe_fp)
        self.assertIsNone(ev.ouis)
        self.assertEqual(ev.sn, 100)

    def test_ouis_keep_only_strings(self):
        ev = parse(PROBE.replace('["0050F2","00163E"]', '["0050F2",5,""]'))
        self.assertEqual(ev.ouis, "0050F2")
        ev = parse(PROBE.replace('["0050F2","00163E"]', '[5]'))
        self.assertIsNone(ev.ouis)

    def test_public_feed_shape_is_unchanged(self):
        self.assertEqual(set(parse(BEACON).to_public()),
                         {"ts", "sensor", "band", "type", "ch", "rssi", "src", "dst",
                          "bssid", "ssid"})


class TestParserRouting(unittest.TestCase):

    def setUp(self):
        self.life, self.aps = [], []
        self.p = Parser("ttyUSB1", on_lifecycle=self.life.append,
                        on_ap_info=self.aps.append)

    def test_ap_info_goes_to_its_own_callback(self):
        self.p.parse_line(BOOT_5)
        before = time.time()
        self.assertIsNone(self.p.parse_line(AP_INFO))
        self.assertEqual([r["kind"] for r in self.life], ["boot"])
        (rec,) = self.aps
        self.assertEqual((rec["sensor_id"], rec["band"]), ("ttyUSB1", "5GHz"))
        self.assertGreaterEqual(rec["received_at"], before)
        self.assertEqual(rec["payload"]["pmf"], "capable")
        self.assertNotIn("event", rec["payload"])

    def test_ap_info_falls_back_to_lifecycle_without_its_callback(self):
        got = []
        p = Parser("ttyUSB1", on_lifecycle=got.append)
        p.parse_line(AP_INFO)
        self.assertEqual([r["kind"] for r in got], ["ap_info"])

    def test_telemetry_clock_and_acks_are_lifecycle_records(self):
        for line in (TELEMETRY, CLOCK, ACK_24):
            self.assertIsNone(self.p.parse_line(line))
        self.assertEqual([r["kind"] for r in self.life], ["telemetry", "clock_sync", "cmd_ack"])
        self.assertEqual(self.life[0]["payload"]["drop_queue"], 4)
        self.assertEqual(self.life[1]["payload"]["mono_us"], 30000123456)
        self.assertEqual(self.life[2]["payload"]["config"]["channels"], "1,6,11")
        self.assertEqual(self.aps, [])

    def test_a_successful_band_switch_relatches_the_band(self):
        self.p.parse_line(BOOT_5)
        self.p.parse_line(ACK_24)
        self.assertEqual(self.p.band, "2.4GHz")
        self.assertEqual(self.life[-1]["band"], "2.4GHz")
        self.assertEqual(self.p.parse_line(BEACON).band, "2.4GHz")

    def test_a_failed_command_keeps_the_band(self):
        self.p.parse_line(BOOT_5)
        self.p.parse_line(ACK_FAILED_24)
        self.assertEqual(self.p.band, "5GHz")

    def test_an_ack_without_a_usable_band_keeps_the_band(self):
        self.p.parse_line(BOOT_5)
        self.p.parse_line(P + '{"event":"cmd_ack","cmd":"get_config","ok":true}')
        self.p.parse_line(P + '{"event":"cmd_ack","cmd":"set","ok":true,"config":{"band":5}}')
        self.p.parse_line(P + '{"event":"cmd_ack","cmd":"set","ok":true,"config":"2.4GHz"}')
        self.assertEqual(self.p.band, "5GHz")


class StoreCase(unittest.TestCase):

    def setUp(self):
        self.tmp = TempDir()
        self.path = self.tmp.file("spectre.db")

    def tearDown(self):
        self.tmp.cleanup()

    def columns(self, table):
        db = sqlite3.connect(self.path)
        try:
            return [r[1] for r in db.execute(f"PRAGMA table_info({table})")]
        finally:
            db.close()

    def rows(self, sql):
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        try:
            return [dict(r) for r in db.execute(sql)]
        finally:
            db.close()

    def ap_rec(self, ts, line=AP_INFO, sensor="ttyUSB1", band="5GHz"):
        recs = []
        Parser(sensor, default_band=band, on_ap_info=recs.append).parse_line(line)
        recs[0]["received_at"] = ts
        return recs[0]


class TestFramesV2Storage(StoreCase):

    def test_v2_fields_round_trip(self):
        store = Store(self.path)
        try:
            store.insert_frames([parse(DEAUTH), parse(PROBE), parse(V1_FRAME)])
        finally:
            store.close()
        deauth, probe, v1 = self.rows("SELECT * FROM frames ORDER BY id")
        self.assertEqual((deauth["reason"], deauth["fc_flags"], deauth["mcs"], deauth["phy"]),
                         (7, 8, 5, "n"))
        self.assertEqual((deauth["sub"], deauth["nf"], deauth["bw"], deauth["ts_us"],
                          deauth["sn"], deauth["dur"], deauth["seq"]),
                         (12, -95, 20, 123456789, 9, 314, 2))
        self.assertEqual((probe["probe_fp"], probe["ouis"], probe["rate"]),
                         ("13adc91c", "0050F2,00163E", 11))
        for name in V2_FIELDS:
            self.assertIsNone(v1[name], name)
        self.assertEqual(v1["ssid"], "ExampleNet")

    def test_every_frame_kind_round_trips_its_own_fields(self):
        store = Store(self.path)
        try:
            store.insert_frames([parse(AUTH), parse(DATA)])
        finally:
            store.close()
        auth, data = self.rows("SELECT * FROM frames ORDER BY id")
        self.assertEqual((auth["auth_alg"], auth["auth_seq"], auth["status"]), (3, 1, 0))
        self.assertEqual((data["eapol"], data["frame_type"]), (1, "DATA"))

    def test_row_tuple_lines_up_with_the_insert(self):
        ev = parse(MAXED)
        row = ev.to_row()
        self.assertEqual(len(row), 12 + len(V2_FIELDS))
        self.assertEqual(row[12:], tuple(getattr(ev, n) for n in V2_FIELDS))


class TestMigration(StoreCase):

    def make_old_db(self):
        db = sqlite3.connect(self.path)
        db.executescript(OLD_FRAMES_DDL)
        db.execute("INSERT INTO frames(received_at,sensor_id,band,frame_type,ch,rssi,seq,"
                   "uptime_ms,src,dst,bssid,ssid) VALUES(100.5,'ttyUSB0','2.4GHz','BEACON',"
                   "6,-50,1,10,'00:00:5E:00:53:01','FF:FF:FF:FF:FF:FF','00:00:5E:00:53:01',"
                   "'ExampleNet')")
        db.commit()
        db.close()

    def test_an_old_database_gains_the_v2_columns(self):
        self.make_old_db()
        Store(self.path).close()
        cols = self.columns("frames")
        for name in V2_FIELDS:
            self.assertIn(name, cols)
        self.assertEqual(cols[:13], ["id", "received_at", "sensor_id", "band", "frame_type",
                                     "ch", "rssi", "seq", "uptime_ms", "src", "dst",
                                     "bssid", "ssid"])

    def test_old_rows_survive_with_null_v2_fields(self):
        self.make_old_db()
        store = Store(self.path)
        try:
            store.insert_frames([parse(DEAUTH)])
        finally:
            store.close()
        old, new = self.rows("SELECT * FROM frames ORDER BY id")
        self.assertEqual((old["received_at"], old["ssid"], old["seq"]), (100.5, "ExampleNet", 1))
        for name in V2_FIELDS:
            self.assertIsNone(old[name], name)
        self.assertEqual(new["reason"], 7)

    def test_migration_is_idempotent(self):
        self.make_old_db()
        Store(self.path).close()
        first = self.columns("frames")
        Store(self.path).close()
        self.assertEqual(self.columns("frames"), first)
        self.assertEqual(len(first), len(set(first)))
        self.assertEqual(len(self.rows("SELECT id FROM frames")), 1)

    def test_a_fresh_database_has_the_same_columns_as_a_migrated_one(self):
        self.make_old_db()
        Store(self.path).close()
        migrated = self.columns("frames")
        fresh = self.tmp.file("fresh.db")
        Store(fresh).close()
        self.path = fresh
        self.assertEqual(self.columns("frames"), migrated)

    def test_an_old_database_gains_the_ap_info_table(self):
        self.make_old_db()
        Store(self.path).close()
        self.assertIn("bssid", self.columns("ap_info"))


class TestApInfoStore(StoreCase):

    def setUp(self):
        super().setUp()
        self.store = Store(self.path)

    def tearDown(self):
        self.store.close()
        super().tearDown()

    def test_round_trip_with_typed_columns(self):
        self.store.insert_ap_info(self.ap_rec(50.0))
        (row,) = self.store.ap_info()
        self.assertEqual((row["sensor_id"], row["band"], row["bssid"], row["why"]),
                         ("ttyUSB1", "5GHz", "00:00:5E:00:53:01", "new"))
        self.assertEqual((row["ch"], row["ds_ch"], row["ssid"], row["sec"], row["pmf"]),
                         (36, 36, "LabNet", "WPA2/WPA3", "capable"))
        self.assertEqual((row["wpa1"], row["ht"], row["vht"], row["he"], row["eht"], row["wps"]),
                         (0, 1, 0, 1, 0, 1))
        self.assertEqual(row["hash"], "40a7e2da")
        self.assertEqual(row["payload"]["csa"], {"mode": 1, "ch": 149, "count": 5})
        self.assertEqual(row["payload"]["akm"], ["PSK", "SAE"])

    def test_hidden_ssid_and_lowercase_bssid_are_normalized(self):
        self.store.insert_ap_info(self.ap_rec(50.0, line=AP_INFO_HIDDEN))
        (row,) = self.store.ap_info()
        self.assertIsNone(row["ssid"])
        self.assertEqual(row["bssid"], "00:00:5E:00:53:09")
        self.assertEqual((row["wpa1"], row["vht"], row["eht"], row["ht"]), (1, 1, 1, 0))

    def test_json_booleans_are_not_channels(self):
        line = AP_INFO.replace('"ch":36,"ds_ch":36', '"ch":true,"ds_ch":"36"')
        self.store.insert_ap_info(self.ap_rec(50.0, line=line))
        (row,) = self.store.ap_info()
        self.assertEqual((row["ch"], row["ds_ch"]), (None, None))
        self.assertEqual(row["payload"]["ch"], True)

    def test_rows_come_back_in_time_order_and_since_filters(self):
        self.store.insert_ap_info(self.ap_rec(30.0, line=AP_INFO_HIDDEN))
        self.store.insert_ap_info(self.ap_rec(10.0))
        self.store.insert_ap_info(self.ap_rec(20.0))
        self.assertEqual([r["received_at"] for r in self.store.ap_info()], [10.0, 20.0, 30.0])
        self.assertEqual([r["received_at"] for r in self.store.ap_info(since=20.0)], [20.0, 30.0])
        self.assertEqual(len(self.store.ap_info(limit=2)), 2)

    def test_pruned_with_the_raw_window(self):
        now = time.time()
        self.store.insert_ap_info(self.ap_rec(now - 3 * 3600))
        self.store.insert_ap_info(self.ap_rec(now - 60))
        with mock.patch.object(self.store, "_disk_used_percent", return_value=10.0):
            self.store.prune(raw_retention_hours=2, disk_guard_percent=85)
        self.assertEqual([r["received_at"] for r in self.store.ap_info()], [now - 60])

    def test_disk_guard_trims_ap_info_too(self):
        now = time.time()
        for h in (0, 5, 10, 20):
            self.store.insert_ap_info(self.ap_rec(now - h * 3600 - 60))
        usage = iter([95.0, 95.0, 50.0])
        with mock.patch.object(self.store, "_disk_used_percent",
                               side_effect=lambda: next(usage)):
            self.store.prune(raw_retention_hours=24, disk_guard_percent=85)
        self.assertEqual(len(self.store.ap_info()), 2)


class TestWiring(StoreCase):

    def setUp(self):
        super().setUp()
        self.store = Store(self.path)
        self.pipe = Pipeline(self.store, Config(self.store))

    def tearDown(self):
        self.store.close()
        super().tearDown()

    def feed(self, reader, text):
        r, w = os.pipe()
        try:
            os.set_blocking(r, False)
            reader._fd = r
            os.write(w, text.encode())
            reader._on_readable()
        finally:
            reader._fd = None
            os.close(r)
            os.close(w)

    def test_pipeline_records_ap_info(self):
        self.pipe.record_ap_info(self.ap_rec(5.0))
        self.assertEqual(self.store.ap_info(), [])        # written by the next flush
        self.pipe.flush()
        self.assertEqual([r["bssid"] for r in self.store.ap_info()], ["00:00:5E:00:53:01"])

    def test_pipeline_ap_info_reaches_the_detection_engine(self):
        # An AP that moves channel between two readings is not an RSSI jump.
        def beacon(ts, rssi):
            return Event(received_at=ts, sensor_id="ttyUSB1", band="5GHz",
                         frame_type="BEACON", ch=36, rssi=rssi, src="00:00:5E:00:53:01",
                         dst="FF:FF:FF:FF:FF:FF", bssid="00:00:5E:00:53:01")
        t0 = 1_700_000_100.0
        self.pipe.record_ap_info(self.ap_rec(t0))
        self.assertEqual(self.pipe.engine.feed(beacon(t0 + 1, -15)), [])
        moved = self.ap_rec(t0 + 2, line=AP_INFO.replace('"ds_ch":36', '"ds_ch":149'))
        self.pipe.record_ap_info(moved)
        self.assertEqual(
            [t.rule for t in self.pipe.engine.feed(beacon(t0 + 3, -75))
             + self.pipe.engine.feed(beacon(t0 + 3.1, -75))], [])
        self.pipe.record_ap_info(self.ap_rec(t0 + 4))
        self.assertEqual(
            [t.rule for t in self.pipe.engine.feed(beacon(t0 + 5, -80))
             + self.pipe.engine.feed(beacon(t0 + 5.1, -80))], ["anomaly"])

    def test_serial_reader_routes_every_v2_line(self):
        reader = SerialReader("/dev/ttyUSB1", 460800, self.pipe)
        self.feed(reader, "\n".join([BOOT_5, AP_INFO, TELEMETRY, CLOCK, ACK_24, DEAUTH]) + "\n")
        self.pipe.flush()
        self.assertEqual([r["bssid"] for r in self.store.ap_info()], ["00:00:5E:00:53:01"])
        self.assertEqual([r["kind"] for r in self.store.board_events()],
                         ["boot", "telemetry", "clock_sync", "cmd_ack"])
        (row,) = self.rows("SELECT band, reason FROM frames")
        self.assertEqual(row, {"band": "2.4GHz", "reason": 7})

    def test_replay_routes_ap_info(self):
        path = self.tmp.file("capture.log")
        with open(path, "w") as fh:
            fh.write(BOOT_5 + "\n" + AP_INFO + "\n")
        asyncio.run(ReplaySource(self.pipe, path, speed=100.0, loop=False).run())
        self.pipe.flush()
        self.assertEqual(len(self.store.ap_info()), 1)
        self.assertEqual([r["kind"] for r in self.store.board_events()], ["boot"])

    def test_simulator_parsers_route_ap_info(self):
        src = SimSource(self.pipe)
        for parser in src._parsers.values():
            parser.parse_line(AP_INFO)
        self.pipe.flush()
        self.assertEqual(sorted(r["sensor_id"] for r in self.store.ap_info()),
                         ["sim-2.4GHz", "sim-5GHz"])


class TestBaud(unittest.TestCase):

    def test_high_speeds_are_mapped(self):
        self.assertEqual(reader_mod._BAUD_MAP[460800], termios.B460800)
        self.assertEqual(reader_mod._BAUD_MAP[921600], termios.B921600)
        self.assertEqual(reader_mod._BAUD_MAP[115200], termios.B115200)

    def test_an_unsupported_baud_fails_loudly(self):
        with self.assertRaises(ValueError):
            SerialReader("/dev/ttyUSB0", 250000, pipeline=mock.Mock())

    def test_the_port_is_opened_at_the_requested_speed(self):
        master, slave = os.openpty()
        name = os.ttyname(slave)
        try:
            with mock.patch.object(reader_mod.fcntl, "ioctl"):
                fd = _open_serial(name, 460800)
            try:
                attrs = termios.tcgetattr(fd)
                self.assertEqual((attrs[4], attrs[5]), (termios.B460800, termios.B460800))
            finally:
                os.close(fd)
        finally:
            os.close(master)
            os.close(slave)


class TestSend(unittest.TestCase):

    def setUp(self):
        self.master, self.slave = os.openpty()
        tty.setraw(self.slave)
        self.reader = SerialReader("/dev/ttyUSB0", 460800, pipeline=mock.Mock())
        self.reader._fd = self.slave

    def tearDown(self):
        self.reader._fd = None
        os.close(self.master)
        os.close(self.slave)

    def read_master(self, want):
        """Read up to *want* bytes; returns short instead of blocking forever."""
        out = b""
        deadline = time.monotonic() + 1
        while len(out) < want:
            left = deadline - time.monotonic()
            if left <= 0 or not select.select([self.master], [], [], left)[0]:
                break
            out += os.read(self.master, 4096)
        return out

    def test_a_dict_goes_out_as_one_compact_json_line(self):
        n = self.reader.send({"cmd": "set", "id": "a1", "channels": [1, 6, 11]})
        expected = b'{"cmd":"set","id":"a1","channels":[1,6,11]}\n'
        self.assertEqual(n, len(expected))
        self.assertEqual(self.read_master(len(expected)), expected)

    def test_a_string_goes_out_unchanged_plus_newline(self):
        self.reader.send('{"cmd":"get_config"}')
        self.assertEqual(self.read_master(21), b'{"cmd":"get_config"}\n')

    def test_line_breaks_inside_a_command_are_refused(self):
        for bad in ('{"cmd":"reboot"}\n{"cmd":"reboot"}', '{"cmd":"get_config"}\r'):
            with self.assertRaises(ValueError):
                self.reader.send(bad)

    def test_the_board_line_limit_is_enforced(self):
        limit = reader_mod.MAX_COMMAND_BYTES
        self.assertEqual(limit, 254)
        self.reader.send("x" * limit)
        self.assertEqual(len(self.read_master(limit + 1)), limit + 1)
        with self.assertRaises(ValueError):
            self.reader.send("x" * (limit + 1))
        with self.assertRaises(ValueError):
            self.reader.send(chr(0xE9) * (limit // 2 + 1))

    def test_sending_on_a_closed_port_raises(self):
        self.reader._fd = None
        with self.assertRaises(RuntimeError):
            self.reader.send({"cmd": "get_config"})

    def test_short_writes_are_completed(self):
        written = []

        def one_byte(fd, data):
            written.append(bytes(data[:1]))
            return 1

        with mock.patch.object(reader_mod.os, "write", side_effect=one_byte):
            self.reader.send('{"cmd":"reboot"}')
        self.assertEqual(b"".join(written), b'{"cmd":"reboot"}\n')

    def test_a_full_output_buffer_is_waited_out(self):
        calls = {"n": 0}
        real_write = os.write

        def busy_then_ok(fd, data):
            calls["n"] += 1
            if calls["n"] == 1:
                raise BlockingIOError
            return real_write(fd, data)

        with mock.patch.object(reader_mod.os, "write", side_effect=busy_then_ok):
            self.reader.send('{"cmd":"get_config"}')
        self.assertEqual(self.read_master(21), b'{"cmd":"get_config"}\n')

    def test_a_port_that_never_drains_times_out(self):
        with mock.patch.object(reader_mod.os, "write", side_effect=BlockingIOError), \
                mock.patch.object(reader_mod, "SEND_TIMEOUT_S", 0.05):
            with self.assertRaises(TimeoutError):
                self.reader.send('{"cmd":"get_config"}')

    def test_concurrent_sends_never_interleave(self):
        out = []

        def slow(fd, data):
            out.append(bytes(data[:1]))
            time.sleep(0.0005)
            return 1

        lines = ['{"cmd":"set","id":"aaaaaaaa"}', '{"cmd":"set","id":"bbbbbbbb"}']
        with mock.patch.object(reader_mod.os, "write", side_effect=slow):
            threads = [threading.Thread(target=self.reader.send, args=(s,)) for s in lines]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
        got = b"".join(out).decode().splitlines()
        self.assertEqual(sorted(got), sorted(lines))


if __name__ == "__main__":
    unittest.main()
