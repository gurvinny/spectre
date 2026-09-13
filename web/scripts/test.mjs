/**
 * Minimal unit-test runner for the pure viz3d logic. The modules import via the
 * `@/` tsconfig alias, which Node's native TS loader can't resolve, so we bundle
 * each `*.test.ts` with esbuild (aliasing `@` → ./src) into a temp dir and run
 * the bundles under `node --test`. No test framework dependency. Author: gurvinny
 */
import { execFileSync } from "node:child_process";
import { mkdtempSync, readdirSync, statSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const webRoot = dirname(dirname(fileURLToPath(import.meta.url)));
const srcDir = join(webRoot, "src");

function findTests(dir) {
  const out = [];
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) out.push(...findTests(p));
    else if (name.endsWith(".test.ts")) out.push(p);
  }
  return out;
}

const tests = findTests(srcDir);
if (tests.length === 0) {
  console.error("no *.test.ts files found under", srcDir);
  process.exit(1);
}

const outDir = mkdtempSync(join(tmpdir(), "bsp-test-"));
execFileSync(
  "npx",
  [
    "-y",
    "esbuild",
    ...tests,
    "--bundle",
    "--format=esm",
    "--platform=node",
    `--alias:@=${srcDir}`,
    // Pin the output layout to src/. Without this esbuild derives a base from
    // whatever inputs happen to exist, so adding one test outside the deepest
    // shared directory silently relocates every other bundle.
    `--outbase=${srcDir}`,
    `--outdir=${outDir}`,
    "--out-extension:.js=.mjs",
  ],
  { stdio: "inherit", cwd: webRoot },
);

function findBundles(dir) {
  const out = [];
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) out.push(...findBundles(p));
    else if (name.endsWith(".test.mjs")) out.push(p);
  }
  return out;
}

const bundles = findBundles(outDir);

// A bundle count below the source count means tests were dropped rather than
// run. That failure is otherwise silent -- the suite just reports fewer passes.
if (bundles.length !== tests.length) {
  console.error(
    `expected ${tests.length} test bundles, found ${bundles.length} -- ` +
      "some tests would not have run",
  );
  process.exit(1);
}

execFileSync("node", ["--test", ...bundles], { stdio: "inherit" });
