"""Engine fan-out: every rule hears ap_info."""
TARGET = "spectre/detect/__init__.py"
TESTS = "tests/test_ingest_v2.py"

MUTATIONS = [
    ("engine-drops-ap-info",
     "        for rule in self.rules:\n            rule.set_ap_info(rec)",
     "        pass",
     "test_pipeline_ap_info_reaches_the_detection_engine"),
]
SURVIVORS = {}
