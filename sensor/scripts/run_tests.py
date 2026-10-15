#!/usr/bin/env python3
"""Run the sensor suite the way CI should: shuffled, counted, and floored.

A green ``unittest discover`` proves less than it looks. A test file whose name
stops matching the pattern, or that fails to import, can vanish without turning
anything red; tests that lean on state left behind by an earlier one pass only
in the order they happen to be written. So this runner:

* checks that EVERY ``tests/test_*.py`` file on disk contributed tests,
* runs the whole suite once per seed in a shuffled order,
* counts assertions as they execute, and
* fails if the test or assertion count drops below the floors below.

Raise the floors when the suite grows. Never lower them to make a run pass.

Usage: python scripts/run_tests.py [--seeds 1 2 3]

Author: gurvinny
Project: SPECTRE
"""
from __future__ import annotations

import argparse
import random
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TESTS = ROOT / "tests"

MIN_TESTS = 157
MIN_ASSERTIONS = 739

_asserts = 0


def _count_assertions() -> None:
    """Wrap every public ``assert*`` on TestCase so each call is counted."""
    def wrap(fn):
        def counted(*a, **kw):
            global _asserts
            _asserts += 1
            return fn(*a, **kw)
        return counted

    for name in dir(unittest.TestCase):
        if name.startswith("assert") and not name.startswith("assert_"):
            setattr(unittest.TestCase, name, wrap(getattr(unittest.TestCase, name)))


def _flatten(suite) -> list[unittest.TestCase]:
    out = []
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            out.extend(_flatten(item))
        else:
            out.append(item)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, nargs="+", default=[1, 2, 3])
    args = ap.parse_args()

    sys.path.insert(0, str(TESTS))
    _count_assertions()

    loader = unittest.TestLoader()
    files = sorted(p.stem for p in TESTS.glob("test_*.py"))
    tests: list[unittest.TestCase] = []
    empty = []
    for stem in files:
        found = _flatten(loader.loadTestsFromName(stem))
        # A file that fails to import comes back as a single _FailedTest; it
        # still "has a test", and running it reports the import error.
        if not found:
            empty.append(stem)
        tests.extend(found)
    if empty:
        print(f"FAIL: no tests collected from {', '.join(empty)}")
        return 1

    ok = True
    for seed in args.seeds:
        global _asserts
        _asserts = 0
        order = list(tests)
        random.Random(seed).shuffle(order)
        print(f"\n=== seed {seed}: {len(order)} tests from {len(files)} files ===")
        result = unittest.TextTestRunner(verbosity=1).run(unittest.TestSuite(order))
        print(f"assertions executed: {_asserts}")
        if not result.wasSuccessful():
            ok = False
        if result.testsRun < MIN_TESTS:
            print(f"FAIL: ran {result.testsRun} tests, floor is {MIN_TESTS}")
            ok = False
        if _asserts < MIN_ASSERTIONS:
            print(f"FAIL: {_asserts} assertions, floor is {MIN_ASSERTIONS}")
            ok = False
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
