"""REST + WebSocket surface, driven through the real app. Author: gurvinny"""
import time
import unittest

from _support import TempDir, UdpSink, frame

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from spectre.api import SESSION_COOKIE, create_app
from spectre.config import Config
from spectre.pipeline import Pipeline
from spectre.store import Store

PASSWORD = "correct-horse-battery"
ROGUE = "00:00:5E:00:53:66"
AP = "00:00:5E:00:53:01"

DATA_ROUTES = ["/api/overview", "/api/frames", "/api/devices", "/api/access-points",
               "/api/search?q=x", "/api/threats", "/api/channels", "/api/summaries",
               "/api/settings", "/api/known-networks", "/api/muted-devices"]


class ApiCase(unittest.TestCase):

    def setUp(self):
        self.tmp = TempDir()
        self.sink = UdpSink()
        self.store = Store(self.tmp.file("spectre.db"))
        self.cfg = Config(self.store)
        self.cfg.set("wazuh_host", "127.0.0.1")
        self.cfg.set("wazuh_port", self.sink.port)
        self.pipe = Pipeline(self.store, self.cfg)
        self.client = TestClient(create_app(self.store, self.cfg, self.pipe))

    def tearDown(self):
        self.client.close()
        self.store.close()
        self.sink.close()
        self.tmp.cleanup()

    def setup_admin(self, **extra):
        r = self.client.post("/api/setup", json={"password": PASSWORD, **extra})
        self.assertEqual(r.status_code, 200, r.text)
        return r


class TestSetupAndLogin(ApiCase):

    def test_health_and_status_are_public(self):
        self.assertEqual(self.client.get("/health").json()["status"], "ok")
        self.assertEqual(self.client.get("/api/status").json()["setup_complete"], False)

    def test_every_data_route_needs_a_session(self):
        self.setup_admin()
        self.client.cookies.clear()
        for path in DATA_ROUTES:
            self.assertEqual(self.client.get(path).status_code, 401, path)
        self.assertEqual(self.client.put("/api/settings", json={}).status_code, 401)
        self.assertEqual(self.client.post("/api/known-networks",
                                          json={"ssid": "x"}).status_code, 401)
        self.assertEqual(self.client.post("/api/password", json={}).status_code, 401)

    def test_forged_cookie_is_rejected(self):
        self.setup_admin()
        self.client.cookies.set(SESSION_COOKIE, "forged")
        self.assertEqual(self.client.get("/api/overview").status_code, 401)

    def test_setup_rejects_short_password_and_runs_once(self):
        r = self.client.post("/api/setup", json={"password": "12345"})
        self.assertEqual(r.status_code, 400)
        self.assertFalse(self.store.has_users())
        self.setup_admin()
        again = self.client.post("/api/setup", json={"password": "another-one"})
        self.assertEqual(again.status_code, 409)
        self.assertEqual(self.client.post("/api/login",
                                          json={"password": PASSWORD}).status_code, 200)

    def test_setup_issues_an_httponly_session_and_seeds_wazuh(self):
        r = self.setup_admin(wazuh_host="siem.test", wazuh_port=1514, ignored="x")
        cookie = r.headers["set-cookie"]
        self.assertIn(SESSION_COOKIE + "=", cookie)
        self.assertIn("HttpOnly", cookie)
        self.assertIn("samesite=lax", cookie.lower())
        self.assertEqual((self.cfg("wazuh_host"), self.cfg("wazuh_port")),
                         ("siem.test", 1514))
        self.assertIsNone(self.store.get_config("ignored"))
        self.assertEqual(self.client.get("/api/status").json()["setup_complete"], True)
        self.assertEqual(self.client.get("/api/overview").status_code, 200)

    def test_login_logout(self):
        self.setup_admin()
        self.client.cookies.clear()
        self.assertEqual(self.client.post("/api/login",
                                          json={"password": "wrong"}).status_code, 401)
        self.assertEqual(self.client.post("/api/login", json={}).status_code, 401)
        self.assertEqual(self.client.post("/api/login",
                                          json={"password": PASSWORD}).status_code, 200)
        token = self.client.cookies.get(SESSION_COOKIE)
        self.assertIsNotNone(self.store.get_session(token))
        self.client.post("/api/logout")
        self.assertIsNone(self.store.get_session(token))
        self.client.cookies.set(SESSION_COOKIE, token)
        self.assertEqual(self.client.get("/api/overview").status_code, 401)

    def test_login_before_setup_fails(self):
        self.assertEqual(self.client.post("/api/login",
                                          json={"password": PASSWORD}).status_code, 401)

    def test_password_change_needs_the_current_one(self):
        self.setup_admin()
        bad = self.client.post("/api/password", json={"current": "nope", "new": "abcdefgh"})
        self.assertEqual(bad.status_code, 401)
        short = self.client.post("/api/password", json={"current": PASSWORD, "new": "abc"})
        self.assertEqual(short.status_code, 400)
        ok = self.client.post("/api/password", json={"current": PASSWORD,
                                                     "new": "new-password-1"})
        self.assertEqual(ok.status_code, 200)
        self.client.cookies.clear()
        self.assertEqual(self.client.post("/api/login",
                                          json={"password": PASSWORD}).status_code, 401)
        self.assertEqual(self.client.post("/api/login", json={
            "password": "new-password-1"}).status_code, 200)


class TestData(ApiCase):

    def setUp(self):
        super().setUp()
        self.setup_admin()

    def test_frames_limit_is_capped(self):
        t = time.time()
        self.store.insert_frames([frame(t, type="BEACON", ch=1) for _ in range(1005)])
        self.assertEqual(len(self.client.get("/api/frames?limit=5000").json()["frames"]),
                         1000)
        self.assertEqual(len(self.client.get("/api/frames?limit=3").json()["frames"]), 3)
        only = self.client.get("/api/frames?type=deauth").json()["frames"]
        self.assertEqual(only, [])

    def test_inventory_scopes(self):
        now = time.time()
        rows = [{"mac": m, "first_seen": ts, "last_seen": ts, "bands": "2.4GHz",
                 "last_rssi": -50, "min_rssi": -50, "max_rssi": -50, "frames": 1,
                 "is_random": 0, "last_ssid": None}
                for m, ts in (("AA:00:00:00:00:01", now), ("AA:00:00:00:00:02", now - 3600))]
        self.store.upsert_devices(rows)
        get = lambda s: [d["mac"][-2:] for d in  # noqa: E731
                         self.client.get(f"/api/devices?scope={s}").json()["devices"]]
        self.assertEqual((get("active"), get("archived"), get("all")),
                         (["01"], ["02"], ["01", "02"]))

    def test_settings_roundtrip_reaches_the_engine_live(self):
        r = self.client.put("/api/settings", json={"deauth_threshold": 3})
        self.assertEqual(r.json()["settings"]["deauth_threshold"], 3)
        self.assertEqual(self.client.get("/api/settings").json()["settings"]
                         ["deauth_threshold"], 3)
        t = time.time()
        for i in range(3):
            self.pipe.ingest(frame(t + i * 0.01, type="DEAUTH", src=AP, bssid=AP))
        self.assertEqual([x["rule"] for x in self.client.get("/api/threats").json()
                          ["threats"]], ["deauth_flood"])

    def test_known_network_add_arms_evil_twin_and_delete_disarms(self):
        self.assertEqual(self.client.post("/api/known-networks", json={}).status_code, 400)
        r = self.client.post("/api/known-networks",
                             json={"ssid": "ExampleNet", "bssid": AP.lower()})
        rid = r.json()["id"]
        self.pipe.ingest(frame(time.time(), type="BEACON", src=ROGUE, bssid=ROGUE,
                               ssid="ExampleNet"))
        self.assertEqual([x["bssid"] for x in self.client.get("/api/threats").json()
                          ["threats"]], [ROGUE])
        self.client.delete(f"/api/known-networks/{rid}")
        self.assertEqual(self.pipe.engine.rules[1]._allow, {})

    def test_untrust_by_bssid(self):
        self.client.post("/api/known-networks", json={"ssid": "A", "bssid": AP})
        r = self.client.delete(f"/api/known-networks/by-bssid/{AP.lower()}")
        self.assertEqual(r.json()["removed"], 1)
        self.assertEqual(self.client.get("/api/known-networks").json()
                         ["known_networks"], [])

    def test_muted_devices_are_uppercased_deduped_and_removable(self):
        self.assertEqual(self.client.post("/api/muted-devices", json={}).status_code, 400)
        self.client.post("/api/muted-devices", json={"mac": "aa:bb:cc:dd:ee:ff"})
        r = self.client.post("/api/muted-devices", json={"mac": "AA:BB:CC:DD:EE:FF"})
        self.assertEqual(r.json()["muted_devices"], ["AA:BB:CC:DD:EE:FF"])
        self.assertEqual(self.pipe.engine.rules[3]._muted, {"AA:BB:CC:DD:EE:FF"})
        r = self.client.delete("/api/muted-devices/aa:bb:cc:dd:ee:ff")
        self.assertEqual(r.json()["muted_devices"], [])
        self.assertEqual(self.pipe.engine.rules[3]._muted, set())

    def test_search_and_channels(self):
        self.pipe.ingest(frame(time.time(), type="BEACON", ch=6, src=AP, bssid=AP,
                               ssid="ExampleNet"))
        self.pipe._flush_inventory()
        res = self.client.get("/api/search?q=examplenet").json()["results"]
        # An AP's own beacons also land it in the device inventory today, so
        # both kinds come back; the AP row is the one this asserts.
        self.assertIn(("ap", AP), [(x["kind"], x["ref"]) for x in res])
        self.assertEqual({x["ref"] for x in res}, {AP})
        self.assertEqual(self.client.get("/api/channels").json()["channels"], {"6": 1})


class TestWebSocket(ApiCase):

    def test_no_session_is_refused_with_policy_violation(self):
        self.setup_admin()
        self.client.cookies.clear()
        with self.assertRaises(WebSocketDisconnect) as cm:
            with self.client.websocket_connect("/ws") as ws:
                ws.receive_json()
        self.assertEqual(cm.exception.code, 1008)

    def test_session_gets_a_snapshot_first(self):
        self.setup_admin()
        with self.client.websocket_connect("/ws") as ws:
            msg = ws.receive_json()
        self.assertEqual(msg["type"], "snapshot")
        self.assertIn("total_frames", msg["overview"])
        self.assertEqual(self.pipe.subscribers, set())  # unsubscribed on close


if __name__ == "__main__":
    unittest.main()
