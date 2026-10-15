"""SIEM forwarding: a malformed line is dropped by Wazuh with no error here."""
TARGET = "spectre/wazuh.py"
TESTS = "tests/test_wazuh.py"

MUTATIONS = [
    ("quote-not-escaped",
     """.replace('"', '\\\\"')""", "",
     "test_sd_escapes_quote_backslash_and_bracket"),
    ("bracket-not-escaped",
     """.replace("]", "\\\\]")""", "",
     "test_attacker_ssid_cannot_break_the_frame"),
    ("wrong-facility",
     "FACILITY_LOCAL7 = 23", "FACILITY_LOCAL7 = 16",
     "test_threat_frame_layout_pri_and_body"),
    ("severity-not-mapped",
     "severity_code = SEVERITY.get(t.severity, (9, 5))[1]", "severity_code = 5",
     "test_each_severity_maps_to_its_syslog_code"),
    ("disabled-still-sends",
     '        if not bool(self.cfg("wazuh_enabled", True)):\n            return False\n', "",
     "test_disabled_or_hostless_sends_nothing"),
    ("tcp-not-delimited",
     'self._tcp.sendall(data + b"\\n")', "self._tcp.sendall(data)",
     "test_tcp_frames_are_newline_delimited_on_one_connection"),
    ("tcp-reconnects-every-send",
     "if self._tcp is None or self._tcp_target != (host, port):", "if True:",
     "test_tcp_frames_are_newline_delimited_on_one_connection"),
    ("failure-not-counted",
     "            self.failures += 1\n", "",
     "test_unreachable_tcp_counts_a_failure"),
    ("timestamp-not-utc",
     "datetime.fromtimestamp(ts, tz=timezone.utc)", "datetime.fromtimestamp(ts)",
     "test_rfc3339_is_utc_with_milliseconds"),
    ("summary-wrong-msgid",
     "return self._emit(6, MSGID_SUMMARY, sd, body)",
     "return self._emit(6, MSGID_THREAT, sd, body)",
     "test_summary_is_info_with_summary_msgid"),
]
SURVIVORS = {}
