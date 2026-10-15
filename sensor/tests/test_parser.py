import unittest
import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from spectre.parser import _extract_json, Parser
from spectre.models import Event


class TestSpectreParser(unittest.TestCase):

    def setUp(self):
        self.parser = Parser("sensor-test")

    def test_extract_json_valid(self):
        line = '<190>ESP32C5 wifi_sniffer: {"seq":47,"uptime_ms":2728,"ch":6,"rssi":-55,"type":"BEACON","ssid":"TestAP"}'
        data = _extract_json(line)
        self.assertIsNotNone(data)
        self.assertEqual(data.get("type"), "BEACON")
        self.assertEqual(data.get("ssid"), "TestAP")

    def test_extract_json_invalid(self):
        line = "ESP-ROM:v1.0 boot loader banner without json"
        data = _extract_json(line)
        self.assertIsNone(data)

    def test_parse_line_beacon(self):
        line = '<190>ESP32C5 wifi_sniffer: {"seq":10,"uptime_ms":1000,"ch":1,"rssi":-40,"type":"BEACON","src":"aa:bb:cc:dd:ee:ff","dst":"ff:ff:ff:ff:ff:ff","bssid":"aa:bb:cc:dd:ee:ff","ssid":"SecureWiFi"}'
        event = self.parser.parse_line(line)
        self.assertIsNotNone(event)
        self.assertEqual(event.frame_type, "BEACON")
        self.assertEqual(event.ssid, "SecureWiFi")
        self.assertEqual(event.rssi, -40)

    def test_pri_and_tag_are_stripped_and_fields_typed(self):
        ev = self.parser.parse_line(
            '<190>ESP32C5 wifi_sniffer: {"seq":"7","uptime_ms":99,"ch":"11",'
            '"rssi":"-61","type":"deauth","src":"aa:bb:cc:dd:ee:01",'
            '"dst":"aa:bb:cc:dd:ee:02","bssid":"aa:bb:cc:dd:ee:03"}')
        self.assertEqual((ev.seq, ev.uptime_ms, ev.ch, ev.rssi), (7, 99, 11, -61))
        self.assertEqual(ev.frame_type, "DEAUTH")
        self.assertEqual((ev.src, ev.dst, ev.bssid),
                         ("AA:BB:CC:DD:EE:01", "AA:BB:CC:DD:EE:02", "AA:BB:CC:DD:EE:03"))
        self.assertEqual(ev.sensor_id, "sensor-test")

    def test_non_numeric_fields_become_none(self):
        ev = self.parser.parse_line('{"type":"BEACON","ch":"six","rssi":null,"seq":[1]}')
        self.assertEqual((ev.ch, ev.rssi, ev.seq), (None, None, None))

    def test_boot_event_latches_band_and_emits_nothing(self):
        self.assertIsNone(self.parser.parse_line(
            '<190>ESP32C5 wifi_sniffer: {"event":"boot","band":"5GHz"}'))
        self.assertEqual(self.parser.last_event_kind, "boot")
        ev = self.parser.parse_line('{"type":"BEACON","ch":1}')
        self.assertEqual(ev.band, "5GHz")  # latched band beats the channel

    def test_band_falls_back_to_channel_and_latches(self):
        p5 = Parser("s5")
        self.assertEqual(p5.parse_line('{"type":"BEACON","ch":32}').band, "5GHz")
        self.assertEqual(p5.parse_line('{"type":"BEACON","ch":1}').band, "5GHz")
        p24 = Parser("s24")
        self.assertEqual(p24.parse_line('{"type":"BEACON","ch":14}').band, "2.4GHz")

    def test_default_band_is_kept_when_given(self):
        p = Parser("s", default_band="2.4GHz")
        self.assertEqual(p.parse_line('{"type":"BEACON","ch":149}').band, "2.4GHz")

    def test_hidden_and_empty_ssid_become_none(self):
        for raw in ('"?"', '""', '5'):
            ev = self.parser.parse_line('{"type":"BEACON","ssid":%s}' % raw)
            self.assertIsNone(ev.ssid, raw)

    def test_unknown_keys_are_preserved_in_extra(self):
        ev = self.parser.parse_line('{"type":"BEACON","ssid":"A","vendor":"x","n":2}')
        self.assertEqual(ev.extra, {"vendor": "x", "n": 2})

    def test_malformed_counter_counts_only_data_shaped_noise(self):
        self.parser.parse_line("ESP-ROM:esp32c5-eco2 banner")
        self.parser.parse_line("")
        self.assertEqual(self.parser.malformed, 0)
        self.parser.parse_line('<190>tag: {"type":"BEACON",broken')
        self.parser.parse_line('{"ch":1}')               # JSON but no type/event
        self.parser.parse_line('{"type":7}')             # non-string type
        self.assertEqual(self.parser.malformed, 3)

    def test_json_array_is_not_an_object(self):
        self.assertIsNone(_extract_json("[1, 2]"))
        self.assertIsNone(_extract_json("} backwards {"))

    def test_received_at_is_wall_clock(self):
        import time
        before = time.time()
        ev = self.parser.parse_line('{"type":"BEACON"}')
        self.assertTrue(before <= ev.received_at <= time.time())


if __name__ == "__main__":
    unittest.main()
