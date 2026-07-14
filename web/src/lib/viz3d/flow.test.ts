/** Unit checks for the edge data-flow pulse math. Author: gurvinny */
import { test } from "node:test";
import assert from "node:assert/strict";
import { pulseFrac, pulsePos, pulsesForEdges, PULSE_LIMIT } from "@/lib/viz3d/flow";
import type { EdgeModel } from "@/lib/viz3d/types";

const edge = (from: string, to: string, activity: number): EdgeModel => ({
  from,
  to,
  activity,
});

test("pulseFrac wraps within [0,1)", () => {
  assert.ok(Math.abs(pulseFrac(0, 0, 2) - 0) < 1e-9);
  assert.ok(Math.abs(pulseFrac(1, 0, 2) - 0.5) < 1e-9);
  const f = pulseFrac(5.9, 0.3, 2);
  assert.ok(f >= 0 && f < 1);
});

test("pulsePos lerps endpoints", () => {
  assert.deepEqual(pulsePos([0, 0, 0], [10, 4, -2], 0), [0, 0, 0]);
  assert.deepEqual(pulsePos([0, 0, 0], [10, 4, -2], 1), [10, 4, -2]);
  assert.deepEqual(pulsePos([0, 0, 0], [10, 4, -2], 0.5), [5, 2, -1]);
});

test("low tier emits no pulses", () => {
  assert.deepEqual(pulsesForEdges([edge("a", "b", 1)], [], "low"), []);
});

test("med tier: one pulse per edge above 0.15 threshold", () => {
  const p = pulsesForEdges(
    [edge("a", "b", 0.2), edge("c", "d", 0.1)],
    [],
    "med",
  );
  assert.equal(p.length, 1);
  assert.equal(p[0].from, "a");
  assert.equal(p[0].kind, "assoc");
});

test("high tier: hot edge (>=0.6) gets a second, phase-offset pulse", () => {
  const p = pulsesForEdges([edge("a", "b", 0.9)], [], "high");
  assert.equal(p.length, 2);
  assert.ok(Math.abs(((p[1].phase - p[0].phase + 1) % 1) - 0.5) < 1e-9);
});

test("mesh edges are tagged and sorted with assoc by activity", () => {
  const p = pulsesForEdges([edge("a", "b", 0.3)], [edge("m1", "m2", 0.9)], "med");
  assert.equal(p[0].from, "m1"); // hottest first
  assert.equal(p[0].kind, "mesh");
});

test("pulses are capped at PULSE_LIMIT", () => {
  const many: EdgeModel[] = Array.from({ length: 200 }, (_, i) =>
    edge("c" + i, "ap", 0.9),
  );
  const p = pulsesForEdges(many, [], "high");
  assert.ok(p.length <= PULSE_LIMIT);
});
