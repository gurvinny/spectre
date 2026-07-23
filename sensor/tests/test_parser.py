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


if __name__ == "__main__":
    unittest.main()
