/**
 * Feature flags.
 * Author: gurvinny
 */
import assert from "node:assert/strict";
import { test } from "node:test";
import { experimentalEnabled, visibleNav } from "@/lib/flags";

test("only an explicit true enables experimental views", () => {
  assert.equal(experimentalEnabled("true"), true);
  assert.equal(experimentalEnabled(" TRUE "), true);
  for (const v of [undefined, "", "false", "1", "yes", "truthy"]) {
    assert.equal(experimentalEnabled(v), false, String(v));
  }
});

test("experimental entries are hidden unless enabled, order kept", () => {
  const items = [
    { href: "/", label: "Home", icon: null },
    { href: "/x", label: "X", icon: null, experimental: true },
    { href: "/y", label: "Y", icon: null, experimental: false },
  ];
  assert.deepEqual(visibleNav(items, false).map((i) => i.href), ["/", "/y"]);
  assert.deepEqual(visibleNav(items, true).map((i) => i.href), ["/", "/x", "/y"]);
});
