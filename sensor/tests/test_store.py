"""SQLite persistence, retention and search. Author: gurvinny"""
import time
import unittest
from unittest import mock

from _support import TempDir, frame

from spectre.models import Threat
from spectre.store import Store, _fts_match


def device(mac, last_seen, **kw):
    d = {"mac": mac, "first_seen": last_seen, "last_seen": last_seen,
         "bands": "2.4GHz", "last_rssi": -50, "min_rssi": -50, "max_rssi": -50,
         "frames": 1, "is_random": 0, "last_ssid": None}
    d.update(kw)
    return d


def ap(bssid, last_seen, ssid="ExampleNet", **kw):
    a = {"bssid": bssid, "ssid": ssid, "band": "2.4GHz", "channels": "6",
         "first_seen": last_seen, "last_seen": last_seen, "last_rssi": -40,
         "beacons": 1, "is_known": 0}
    a.update(kw)
    return a


class StoreCase(unittest.TestCase):

    def setUp(self):
        self.tmp = TempDir()
        self.store = Store(self.tmp.file("spectre.db"))

    def tearDown(self):
        self.store.close()
        self.tmp.cleanup()


class TestFrames(StoreCase):

    def test_roundtrip_newest_first_with_filters(self):
        evs = [frame(100, type="BEACON", ch=1, src="00:00:00:00:00:01"),
               frame(101, band="5GHz", type="DEAUTH", ch=36, src="00:00:00:00:00:02"),
               frame(102, type="DEAUTH", ch=6, src="00:00:00:00:00:03")]
        self.assertEqual(self.store.insert_frames(evs), 3)
        self.assertEqual(self.store.insert_frames([]), 0)
        rows = self.store.recent_frames()
        self.assertEqual([r["src"] for r in rows],
                         ["00:00:00:00:00:03", "00:00:00:00:00:02", "00:00:00:00:00:01"])
        self.assertEqual([r["src"] for r in self.store.recent_frames(frame_type="deauth")],
                         ["00:00:00:00:00:03", "00:00:00:00:00:02"])
        self.assertEqual([r["ch"] for r in self.store.recent_frames(band="5GHz")], [36])
        self.assertEqual(len(self.store.recent_frames(limit=1)), 1)

    def test_prune_deletes_only_frames_past_retention(self):
        now = time.time()
        self.store.insert_frames([frame(now - 3 * 3600, type="BEACON"),
                                  frame(now - 60, type="BEACON")])
        with mock.patch.object(self.store, "_disk_used_percent", return_value=10.0):
            report = self.store.prune(raw_retention_hours=2, disk_guard_percent=85)
        self.assertEqual((report["deleted"], report["guard_deleted"]), (1, 0))
        self.assertEqual(len(self.store.recent_frames()), 1)

    def test_disk_guard_halves_the_window_until_under_threshold(self):
        now = time.time()
        self.store.insert_frames([frame(now - h * 3600 - 60, type="BEACON")
                                  for h in (0, 5, 10, 20)])
        usage = iter([95.0, 95.0, 50.0])  # over, over, then under
        with mock.patch.object(self.store, "_disk_used_percent",
                               side_effect=lambda: next(usage)):
            report = self.store.prune(raw_retention_hours=24, disk_guard_percent=85)
        # 24h keeps all four; 12h drops the 20h one; 6h drops the 10h one.
        self.assertEqual((report["deleted"], report["guard_deleted"],
                          report["window_hours"]), (0, 2, 6))
        self.assertEqual(len(self.store.recent_frames()), 2)

    def test_disk_guard_never_goes_below_one_hour(self):
        now = time.time()
        self.store.insert_frames([frame(now - 30 * 60, type="BEACON")])
        with mock.patch.object(self.store, "_disk_used_percent", return_value=99.0):
            report = self.store.prune(raw_retention_hours=48, disk_guard_percent=85)
        self.assertEqual(report["window_hours"], 1.0)
        self.assertEqual(len(self.store.recent_frames()), 1)


class TestInventory(StoreCase):

    def test_device_upsert_merges_rssi_range_and_keeps_first_seen(self):
        self.store.upsert_devices([device("AA:00:00:00:00:01", 100,
                                          min_rssi=-70, max_rssi=-40)])
        self.store.upsert_devices([device("AA:00:00:00:00:01", 200, first_seen=200,
                                          min_rssi=-60, max_rssi=-50, frames=9)])
        self.store.upsert_devices([device("AA:00:00:00:00:01", 300, first_seen=300,
                                          min_rssi=-90, max_rssi=-30, frames=12)])
        [row] = self.store.list_devices(since=None)
        self.assertEqual((row["first_seen"], row["last_seen"], row["min_rssi"],
                          row["max_rssi"], row["frames"]), (100, 300, -90, -30, 12))

    def test_device_upsert_never_narrows_the_rssi_range(self):
        self.store.upsert_devices([device("AA:00:00:00:00:01", 100,
                                          min_rssi=-70, max_rssi=-40)])
        self.store.upsert_devices([device("AA:00:00:00:00:01", 200,
                                          min_rssi=-60, max_rssi=-50)])
        [row] = self.store.list_devices()
        self.assertEqual((row["min_rssi"], row["max_rssi"]), (-70, -40))

    def test_ap_upsert_overwrites_live_fields(self):
        self.store.upsert_aps([ap("00:00:5E:00:53:01", 100)])
        self.store.upsert_aps([ap("00:00:5E:00:53:01", 200, ssid="Renamed",
                                  beacons=50, is_known=1)])
        [row] = self.store.list_aps()
        self.assertEqual((row["ssid"], row["beacons"], row["is_known"], row["first_seen"]),
                         ("Renamed", 50, 1, 100))

    def test_scope_bounds_split_active_from_archived(self):
        self.store.upsert_devices([device("AA:00:00:00:00:01", 100),
                                   device("AA:00:00:00:00:02", 200),
                                   device("AA:00:00:00:00:03", 300)])
        macs = lambda rows: [r["mac"][-2:] for r in rows]  # noqa: E731
        self.assertEqual(macs(self.store.list_devices(since=200)), ["03", "02"])
        self.assertEqual(macs(self.store.list_devices(until=200)), ["01"])
        self.assertEqual(macs(self.store.list_devices()), ["03", "02", "01"])
        self.assertEqual(macs(self.store.list_devices(limit=1)), ["03"])

    def test_prune_inventory_exempts_muted_devices_and_known_aps(self):
        old, new = time.time() - 10 * 86400, time.time()
        self.store.upsert_devices([device("AA:00:00:00:00:01", old),
                                   device("AA:00:00:00:00:02", old),
                                   device("AA:00:00:00:00:03", new)])
        self.store.upsert_aps([ap("00:00:5E:00:53:01", old),
                               ap("00:00:5E:00:53:02", old, is_known=1),
                               ap("00:00:5E:00:53:03", new)])
        report = self.store.prune_inventory(86400, 86400, ["aa:00:00:00:00:02"])
        self.assertEqual(report, {"devices_purged": 1, "aps_purged": 1})
        self.assertEqual({d["mac"] for d in self.store.list_devices()},
                         {"AA:00:00:00:00:02", "AA:00:00:00:00:03"})
        self.assertEqual({a["bssid"] for a in self.store.list_aps()},
                         {"00:00:5E:00:53:02", "00:00:5E:00:53:03"})


class TestThreatsAndSummaries(StoreCase):

    def test_threat_roundtrip_with_rank_and_detail(self):
        t = Threat(ts=500, rule="evil_twin", severity="critical", title="x",
                   bssid="B", detail={"rogue_bssid": "B", "known": [1, 2]})
        tid = self.store.insert_threat(t, wazuh_sent=True)
        [row] = self.store.list_threats()
        self.assertEqual((row["id"], row["rank"], row["wazuh_sent"], row["detail"]),
                         (tid, 1, 1, {"rogue_bssid": "B", "known": [1, 2]}))

    def test_threats_list_newest_first_and_count_since(self):
        for ts in (100, 300, 200):
            self.store.insert_threat(Threat(ts=ts, rule="r", severity="low", title=str(ts)))
        self.assertEqual([r["ts"] for r in self.store.list_threats()], [300, 200, 100])
        self.assertEqual(self.store.count_threats_since(200), 2)

    def test_summaries_return_oldest_first_from_the_latest_n(self):
        for ts in (1, 2, 3):
            self.store.insert_summary({"ts": ts, "fps": ts * 10})
        self.assertEqual([s["fps"] for s in self.store.recent_summaries(2)], [20, 30])


class TestKnownNetworksConfigSessions(StoreCase):

    def test_known_networks_store_bssid_uppercase(self):
        rid = self.store.add_known_network("Home", "aa:bb:cc:dd:ee:ff", "2.4GHz", "n")
        self.store.add_known_network("Home", None, None)
        rows = self.store.list_known_networks()
        self.assertEqual([(r["id"], r["bssid"]) for r in rows],
                         [(rid, "AA:BB:CC:DD:EE:FF"), (rid + 1, None)])

    def test_delete_known_by_bssid_removes_every_entry(self):
        self.store.add_known_network("A", "aa:bb:cc:dd:ee:ff", None)
        self.store.add_known_network("B", "AA:BB:CC:DD:EE:FF", None)
        self.store.add_known_network("C", "11:22:33:44:55:66", None)
        self.assertEqual(self.store.delete_known_by_bssid("aa:bb:cc:dd:ee:ff"), 2)
        self.assertEqual([r["ssid"] for r in self.store.list_known_networks()], ["C"])

    def test_delete_known_by_id(self):
        rid = self.store.add_known_network("A", None, None)
        self.store.delete_known_network(rid)
        self.assertEqual(self.store.list_known_networks(), [])

    def test_config_values_roundtrip_as_json(self):
        for key, value in (("i", 3), ("f", 1.5), ("b", False), ("l", ["X"]), ("s", "v")):
            self.store.set_config(key, value)
            self.assertEqual(self.store.get_config(key), value)
        self.assertEqual(self.store.get_config("missing", "dflt"), "dflt")

    def test_sessions_expire(self):
        self.store.create_session("live", "admin", 3600)
        self.store.create_session("dead", "admin", -1)
        self.assertEqual(self.store.get_session("live")["username"], "admin")
        self.assertIsNone(self.store.get_session("dead"))
        self.assertIsNone(self.store.get_session("nope"))
        self.store.delete_session("live")
        self.assertIsNone(self.store.get_session("live"))

    def test_prune_removes_expired_sessions(self):
        self.store.create_session("dead", "admin", -1)
        with mock.patch.object(self.store, "_disk_used_percent", return_value=1.0):
            self.store.prune(48, 85)
        with self.store._lock:
            n = self.store._db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        self.assertEqual(n, 0)

    def test_users(self):
        self.assertFalse(self.store.has_users())
        self.store.upsert_user("admin", "h1", "s1")
        self.store.upsert_user("admin", "h2", "s2")
        self.assertTrue(self.store.has_users())
        self.assertEqual({k: self.store.get_user("admin")[k] for k in ("pwd_hash", "salt")},
                         {"pwd_hash": "h2", "salt": "s2"})


class TestSearch(StoreCase):

    def setUp(self):
        super().setUp()
        self.store.upsert_devices([device("2A:2F:D0:11:22:33", 100, last_ssid="CoffeeShop",
                                          is_random=1)])
        self.store.upsert_aps([ap("00:00:5E:00:53:01", 100, ssid="ExampleNet")])
        self.store.insert_threat(Threat(ts=1, rule="deauth_flood", severity="high",
                                        title="Deauth flood on 00:00:5E:00:53:01"))
        self.store.add_known_network("TrustedHome", "11:22:33:44:55:66", None)

    def kinds(self, q):
        return sorted({(r["kind"], r["ref"]) for r in self.store.search(q)})

    def test_partial_colonless_mac_prefix_finds_the_device(self):
        self.assertEqual(self.kinds("2a2fd0"), [("device", "2A:2F:D0:11:22:33")])

    def test_ssid_search_finds_ap_and_threat_by_bssid(self):
        self.assertIn(("ap", "00:00:5E:00:53:01"), self.kinds("ExampleNet"))
        self.assertIn("threat", {k for k, _ in self.kinds("deauth")})
        self.assertEqual({k for k, _ in self.kinds("TrustedHome")}, {"known"})

    def test_hostile_query_is_neutralised(self):
        self.assertEqual(_fts_match('x" OR 1=1; DROP TABLE devices; --'),
                         "x* OR* 1* 1* DROP* TABLE* devices*")
        self.assertEqual(self.store.search('"*NEAR('), [])
        self.assertEqual(self.store.search(""), [])
        self.assertEqual(len(self.store.list_devices()), 1)

    def test_purged_device_leaves_the_index(self):
        self.store.prune_inventory(1, 10**9, [])
        self.assertEqual(self.kinds("2a2fd0"), [])

    def test_like_fallback_without_fts(self):
        self.store._fts = False
        self.assertEqual(self.kinds("CoffeeShop"), [("device", "2A:2F:D0:11:22:33")])
        self.assertEqual(self.kinds("Example%"), [("ap", "00:00:5E:00:53:01")])
        # A user's "_" must not act as a LIKE single-character wildcard.
        self.assertEqual(self.kinds("Ex_mpleNet"), [])

    def test_reindex_rebuilds_from_durable_tables(self):
        with self.store._lock:
            self.store._db.execute("DELETE FROM search_fts")
        self.store._reindex_all()
        self.assertEqual(self.kinds("2a2fd0"), [("device", "2A:2F:D0:11:22:33")])


if __name__ == "__main__":
    unittest.main()
