"""Threat severities: the syslog code is what a SIEM sorts and pages on."""
TARGET = "spectre/models.py"
TESTS = "tests/test_wazuh.py"

MUTATIONS = [
    ("high-outranks-critical",
     '"high":     (2, 3),', '"high":     (2, 1),',
     "test_syslog_urgency_follows_threat_severity"),
    ("medium-and-low-swapped",
     '"medium":   (3, 4),', '"medium":   (3, 5),',
     "test_syslog_urgency_follows_threat_severity"),
    ("critical-demoted",
     '"critical": (1, 2),', '"critical": (1, 4),',
     "test_each_severity_maps_to_its_syslog_code"),
]

SURVIVORS = {}
