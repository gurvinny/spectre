#!/usr/bin/env python3
"""Run the curated mutation catalogues. A test that cannot fail is not a test.

Each catalogue in ``tests/mutations/`` names one source file (TARGET), the test
file that must defend it (TESTS), and the defects it must catch as
``(label, old, new, expected_test)`` tuples. Every mutation is applied, the
claiming test file is run, and the result is reported as:

* CAUGHT   - the test that claimed the defect failed
* WEAK     - something failed, but not the test that claimed it
* SURVIVED - nothing failed: the suite cannot see this defect
* ANCHOR   - ``old`` no longer matches the source exactly once. That is a
             catalogue that silently stopped testing anything, so it counts
             as a failure, never a pass.
* ALLOWED  - an intentional survivor (``expected_test=None``), with the reason
             recorded in the catalogue's SURVIVORS dict.

The working tree is never touched. Tracked and untracked-but-not-ignored files
are exported to a temp dir and mutated there, so a dev server, a watcher or the
running sensor can never execute a mutant. Each catalogue's test file must pass
unmutated first; on a red baseline every later "caught" would be meaningless.

Usage: python scripts/mutate.py [--only NAME] [--staged]

Author: gurvinny
Project: SPECTRE
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SENSOR = Path(__file__).resolve().parent.parent
REPO = SENSOR.parent
TIMEOUT_SECONDS = 120
_RESULT = re.compile(r"^(test\w+) \(.*\) \.\.\. (FAIL|ERROR)$")


def export_tree(dest: Path, staged: bool) -> None:
    """Copy the code under test into *dest*.

    ``--staged`` writes exactly the INDEX (what is being committed) via
    ``git checkout-index``; ``git worktree add HEAD`` would test the previous
    commit and pass a broken change.
    """
    if staged:
        subprocess.run(["git", "checkout-index", "-a", "--prefix", f"{dest}/"],
                       cwd=REPO, check=True)
        return
    rels: list[str] = []
    for args in (["git", "ls-files", "-z"],
                 ["git", "ls-files", "-o", "--exclude-standard", "-z"]):
        out = subprocess.run(args, cwd=REPO, check=True, capture_output=True)
        rels += [r for r in out.stdout.decode().split("\0") if r]
    for rel in rels:
        src, dst = REPO / rel, dest / rel
        if src.is_file():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)


def run_tests(work: Path, test_file: str) -> tuple[int, list[str]] | None:
    """Run one test file. Returns (returncode, failing test names) or None on timeout."""
    # PYTHONDONTWRITEBYTECODE is load-bearing: two mutants of identical size
    # written within one second share a .pyc (mtime, size) key, and the next
    # run silently imports the PREVIOUS mutant.
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    try:
        r = subprocess.run(
            [sys.executable, "-m", "unittest", "discover", "-s", "tests",
             "-p", Path(test_file).name, "-v"],
            cwd=work / "sensor", capture_output=True, text=True, env=env,
            timeout=TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        return None
    failed = []
    for line in r.stderr.splitlines():
        m = _RESULT.match(line.strip())
        if m:
            failed.append(m.group(1))
    return r.returncode, failed


def load_catalogues(only: str | None):
    for path in sorted((SENSOR / "tests" / "mutations").glob("*.py")):
        if path.name.startswith("_") or (only and only not in path.stem):
            continue
        spec = importlib.util.spec_from_file_location(f"_mut_{path.stem}", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        yield path.stem, mod


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--staged", action="store_true")
    ap.add_argument("--only")
    a = ap.parse_args()
    sys.stdout.reconfigure(line_buffering=True)

    tmp = Path(tempfile.mkdtemp(prefix="spectre-mutate-"))
    try:
        export_tree(tmp, a.staged)
        if not (tmp / "sensor" / "spectre" / "pipeline.py").is_file():
            print("export produced no sensor/spectre package -- refusing to run",
                  file=sys.stderr)
            return 2

        caught = survived = weak = 0
        per: list[tuple[str, int, int]] = []
        for name, cat in load_catalogues(a.only):
            target = tmp / "sensor" / cat.TARGET
            pristine = target.read_text()
            print(f"\n=== {name} ({cat.TARGET}) ===")
            base = run_tests(tmp, cat.TESTS)
            if base is None or base[0] != 0:
                print(f"  BASELINE RED for {cat.TESTS}: refusing to judge mutants")
                survived += 1
                per.append((name, 0, 1))
                continue
            c0, s0 = caught, survived
            for label, old, new, expect in cat.MUTATIONS:
                n = pristine.count(old)
                if n != 1:
                    print(f"  ANCHOR   {label}: {n} matches")
                    survived += 1
                    continue
                target.write_text(pristine.replace(old, new))
                res = run_tests(tmp, cat.TESTS)
                target.write_text(pristine)
                if res is None:
                    print(f"  TIMEOUT  {label}")
                    survived += 1
                    continue
                code, failed = res
                if code == 0 or not failed:
                    if expect is None:
                        print(f"  ALLOWED  {label}\n           {cat.SURVIVORS[label]}")
                    else:
                        print(f"  SURVIVED {label}  (expected {expect} to fail)")
                        survived += 1
                elif expect is not None and expect in failed:
                    print(f"  CAUGHT   {label} -> {expect}")
                    caught += 1
                else:
                    print(f"  WEAK     {label} -> caught by {failed[0]}, not {expect}")
                    caught += 1
                    weak += 1
            per.append((name, caught - c0, survived - s0))

        print("\n--- per catalogue ---")
        for name, c, s in per:
            print(f"  {name:<20} caught {c:>3}  survived {s}")
        print(f"\ncaught {caught}, survived {survived}"
              + (f", {weak} caught by a different test than claimed" if weak else ""))
        return 1 if survived or not per else 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
