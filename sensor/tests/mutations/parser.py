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
     "                self._latch_band(obj.get(\"band\"))\n", "                pass\n",
     "test_boot_event_latches_band_and_emits_nothing"),
    ("channel-fallback-split-wrong",
     'self.band = "5GHz" if ch >= 32 else "2.4GHz"',
     'self.band = "5GHz" if ch > 32 else "2.4GHz"',
     "test_band_falls_back_to_channel_and_latches"),
    ("hidden-ssid-kept",
     'if ssid == "?" or ssid == "":', 'if ssid == "":',
     "test_hidden_and_empty_ssid_become_none"),
    ("extra-keys-dropped",
     "extra = {k: v for k, v in obj.items() if k not in _KNOWN_KEYS}", "extra = {}",
     "test_unknown_keys_are_preserved_in_extra"),
    ("noise-counted-as-malformed",
     '            if "{" in line:\n                self.malformed += 1\n                self._report_malformed(raw)\n',
     "            self.malformed += 1\n            self._report_malformed(raw)\n",
     "test_malformed_counter_counts_only_data_shaped_noise"),
    ("bad-int-raises",
     "    except (TypeError, ValueError):\n        return None\n\n\ndef _as_mac",
     "    except (ZeroDivisionError,):\n        return None\n\n\ndef _as_mac",
     "test_non_numeric_fields_become_none"),
    ("array-accepted-as-object",
     "return obj if isinstance(obj, dict) else None", "return obj",
     None),
    ("json-start-not-retried",
     'start = line.find("{", start + 1)', "return None",
     "test_boot_line_after_a_partial_frame_and_rom_noise_is_kept"),
    ("malformed-noise-not-reported",
     "                self.malformed += 1\n                self._report_malformed(raw)\n",
     "                self.malformed += 1\n",
     "test_each_malformed_line_is_reported_to_the_callback"),
    ("untyped-object-not-reported",
     "            self.malformed += 1\n            self._report_malformed(raw)\n            return None",
     "            self.malformed += 1\n            return None",
     "test_each_malformed_line_is_reported_to_the_callback"),
]
SURVIVORS = {
    "array-accepted-as-object":
        "dead guard: the slice always starts at '{', so json.loads returns a "
        "dict or raises; kept as defence in depth, no input can reach it",
}
