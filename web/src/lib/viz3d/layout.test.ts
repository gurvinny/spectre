/** Unit checks for the deterministic layout math. Author: gurvinny */
import { test } from "node:test";
import assert from "node:assert/strict";
import {
  hashUnit,
  strengthOf,
  shellRadius,
  shellHeight,
  R_MAX,
} from "@/lib/viz3d/layout";

test("hashUnit is deterministic and within [0,1)", () => {
  assert.equal(hashUnit("ExampleNet"), hashUnit("ExampleNet"));
  for (const s of ["a", "AA:BB", "", "IoT-Net", "x".repeat(64)]) {
    const h = hashUnit(s);
    assert.ok(h >= 0 && h < 1, `${s} → ${h}`);
  }
  assert.notEqual(hashUnit("a"), hashUnit("b"));
});

test("strengthOf maps dBm to 0..1, clamped", () => {
  assert.equal(strengthOf(null), 0);
  assert.equal(strengthOf(-90), 0);
  assert.equal(strengthOf(-30), 1);
  assert.equal(strengthOf(-120), 0); // clamp low
  assert.equal(strengthOf(0), 1); // clamp high
  assert.ok(Math.abs(strengthOf(-60) - 0.5) < 1e-9);
});

test("shellRadius: strong signal near axis, weak splayed out", () => {
  assert.ok(shellRadius(1) < shellRadius(0));
  assert.ok(Math.abs(shellRadius(0) - R_MAX) < 1e-9); // weakest at outer shell
  assert.ok(shellRadius(1) > 0);
});

test("shellHeight: strong rides high, weak sinks", () => {
  assert.ok(shellHeight(1) > shellHeight(0));
  assert.ok(shellHeight(0) < 0); // floor is below origin
});
