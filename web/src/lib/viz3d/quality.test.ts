/** Unit checks for the adaptive-quality policy. Author: gurvinny */
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  classifyFps,
  nextTier,
  effectiveTier,
  motionForTier,
} from "@/lib/viz3d/quality";

test("classifyFps thresholds", () => {
  assert.equal(classifyFps(60), "high");
  assert.equal(classifyFps(45), "high");
  assert.equal(classifyFps(44), "med");
  assert.equal(classifyFps(24), "med");
  assert.equal(classifyFps(23), "low");
  assert.equal(classifyFps(0), "low");
});

test("nextTier demotes after a single bad window", () => {
  const r = nextTier("high", "low", 0);
  assert.equal(r.tier, "low");
  assert.equal(r.streak, 0);
});

test("nextTier promotes only after two consecutive good windows, one step", () => {
  const a = nextTier("low", "high", 0); // 1st good window
  assert.equal(a.tier, "low");
  assert.equal(a.streak, 1);
  const b = nextTier("low", "high", a.streak); // 2nd good window
  assert.equal(b.tier, "med"); // one step, not straight to high
  assert.equal(b.streak, 0);
});

test("nextTier steady window resets streak", () => {
  const r = nextTier("med", "med", 1);
  assert.equal(r.tier, "med");
  assert.equal(r.streak, 0);
});

test("effectiveTier override matrix", () => {
  assert.equal(effectiveTier("high", "performance", false), "low");
  assert.equal(effectiveTier("low", "beauty", false), "high");
  assert.equal(effectiveTier("high", "balanced", false), "high");
  assert.equal(effectiveTier("med", "balanced", false), "med");
  // reduced-motion wins over everything, even beauty
  assert.equal(effectiveTier("high", "beauty", true), "low");
});

test("motionForTier: low is fully static", () => {
  const low = motionForTier("low");
  assert.deepEqual(low, {
    sweep: false,
    sweepPeriod: 0,
    edgeFlow: false,
    sensorPulse: false,
    haloBreathing: false,
    autoRotate: false,
  });
  assert.equal(motionForTier("med").haloBreathing, false);
  assert.equal(motionForTier("high").haloBreathing, true);
  assert.ok(motionForTier("high").sweepPeriod < motionForTier("med").sweepPeriod);
});
