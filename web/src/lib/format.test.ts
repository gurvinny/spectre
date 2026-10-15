/**
 * Channel histogram helpers.
 * Author: gurvinny
 */
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  channelsFromFrames, compact, countByChannel, fmtUptime, rssiColor, rssiToStrength,
  severityColor,
} from "@/lib/format";

test("channelsFromFrames counts per channel and skips null", () => {
  const out = channelsFromFrames([
    { ch: 6 }, { ch: 6 }, { ch: 11 }, { ch: null },
  ]);
  assert.equal(out["6"], 2);
  assert.equal(out["11"], 1);
  // Number(null) is 0, so a missing channel must be rejected before coercion
  // rather than silently recorded as channel 0.
  assert.equal(out["0"], undefined);
});

test("channelsFromFrames ignores a non-integer channel", () => {
  // The value arrives as JSON, so the declared type is not a runtime promise.
  const out = channelsFromFrames([
    { ch: "__proto__" as unknown as number },
    { ch: 1.5 as unknown as number },
    { ch: 3 },
  ]);
  assert.equal(out["3"], 1);
  assert.equal(Object.keys(out).length, 1);
});

test("channelsFromFrames cannot reach Object.prototype", () => {
  const out = channelsFromFrames([{ ch: 1 }]);
  assert.equal(Object.getPrototypeOf(out), null);
  assert.equal(({} as Record<string, unknown>).polluted, undefined);
});

test("countByChannel respects the time window and skips null", () => {
  const out = countByChannel(
    [
      { ch: 6, ts: 100 }, { ch: 6, ts: 50 },
      { ch: 11, ts: 150 }, { ch: null, ts: 200 },
    ],
    100,
  );
  assert.equal(out[6], 1);      // the ts:50 frame is outside the window
  assert.equal(out[11], 1);
  assert.equal(out[0], undefined);
});

test("rssiToStrength maps -90..-30 dBm onto 0..1 and clamps", () => {
  assert.equal(rssiToStrength(-90), 0);
  assert.equal(rssiToStrength(-60), 0.5);
  assert.equal(rssiToStrength(-30), 1);
  assert.equal(rssiToStrength(-120), 0);
  assert.equal(rssiToStrength(-10), 1);
  assert.equal(rssiToStrength(null), 0);
});

test("rssiColor bands strong, middling and weak signal", () => {
  assert.equal(rssiColor(-35), "var(--color-phosphor)");
  assert.equal(rssiColor(-60), "var(--color-rf-amber)");
  assert.equal(rssiColor(-85), "var(--color-alert)");
});

test("fmtUptime picks the two most significant units", () => {
  assert.equal(fmtUptime(59), "0m 59s");
  assert.equal(fmtUptime(3 * 3600 + 25 * 60 + 9), "3h 25m");
  assert.equal(fmtUptime(2 * 86400 + 5 * 3600), "2d 5h");
});

test("compact abbreviates thousands and millions", () => {
  assert.deepEqual([compact(999), compact(1500), compact(2_345_678)],
                   ["999", "1.5k", "2.35M"]);
});

test("severityColor falls back to info for unknown severities", () => {
  assert.equal(severityColor("critical"), "var(--color-sev-critical)");
  assert.equal(severityColor("nonsense"), "var(--color-sev-info)");
});
