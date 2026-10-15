#!/usr/bin/env node
/**
 * Curated mutation runner for the web unit tests. A test that cannot fail is
 * not a test.
 *
 * Each tests/mutations/*.mutations.mjs names a TARGET source file, the TESTS
 * file that must defend it, and MUTATIONS as [label, old, new, expectedTest].
 * Every mutation is applied in a throwaway export of the repo (never the
 * working tree, where `next dev` would hot-reload the mutant), the claiming
 * test file is run through scripts/test.mjs, and the result is one of:
 *
 *   CAUGHT   the claiming test failed
 *   WEAK     something failed, but not the claiming test
 *   SURVIVED nothing failed
 *   ANCHOR   `old` does not match the source exactly once; a stale catalogue
 *            entry tests nothing, so it counts as a failure
 *   ALLOWED  intentional survivor (expectedTest null), reason in SURVIVORS
 *
 * The claiming file must pass, with at least one test, before any mutant is
 * judged: on a red or empty baseline every "caught" would be meaningless.
 *
 * Usage: node scripts/mutate.mjs [--only NAME] [--staged]
 * Author: gurvinny
 */
import { execFileSync } from "node:child_process";
import {
  copyFileSync, existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync,
  rmSync, symlinkSync, writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { pathToFileURL } from "node:url";

const WEB = resolve(import.meta.dirname, "..");
const REPO = resolve(WEB, "..");
const args = process.argv.slice(2);
const STAGED = args.includes("--staged");
const ONLY = args.includes("--only") ? args[args.indexOf("--only") + 1] : null;

function exportTree(dest) {
  if (STAGED) {
    execFileSync("git", ["checkout-index", "-a", `--prefix=${dest}/`], { cwd: REPO });
    return;
  }
  const rels = [];
  for (const cmd of [["ls-files", "-z"], ["ls-files", "-o", "--exclude-standard", "-z"]]) {
    const out = execFileSync("git", cmd, { cwd: REPO, maxBuffer: 64 * 1024 * 1024 });
    rels.push(...out.toString().split("\0").filter(Boolean));
  }
  for (const rel of rels) {
    const src = join(REPO, rel);
    if (!existsSync(src)) continue;
    const dst = join(dest, rel);
    mkdirSync(dirname(dst), { recursive: true });
    copyFileSync(src, dst);
  }
}

function runTests(webDir, testFile) {
  let out = "";
  let code = 0;
  try {
    out = execFileSync("node", ["scripts/test.mjs", testFile], {
      cwd: webDir, encoding: "utf8", stdio: ["ignore", "pipe", "pipe"], timeout: 120_000,
    });
  } catch (err) {
    out = String(err.stdout ?? "");
    code = err.status ?? 1;
  }
  // TAP: "not ok 3 - test name". Subtests are indented; take every level.
  const failed = [...out.matchAll(/^\s*not ok \d+ - (.+)$/gm)].map((m) => m[1].trim());
  const ran = Number(/^# tests (\d+)$/m.exec(out)?.[1] ?? 0);
  return { code, failed, ran };
}

async function loadCatalogues() {
  const dir = join(WEB, "tests", "mutations");
  const out = [];
  for (const f of readdirSync(dir).sort()) {
    if (!f.endsWith(".mutations.mjs") || f.startsWith("_")) continue;
    const stem = f.replace(/\.mutations\.mjs$/, "");
    if (ONLY && !stem.includes(ONLY)) continue;
    out.push([stem, await import(pathToFileURL(join(dir, f)).href)]);
  }
  return out;
}

const work = mkdtempSync(join(tmpdir(), "spectre-web-mutate-"));
let caught = 0, survived = 0, weak = 0;
const per = [];
try {
  exportTree(work);
  const webDir = join(work, "web");
  if (!existsSync(join(webDir, "src")) || !existsSync(join(webDir, "scripts", "test.mjs"))) {
    console.error("export produced no web/src -- refusing to run");
    process.exit(2);
  }
  symlinkSync(join(WEB, "node_modules"), join(webDir, "node_modules"), "dir");

  const catalogues = await loadCatalogues();
  if (catalogues.length === 0) {
    console.error("no catalogues found");
    process.exit(2);
  }
  for (const [name, cat] of catalogues) {
    const target = join(webDir, cat.TARGET);
    const pristine = readFileSync(target, "utf8");
    console.log(`\n=== ${name} (${cat.TARGET}) ===`);
    const base = runTests(webDir, cat.TESTS);
    if (base.code !== 0 || base.ran === 0) {
      console.log(`  BASELINE ${base.ran === 0 ? "EMPTY" : "RED"} for ${cat.TESTS}: refusing to judge mutants`);
      survived++;
      per.push([name, 0, 1]);
      continue;
    }
    const c0 = caught, s0 = survived;
    for (const [label, oldSrc, newSrc, expect] of cat.MUTATIONS) {
      const hits = pristine.split(oldSrc).length - 1;
      if (hits !== 1) {
        console.log(`  ANCHOR   ${label}: ${hits} matches`);
        survived++;
        continue;
      }
      writeFileSync(target, pristine.replace(oldSrc, newSrc));
      const res = runTests(webDir, cat.TESTS);
      writeFileSync(target, pristine);
      if (res.code === 0) {
        if (expect === null) console.log(`  ALLOWED  ${label}\n           ${cat.SURVIVORS[label]}`);
        else { console.log(`  SURVIVED ${label}  (expected "${expect}")`); survived++; }
      } else if (expect !== null && res.failed.includes(expect)) {
        console.log(`  CAUGHT   ${label} -> ${expect}`);
        caught++;
      } else {
        console.log(`  WEAK     ${label} -> ${res.failed[0] ?? "build/bundle failure"}, not "${expect}"`);
        caught++;
        weak++;
      }
    }
    per.push([name, caught - c0, survived - s0]);
  }
  console.log("\n--- per catalogue ---");
  for (const [n, c, s] of per) console.log(`  ${n.padEnd(20)} caught ${String(c).padStart(3)}  survived ${s}`);
  console.log(`\ncaught ${caught}, survived ${survived}` + (weak ? `, ${weak} caught by a different test than claimed` : ""));
  process.exitCode = survived ? 1 : 0;
} finally {
  rmSync(work, { recursive: true, force: true });
}
