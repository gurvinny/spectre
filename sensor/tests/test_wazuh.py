"""RFC 5424 forwarder to Wazuh. Author: gurvinny"""
import json
import os
import re
import socket
import threading
import time
import unittest

from _support import UdpSink, make_cfg

from spectre.models import Threat
from spectre.wazuh import WazuhForwarder, _rfc3339, _sd

LINE = re.compile(r"^<(\d+)>1 (\S+) (\S+) (\S+) - (\S+) (\[.*?[^\\]\]|-) (\{.*\})$")


def threat(**kw):
    base = dict(ts=1_700_000_000.5, rule="evil_twin", severity="critical",
                title="Evil twin: 'ExampleNet'", band="5GHz",
                bssid="00:00:5E:00:53:66", ssid="ExampleNet",
                detail={"rogue_bssid": "00:00:5E:00:53:66"})
    base.update(kw)
    return Threat(**base)


class TestFormatting(unittest.TestCase):

    def test_rfc3339_is_utc_with_milliseconds(self):
        # Force a non-UTC local zone, or a dropped tz= is invisible on a UTC host.
        old = os.environ.get("TZ")
        os.environ["TZ"] = "America/New_York"
        time.tzset()
        try:
            self.assertEqual(_rfc3339(0.25), "1970-01-01T00:00:00.250Z")
        finally:
            if old is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = old
            time.tzset()

    def test_sd_escapes_quote_backslash_and_bracket(self):
        self.assertEqual(_sd({"ssid": 'a"b\\c]d'}).split(" ", 1)[1],
                         'ssid="a\\"b\\\\c\\]d"]')

    def test_sd_id_is_name_at_enterprise_number(self):
        # RFC 5424 section 7.2.2: a private SD-ID is "name@<private enterprise number>".
        self.assertTrue(_sd({"band": "5GHz"}).startswith("[spectre@32473 "))

    def test_sd_drops_none_and_is_nil_when_empty(self):
        self.assertNotIn("bssid", _sd({"band": "5GHz", "bssid": None}))
        self.assertEqual(_sd({"x": None}), "-")


class TestUdp(unittest.TestCase):

    def setUp(self):
        self.sink = UdpSink()
        self.cfg = make_cfg(wazuh_enabled=True, wazuh_host="127.0.0.1",
                            wazuh_port=self.sink.port, wazuh_proto="udp",
                            wazuh_app_name="spectre")
        self.fwd = WazuhForwarder(self.cfg, hostname="sensor-host")

    def tearDown(self):
        self.sink.close()

    def test_threat_frame_layout_pri_and_body(self):
        self.assertTrue(self.fwd.send_threat(threat()))
        m = LINE.match(self.sink.recv())
        self.assertIsNotNone(m)
        pri, _ts, host, app, msgid, sd, body = m.groups()
        self.assertEqual((int(pri), host, app, msgid),
                         (23 * 8 + 2, "sensor-host", "spectre", "THREAT"))
        for kv in ('band="5GHz"', 'rule="evil_twin"', 'ssid="ExampleNet"',
                   'severity="critical"'):
            self.assertIn(kv, sd)
        decoded = json.loads(body)
        self.assertEqual(decoded["kind"], "threat")
        self.assertEqual(decoded["detail"], {"rogue_bssid": "00:00:5E:00:53:66"})
        self.assertEqual(decoded["rank"], 1)
        self.assertEqual(self.fwd.status()["sent"], 1)

    def test_syslog_urgency_follows_threat_severity(self):
        # Lower syslog code = more urgent. A less severe threat must never be
        # sent as more urgent than a more severe one.
        codes = []
        for sev in ("critical", "high", "medium", "low", "info"):
            self.fwd.send_threat(threat(severity=sev))
            codes.append(int(LINE.match(self.sink.recv()).group(1)) - 23 * 8)
        self.assertEqual(codes, sorted(set(codes)))

    def test_each_severity_maps_to_its_syslog_code(self):
        for sev, code in (("critical", 2), ("high", 3), ("medium", 4),
                          ("low", 5), ("info", 6), ("bogus", 5)):
            self.fwd.send_threat(threat(severity=sev))
            self.assertEqual(int(LINE.match(self.sink.recv()).group(1)),
                             23 * 8 + code, sev)

    def test_attacker_ssid_cannot_break_the_frame(self):
        evil = 'x"] [inject@1 a="b"] {"kind":"fake"}'
        self.fwd.send_threat(threat(ssid=evil, title=evil))
        m = LINE.match(self.sink.recv())
        self.assertIsNotNone(m)
        self.assertEqual(json.loads(m.group(7))["ssid"], evil)

    def test_summary_is_info_with_summary_msgid(self):
        self.assertTrue(self.fwd.send_summary({"fps": 50.0}))
        m = LINE.match(self.sink.recv())
        self.assertEqual((int(m.group(1)), m.group(5)), (23 * 8 + 6, "SUMMARY"))
        self.assertEqual(json.loads(m.group(7)), {"kind": "summary", "fps": 50.0})

    def test_disabled_or_hostless_sends_nothing(self):
        self.cfg.values["wazuh_enabled"] = False
        self.assertFalse(self.fwd.send_threat(threat()))
        self.cfg.values["wazuh_enabled"] = True
        self.cfg.values["wazuh_host"] = ""
        self.assertFalse(self.fwd.send_threat(threat()))
        self.assertTrue(self.sink.empty())
        self.assertEqual((self.fwd.sent, self.fwd.failures), (0, 0))


class TestTcp(unittest.TestCase):

    def test_tcp_frames_are_newline_delimited_on_one_connection(self):
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        got, accepted = [], []

        def serve():
            conn, _ = srv.accept()
            accepted.append(1)
            buf = b""
            conn.settimeout(2)
            while buf.count(b"\n") < 2:
                chunk = conn.recv(65535)
                if not chunk:
                    break
                buf += chunk
            got.extend(buf.split(b"\n")[:2])
            conn.close()

        th = threading.Thread(target=serve)
        th.start()
        cfg = make_cfg(wazuh_enabled=True, wazuh_host="127.0.0.1",
                       wazuh_port=srv.getsockname()[1], wazuh_proto="TCP")
        fwd = WazuhForwarder(cfg)
        self.assertTrue(fwd.send_threat(threat()))
        self.assertTrue(fwd.send_summary({"fps": 1}))
        th.join(3)
        srv.close()
        fwd._reset_tcp()
        self.assertEqual(len(accepted), 1)
        self.assertEqual([LINE.match(g.decode()).group(5) for g in got],
                         ["THREAT", "SUMMARY"])

    def test_unreachable_tcp_counts_a_failure(self):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()  # nothing listens here now
        fwd = WazuhForwarder(make_cfg(wazuh_enabled=True, wazuh_host="127.0.0.1",
                                      wazuh_port=port, wazuh_proto="tcp"))
        self.assertFalse(fwd.send_threat(threat()))
        st = fwd.status()
        self.assertEqual((st["sent"], st["failures"]), (0, 1))
        self.assertTrue(st["last_error"])
        self.assertIsNone(fwd._tcp)


if __name__ == "__main__":
    unittest.main()
