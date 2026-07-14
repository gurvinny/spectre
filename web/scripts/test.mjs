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
    `--outdir=${outDir}`,
    "--out-extension:.js=.mjs",
  ],
  { stdio: "inherit", cwd: webRoot },
);

const bundles = readdirSync(outDir)
  .filter((n) => n.endsWith(".test.mjs"))
  .map((n) => join(outDir, n));
execFileSync("node", ["--test", ...bundles], { stdio: "inherit" });
