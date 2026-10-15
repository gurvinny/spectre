"""Ingest parser: the first code an attacker's frames touch."""
TARGET = "spectre/parser.py"
TESTS = "tests/test_parser.py"

MUTATIONS = [
    ("macs-not-normalised",
     "return v.upper()", "return v",
     "test_pri_and_tag_are_stripped_and_fields_typed"),
    ("frame-type-not-normalised",
     "frame_type=frame_type.upper(),", "frame_type=frame_type,",
     "test_pri_and_tag_are_stripped_and_fields_typed"),
    ("boot-band-not-latched",
     "                    self.band = band\n", "                    pass\n",
     "test_boot_event_latches_band_and_emits_nothing"),
    ("channel-fallback-split-wrong",
     'self.band = "5GHz" if ch >= 32 else "2.4GHz"',
     'self.band = "5GHz" if ch > 32 else "2.4GHz"',
     "test_band_falls_back_to_channel_and_latches"),
    ("hidden-ssid-kept",
     'if ssid == "?" or ssid == "":', 'if ssid == "":',
     "test_hidden_and_empty_ssid_become_none"),
    ("extra-keys-dropped",
     "extra = {k: v for k, v in obj.items() if k not in known}", "extra = {}",
     "test_unknown_keys_are_preserved_in_extra"),
    ("noise-counted-as-malformed",
     '            if "{" in line:\n                self.malformed += 1\n',
     "            self.malformed += 1\n",
     "test_malformed_counter_counts_only_data_shaped_noise"),
    ("bad-int-raises",
     "    except (TypeError, ValueError):\n        return None\n\n\ndef _as_mac",
     "    except (ZeroDivisionError,):\n        return None\n\n\ndef _as_mac",
     "test_non_numeric_fields_become_none"),
    ("array-accepted-as-object",
     "return obj if isinstance(obj, dict) else None", "return obj",
     "test_json_array_is_not_an_object"),
]
SURVIVORS = {}
