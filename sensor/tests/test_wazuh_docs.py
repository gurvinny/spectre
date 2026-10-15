"""The Wazuh decoder and rules published in docs/wazuh-integration.md, run
against frames the shipping forwarder actually sends. Author: gurvinny

Threats come from the real detectors, the frames from the real
:class:`~spectre.wazuh.WazuhForwarder` over loopback UDP, and the XML straight
out of the doc, so a change to the wire format, a detector title, or the doc
breaks this suite instead of a reader's SIEM.

Wazuh itself is not run here. The matcher below models the parts the doc
relies on: ``program_name`` + child decoder regex, ``if_sid`` descent in file
order, ``field`` regex matches, and ``mitre`` ids.
"""
import os
import re
import unittest
import xml.etree.ElementTree as ET

from _support import UdpSink, frame, make_cfg, sim_events

from spectre.detect.anomaly import AnomalyRule
from spectre.detect.deauth_flood import DeauthFlood
from spectre.detect.evil_twin import EvilTwin
from spectre.detect.flood import FloodRule
from spectre.wazuh import WazuhForwarder

DOC = os.path.join(os.path.dirname(__file__), "..", "..", "docs", "wazuh-integration.md")
FRAME = re.compile(r"^<\d+>1 \S+ \S+ (\S+) - \S+ (?:\[.*?[^\\]\]|-) (\{.*\})$")
GOOD, ROGUE = "00:00:5E:00:53:01", "00:00:5E:00:53:66"


def osregex(pattern: str) -> str:
    """Reject what Wazuh's default OS_Regex cannot parse, return *pattern*.

    OS_Regex has no character classes, groups-with-flags or counted repeats,
    and ``+``/``*`` apply only to backslash expressions (``\\w+``, ``\\.*``).
    Python's ``re`` accepts all of those, so without this check a pattern that
    never matches on a real manager would pass here.
    """
    prev_escape = False
    i = 0
    while i < len(pattern):
        c = pattern[i]
        if c == "\\":
            prev_escape = True
            i += 2
            continue
        if c in "[]{}?":
            raise AssertionError(f"OS_Regex has no {c!r}: {pattern!r} needs type=\"pcre2\"")
        if c in "+*" and not prev_escape:
            raise AssertionError(f"OS_Regex {c!r} needs a backslash expression: {pattern!r}")
        prev_escape = False
        i += 1
    return pattern


def compiled(el) -> re.Pattern:
    """A decoder/rule regex element, checked against the engine it names."""
    if el.get("type") == "pcre2":
        return re.compile(el.text)
    return re.compile(osregex(el.text))


def _doc():
    with open(DOC, encoding="utf-8") as fh:
        return fh.read()


def _xml_after(heading: str) -> ET.Element:
    text = _doc()
    at = text.index(heading)
    block = re.search(r"```xml\n(.*?)```", text[at:], re.S).group(1)
    return ET.fromstring("<root>" + block + "</root>")


class Wazuh:
    """Just enough of the Wazuh analysis engine to evaluate the doc's XML."""

    def __init__(self):
        decoders = _xml_after("## Decoder")
        self.program = decoders.find("decoder[@name='spectre']/program_name").text
        self.children = [
            (compiled(d.find("regex")), d.find("order").text.split(","))
            for d in decoders.findall("decoder") if d.find("parent") is not None
        ]
        self.rules = _xml_after("## Rules").findall(".//rule")

    def decode(self, line: str):
        m = FRAME.match(line)
        if m is None or m.group(1) != self.program:
            return None
        fields = {}
        for regex, order in self.children:
            hit = regex.search(m.group(2))
            if hit:
                fields.update(zip(order, hit.groups()))
                break  # Wazuh stops at the first matching child decoder
        return fields

    def _matches(self, rule, fields) -> bool:
        return all(
            f.get("name") in fields and compiled(f).search(fields[f.get("name")])
            for f in rule.findall("field")
        )

    def analyze(self, line: str):
        """(rule id, [mitre ids]) for the deepest rule the line reaches."""
        fields = self.decode(line)
        if fields is None:
            return None
        current = next(r for r in self.rules
                       if r.findtext("decoded_as") == "spectre")
        while True:
            parent = current.get("id")
            child = next((r for r in self.rules
                          if parent in re.split(r"[,\s]+", r.findtext("if_sid") or "")
                          and self._matches(r, fields)), None)
            if child is None:
                break
            current = child
        return current.get("id"), [i.text for i in current.findall("mitre/id")]


class TestPublishedWazuhConfig(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.wazuh = Wazuh()

    def setUp(self):
        self.sink = UdpSink()
        self.fwd = WazuhForwarder(make_cfg(wazuh_enabled=True, wazuh_host="127.0.0.1",
                                           wazuh_port=self.sink.port, wazuh_proto="udp"))

    def tearDown(self):
        self.sink.close()

    def wire(self, threat) -> str:
        self.assertTrue(self.fwd.send_threat(threat))
        return self.sink.recv()

    def verdict(self, threat):
        return self.wazuh.analyze(self.wire(threat))

    # ── one threat per detection, from the detector that ships ─────────
    def deauth(self):
        rule = DeauthFlood(make_cfg(deauth_window_seconds=10, deauth_threshold=20))
        return [t for ev in sim_events("deauth_flood") for t in rule.process(ev)][0]

    def evil_twin(self, **row):
        rule = EvilTwin(make_cfg())
        rule.set_known_networks([{"ssid": "ExampleNet", "bssid": GOOD, **row}])
        return rule

    def flood(self, name, **kw):
        rule = FloodRule(make_cfg(flood_window_seconds=5, flood_cooldown_seconds=30,
                                  beacon_flood_distinct_bssids=40, probe_flood_threshold=120))
        return [t for ev in sim_events(name, **kw) for t in rule.process(ev)][0]

    def anomaly(self, **cfg):
        return AnomalyRule(make_cfg(new_device_warmup_seconds=60, rssi_jump_db=55,
                                    rssi_jump_cooldown_seconds=60, **cfg))

    def test_deauth_flood_maps_to_endpoint_dos(self):
        self.assertEqual(self.verdict(self.deauth()), ("100612", ["T1499"]))

    def test_evil_twin_maps_to_adversary_in_the_middle(self):
        rule = self.evil_twin()
        [t] = [t for ev in sim_events("evil_twin") for t in rule.process(ev)]
        self.assertEqual(t.severity, "critical")
        self.assertEqual(self.verdict(t), ("100610", ["T1557"]))

    def test_unexpected_band_is_rogue_ap_not_deauth(self):
        # Shares severity "high" with deauth: a severity-keyed technique tagged it T1499.
        rule = self.evil_twin(band="2.4GHz")
        [t] = rule.process(frame(1, band="5GHz", type="BEACON", ch=36, rssi=-40,
                                 src=GOOD, dst="FF:FF:FF:FF:FF:FF", bssid=GOOD,
                                 ssid="ExampleNet"))
        self.assertEqual(t.severity, "high")
        self.assertEqual(self.verdict(t), ("100611", ["T1557"]))

    def test_beacon_flood_maps_to_network_dos(self):
        self.assertEqual(self.verdict(self.flood("beacon_flood")), ("100613", ["T1498"]))

    def test_probe_flood_maps_to_active_scanning(self):
        t = self.flood("probe_flood", step=0.001)
        self.assertEqual(self.verdict(t), ("100614", ["T1595"]))

    def test_rssi_jump_is_levelled_but_unmapped(self):
        rule = self.anomaly()
        dev = "00:00:5E:00:53:20"
        rule.process(frame(100, type="PROBE_REQ", ch=6, rssi=-90, src=dev,
                           dst="FF:FF:FF:FF:FF:FF", bssid="FF:FF:FF:FF:FF:FF", ssid="?"))
        [t] = rule.process(frame(101, type="PROBE_REQ", ch=6, rssi=-30, src=dev,
                                 dst="FF:FF:FF:FF:FF:FF", bssid="FF:FF:FF:FF:FF:FF", ssid="?"))
        self.assertTrue(t.title.startswith("RSSI jump"))
        self.assertEqual(self.verdict(t), ("100604", []))

    def test_new_device_is_levelled_but_unmapped(self):
        rule = self.anomaly(new_device_alerts=True)
        rule.process(frame(0, type="PROBE_REQ", ch=6, rssi=-60, src="00:00:5E:00:53:21",
                           dst="FF:FF:FF:FF:FF:FF", bssid="FF:FF:FF:FF:FF:FF", ssid="?"))
        [t] = rule.process(frame(100, type="PROBE_REQ", ch=6, rssi=-60, src="00:00:5E:00:53:22",
                                 dst="FF:FF:FF:FF:FF:FF", bssid="FF:FF:FF:FF:FF:FF", ssid="?"))
        self.assertEqual(self.verdict(t), ("100604", []))

    # ── decoder fields ─────────────────────────────────────────────────
    def test_decoder_extracts_every_field_through_json_escapes(self):
        rule = EvilTwin(make_cfg())
        rule.set_known_networks([{"ssid": 'Café "5G"', "bssid": GOOD}])
        [t] = rule.process(frame(1, band="5GHz", type="BEACON", ch=36, rssi=-40, src=ROGUE,
                                 dst="FF:FF:FF:FF:FF:FF", bssid=ROGUE, ssid='Café "5G"'))
        fields = self.wazuh.decode(self.wire(t))
        self.assertEqual(fields["spectre.rule"], "evil_twin")
        self.assertEqual(fields["spectre.severity"], "critical")
        self.assertEqual(fields["spectre.band"], "5GHz")
        # Decoded as raw JSON text: the escapes survive, the title is not cut short.
        self.assertEqual(fields["spectre.title"],
                         "Evil twin: 'Caf\\u00e9 \\\"5G\\\"' from unexpected BSSID " + ROGUE)
        self.assertEqual(self.verdict(t), ("100610", ["T1557"]))

    def test_summary_stays_on_the_base_rule(self):
        self.assertTrue(self.fwd.send_summary({"frames": 10}))
        self.assertEqual(self.wazuh.analyze(self.sink.recv()), ("100600", []))

    def test_other_programs_are_not_decoded(self):
        line = '<190>1 2026-01-01T00:00:00.000Z host other - THREAT - {"rule":"evil_twin"}'
        self.assertIsNone(self.wazuh.analyze(line))

    def test_osregex_check_rejects_what_wazuh_cannot_parse(self):
        for bad in (r'"title":"([^"]+)"', r'"rule":"(\w+)".+"severity"', r"a{2}"):
            with self.assertRaises(AssertionError, msg=bad):
                osregex(bad)
        for ok in (r"^critical$", r'"rule":"(\w+)"\.+"severity"', r"^evil_twin$"):
            self.assertEqual(osregex(ok), ok)

    # ── the table and the XML say the same thing ───────────────────────
    def test_mapping_table_matches_rule_xml(self):
        table = _doc().split("## MITRE ATT&CK mapping", 1)[1]
        rows = re.findall(r"^\| [^|]+ \| (\d{6}) \| (T\d{4}) ", table, re.M)
        xml = {r.get("id"): r.findtext("mitre/id") for r in self.wazuh.rules
               if r.find("mitre") is not None}
        self.assertEqual(dict(rows), xml)
        self.assertEqual(set(xml), {"100610", "100611", "100612", "100613", "100614"})


if __name__ == "__main__":
    unittest.main()
