/**
 * Channel histogram helpers.
 * Author: gurvinny
 */
import assert from "node:assert/strict";
import { test } from "node:test";
import { channelsFromFrames, countByChannel } from "@/lib/format";

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
