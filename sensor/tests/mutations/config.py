"""Live config seeding."""
TARGET = "spectre/config.py"
TESTS = "tests/test_config.py"

MUTATIONS = [
    ("env-overwrites-ui-values",
     "            if key in existing:\n                continue\n", "",
     "test_stored_value_wins_over_env_on_restart"),
    ("env-bool-wrong",
     '"wazuh_enabled": ("WAZUH_ENABLED", lambda v: v.lower() == "true"),',
     '"wazuh_enabled": ("WAZUH_ENABLED", bool),',
     "test_env_seeds_typed_values_on_first_run"),
    ("bad-env-crashes",
     "                    except (ValueError, TypeError):\n                        value = default\n",
     "                    except KeyError:\n                        value = default\n",
     "test_bad_env_value_falls_back_to_default"),
    ("defaults-not-consulted",
     "return self.store.get_config(key, DEFAULTS.get(key, default))",
     "return self.store.get_config(key, default)",
     "test_missing_row_falls_back_to_defaults_not_the_callers_default"),
]
SURVIVORS = {
}
