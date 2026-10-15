"""SQLite-backed live config. Author: gurvinny"""
import os
import unittest
from unittest import mock

from _support import TempDir

from spectre.config import DEFAULTS, Config
from spectre.store import Store


class TestConfig(unittest.TestCase):

    def setUp(self):
        self.tmp = TempDir()
        self.path = self.tmp.file("spectre.db")

    def tearDown(self):
        self.tmp.cleanup()

    def make(self, env=None):
        with mock.patch.dict(os.environ, env or {}, clear=False):
            store = Store(self.path)
            self.addCleanup(store.close)
            return Config(store)

    def test_first_run_seeds_every_default(self):
        cfg = self.make()
        self.assertEqual(cfg.snapshot(), DEFAULTS)
        self.assertEqual(set(cfg.store.all_config()), set(DEFAULTS))

    def test_env_seeds_typed_values_on_first_run(self):
        cfg = self.make({"WAZUH_HOST": "siem.test", "WAZUH_PORT": "1514",
                         "WAZUH_ENABLED": "FALSE", "RAW_RETENTION_HOURS": "6.5"})
        self.assertEqual((cfg("wazuh_host"), cfg("wazuh_port"), cfg("wazuh_enabled"),
                          cfg("raw_retention_hours")), ("siem.test", 1514, False, 6.5))

    def test_bad_env_value_falls_back_to_default(self):
        cfg = self.make({"WAZUH_PORT": "not-a-port", "WAZUH_HOST": ""})
        self.assertEqual((cfg("wazuh_port"), cfg("wazuh_host")),
                         (DEFAULTS["wazuh_port"], DEFAULTS["wazuh_host"]))

    def test_stored_value_wins_over_env_on_restart(self):
        cfg = self.make()
        cfg.set("wazuh_host", "set-in-ui")
        cfg.store.close()
        again = self.make({"WAZUH_HOST": "from-env"})
        self.assertEqual(again("wazuh_host"), "set-in-ui")

    def test_live_set_is_visible_to_the_accessor(self):
        cfg = self.make()
        cfg.set("deauth_threshold", 3)
        self.assertEqual((cfg("deauth_threshold"), cfg.get("deauth_threshold")), (3, 3))

    def test_unknown_key_uses_the_callers_default(self):
        cfg = self.make()
        self.assertEqual(cfg("no_such_key", 42), 42)


if __name__ == "__main__":
    unittest.main()
