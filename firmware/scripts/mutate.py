#!/usr/bin/env python3
"""Run the firmware mutation catalogues. A test that cannot fail is not a test.

Same contract as ``sensor/scripts/mutate.py``. Each catalogue in
``test/mutations/`` names one source file (TARGET, relative to ``firmware/``)
and the defects it must catch as ``(label, old, new, expected_test)``. Every
mutation is applied in a temp copy, the host suite is rebuilt and run, and the
result is reported as:

* CAUGHT   - the test that claimed the defect failed (or crashed under ASan)
* WEAK     - something failed, but not the test that claimed it
* SURVIVED - nothing failed: the suite cannot see this defect
* BROKEN   - the mutant does not compile. It tests nothing, so it counts as a
             failure: mutate toward a different answer, never a syntax error.
* TIMEOUT  - the suite hung. Counts as a failure.
* ANCHOR   - ``old`` no longer matches the source exactly once: a catalogue
             that silently stopped testing anything. Counts as a failure.
* ALLOWED  - an intentional survivor (``expected_test=None``), with the reason
             in the catalogue's SURVIVORS dict.

The working tree is never touched, and the unmutated suite must pass first;
on a red baseline every later "caught" would be meaningless.

Usage: python firmware/scripts/mutate.py [--only NAME]

Author: gurvinny
Project: SPECTRE
"""
from __future__ import annotations

import argparse
import importlib.util
import platform
import re
import resource
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

FIRMWARE = Path(__file__).resolve().parent.parent
REPO = FIRMWARE.parent
CATALOGUES = FIRMWARE / "test" / "mutations"
TIMEOUT_SECONDS = 60
LOG_LIMIT_BYTES = 64 * 1024 * 1024


def _limit_log() -> None:
    # A runaway mutant gets SIGXFSZ instead of filling the disk.
    resource.setrlimit(resource.RLIMIT_FSIZE, (LOG_LIMIT_BYTES, LOG_LIMIT_BYTES))
_FAIL = re.compile(r"^FAIL: (test\w+) \(")
_RUN = re.compile(r"^RUN: (test\w+)$")


def export_tree(dest: Path) -> None:
    """Copy tracked + untracked-not-ignored files under firmware/ into dest."""
    rels: list[str] = []
    for args in (["git", "ls-files", "-z", "firmware"],
                 ["git", "ls-files", "-o", "--exclude-standard", "-z", "firmware"]):
        out = subprocess.run(args, cwd=REPO, check=True, capture_output=True)
        rels += [r for r in out.stdout.decode().split("\0") if r]
    for rel in rels:
        src, dst = REPO / rel, dest / rel
        if src.is_file():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dst)


def run_suite(work: Path) -> tuple[str, list[str]]:
    """Build and run the host suite. Returns (status, failing tests)."""
    test_dir = work / "firmware" / "test"
    build = subprocess.run(["make", "-s", "out/run_tests"], cwd=test_dir,
                           capture_output=True, text=True)
    if build.returncode != 0:
        return "broken", []
    # Output goes to a file, never into memory: a looping mutant can print
    # without bound before the timeout fires.
    log = test_dir / "out" / "mutant.log"
    try:
        with open(log, "w") as fh:
            # ASLR off, as in the Makefile: see the note there.
            r = subprocess.run(["setarch", platform.machine(), "-R", "./out/run_tests"],
                               cwd=test_dir, stdout=fh, stderr=subprocess.STDOUT,
                               timeout=TIMEOUT_SECONDS, preexec_fn=_limit_log)
    except subprocess.TimeoutExpired:
        return "timeout", []
    failed, last_run = [], None
    with open(log, errors="replace") as fh:
        lines = [ln.rstrip("\n") for _, ln in zip(range(200000), fh)]
    for line in lines:
        if m := _FAIL.match(line):
            failed.append(m.group(1))
        elif m := _RUN.match(line):
            last_run = m.group(1)
    if r.returncode != 0 and not failed and last_run:
        failed.append(last_run)          # crashed inside this test
    if r.returncode != 0 and not failed:
        return "red", ["<suite>"]
    return ("green" if r.returncode == 0 else "red"), failed


def load_catalogues(only: str | None):
    cats = []
    for path in sorted(CATALOGUES.glob("*.py")):
        if path.name.startswith("_") or (only and path.stem != only):
            continue
        spec = importlib.util.spec_from_file_location(f"mut_{path.stem}", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.SURVIVORS = getattr(mod, "SURVIVORS", {})
        cats.append((path.stem, mod))
    return cats


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only")
    args = ap.parse_args()
    cats = load_catalogues(args.only)
    if not cats:
        print("no catalogues found")
        return 2

    tmp = Path(tempfile.mkdtemp(prefix="spectre-fw-mut-"))
    try:
        export_tree(tmp)
        status, failed = run_suite(tmp)
        if status != "green":
            print(f"baseline is {status} ({failed}): fix the suite before mutating")
            return 2

        caught = survived = weak = 0
        per = []
        for name, cat in cats:
            target = tmp / "firmware" / cat.TARGET
            pristine = target.read_text()
            print(f"\n== {name} ({cat.TARGET})")
            c0, s0 = caught, survived
            for label, old, new, expect in cat.MUTATIONS:
                n = pristine.count(old)
                if n != 1:
                    print(f"  ANCHOR   {label}: {n} matches")
                    survived += 1
                    continue
                target.write_text(pristine.replace(old, new))
                status, failed = run_suite(tmp)
                target.write_text(pristine)
                if status in ("broken", "timeout"):
                    print(f"  {status.upper():<8} {label}")
                    survived += 1
                elif status == "green":
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
        return 1 if survived else 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
