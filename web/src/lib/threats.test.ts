/**
 * Live threat window: stored and pushed threats merged once each, newest first.
 * Author: gurvinny
 */
import assert from "node:assert/strict";
import { test } from "node:test";
import { mergeThreats, threatKey } from "@/lib/threats";
import type { Threat } from "@/lib/types";

const t = (ts: number, rule = "deauth_flood", over: Partial<Threat> = {}): Threat => ({
  ts, rule, severity: "high", rank: 3, title: rule, band: "2.4GHz",
  bssid: "00:00:5e:00:53:01", ssid: null, src: "00:00:5e:00:53:02", detail: {}, ...over,
});

test("a stored threat and its pushed copy count once", () => {
  const pushed = [t(105), t(100)];
  const stored = [{ ...t(100), wazuh_sent: true }, t(90)];
  const out = mergeThreats(pushed, stored, 10);
  assert.deepEqual(out.map((x) => x.ts), [105, 100, 90]);
  // The first list wins a tie, so a live push keeps its own copy.
  assert.equal(out[1].wazuh_sent, undefined);
});

test("threats that differ in any identity field are kept apart", () => {
  const base = t(100);
  for (const other of [
    t(101), t(100, "probe_flood"), t(100, "deauth_flood", { band: "5GHz" }),
    t(100, "deauth_flood", { src: "00:00:5e:00:53:03" }),
    t(100, "deauth_flood", { bssid: "00:00:5e:00:53:04" }),
    t(100, "deauth_flood", { src: null }), t(100, "deauth_flood", { bssid: null }),
  ]) {
    assert.notEqual(threatKey(other), threatKey(base));
    assert.equal(mergeThreats([base], [other], 10).length, 2);
  }
  // A missing source and a missing BSSID are not the same threat.
  assert.notEqual(threatKey(t(100, "x", { src: null, bssid: "b" })),
    threatKey(t(100, "x", { src: "b", bssid: null })));
});

test("the merged window is newest first whatever order the lists arrive in", () => {
  const out = mergeThreats([t(10), t(30)], [t(20), t(40)], 10);
  assert.deepEqual(out.map((x) => x.ts), [40, 30, 20, 10]);
});

test("the window keeps only the newest max threats", () => {
  const out = mergeThreats([t(1), t(2)], [t(3), t(4), t(5)], 3);
  assert.deepEqual(out.map((x) => x.ts), [5, 4, 3]);
  assert.deepEqual(mergeThreats([], [], 3), []);
  assert.deepEqual(mergeThreats([t(1)], [], 0), []);
});

test("a list's own repeats are dropped too", () => {
  assert.equal(mergeThreats([t(1), t(1)], [t(1)], 10).length, 1);
});
