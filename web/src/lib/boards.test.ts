/**
 * Board health panel logic.
 * Author: gurvinny
 */
import assert from "node:assert/strict";
import { test } from "node:test";
import {
  ackText, boardLink, buildSetCommand, fmtFrac, fmtPct, fmtRate, levelColor, linkStat, linkText,
  liveness, loadLevel, lossLevel, malformedLevel, parseChannels,
} from "@/lib/boards";
import type { Board, BoardHealth } from "@/lib/types";

test("liveness ages a board from live to stale to silent", () => {
  assert.equal(liveness(null, 1000), "silent");
  // Never seen is silent even right after the epoch, not "seen at 0".
  assert.equal(liveness(null, 10), "silent");
  assert.equal(liveness(1000, 1000), "live");
  assert.equal(liveness(970, 1000), "live");
  assert.equal(liveness(969, 1000), "stale");
  assert.equal(liveness(880, 1000), "stale");
  assert.equal(liveness(879, 1000), "silent");
});

test("loss and load levels have their own thresholds", () => {
  assert.equal(lossLevel(null), "none");
  assert.equal(lossLevel(0.49), "ok");
  assert.equal(lossLevel(0.5), "warn");
  assert.equal(lossLevel(1.99), "warn");
  assert.equal(lossLevel(2), "crit");
  assert.equal(loadLevel(0.69), "ok");
  assert.equal(loadLevel(0.7), "warn");
  assert.equal(loadLevel(0.9), "crit");
  assert.equal(loadLevel(Number.NaN), "none");
});

test("level colours", () => {
  assert.equal(levelColor("ok"), "var(--color-phosphor)");
  assert.equal(levelColor("live"), "var(--color-phosphor)");
  assert.equal(levelColor("warn"), "var(--color-rf-amber)");
  assert.equal(levelColor("stale"), "var(--color-rf-amber)");
  assert.equal(levelColor("crit"), "var(--color-alert)");
  assert.equal(levelColor("silent"), "var(--color-alert)");
  assert.equal(levelColor("none"), "var(--color-ink-mute)");
});

test("percent formatting shows a dash for unknown", () => {
  assert.equal(fmtPct(null), "—");
  assert.equal(fmtPct(3.456), "3.5%");
  assert.equal(fmtPct(3.456, 2), "3.46%");
  assert.equal(fmtFrac(0.5), "50%");
  assert.equal(fmtFrac(null), "—");
});

test("parseChannels reads commas and spaces, blank leaves the list alone", () => {
  assert.deepEqual(parseChannels(""), { ok: true, value: undefined });
  assert.deepEqual(parseChannels("  "), { ok: true, value: undefined });
  assert.deepEqual(parseChannels("1, 6 11"), { ok: true, value: [1, 6, 11] });
  assert.deepEqual(parseChannels("36,40,"), { ok: true, value: [36, 40] });
});

test("parseChannels rejects junk, duplicates and too many", () => {
  for (const bad of ["1,x", "6.5", "-1", "1e2"]) {
    assert.equal(parseChannels(bad).ok, false, bad);
  }
  const dup = parseChannels("1,6,1");
  assert.equal(dup.ok, false);
  assert.match((dup as { error: string }).error, /twice/);
  const many = Array.from({ length: 33 }, (_, i) => i + 1).join(",");
  assert.equal(parseChannels(many).ok, false);
  const max = Array.from({ length: 32 }, (_, i) => i + 1).join(",");
  assert.equal(parseChannels(max).ok, true);
});

test("buildSetCommand sends only filled fields", () => {
  assert.deepEqual(buildSetCommand({ channels: "36,40", dwell: "", pin: "" }),
    { ok: true, value: { cmd: "set", channels: [36, 40] } });
  assert.deepEqual(buildSetCommand({ channels: "", dwell: "250", pin: "0" }),
    { ok: true, value: { cmd: "set", dwell_ms: 250, pin: 0 } });
});

test("buildSetCommand enforces the dwell range and refuses an empty form", () => {
  assert.equal(buildSetCommand({ channels: "", dwell: "49", pin: "" }).ok, false);
  assert.equal(buildSetCommand({ channels: "", dwell: "50", pin: "" }).ok, true);
  assert.equal(buildSetCommand({ channels: "", dwell: "5000", pin: "" }).ok, true);
  assert.equal(buildSetCommand({ channels: "", dwell: "5001", pin: "" }).ok, false);
  assert.equal(buildSetCommand({ channels: "", dwell: "2.5", pin: "" }).ok, false);
  assert.equal(buildSetCommand({ channels: "", dwell: "250.5", pin: "" }).ok, false);
  assert.equal(buildSetCommand({ channels: "", dwell: "", pin: "x" }).ok, false);
  // A bad channel list fails the command even when another field is fine.
  const dup = buildSetCommand({ channels: "1,1", dwell: "250", pin: "" });
  assert.equal(dup.ok, false);
  assert.match((dup as { error: string }).error, /twice/);
  const empty = buildSetCommand({ channels: " ", dwell: "", pin: "" });
  assert.deepEqual(empty, { ok: false, error: "nothing to change" });
});

test("ackText says what the board answered", () => {
  assert.equal(ackText(null), "no reply yet");
  assert.equal(ackText({ cmd: "set", ok: true, received_at: 1 }), "set ok");
  assert.equal(ackText({ cmd: "set", ok: false, err: "bad dwell", received_at: 1 }),
    "set refused: bad dwell");
  assert.equal(ackText({ received_at: 1 }), "command refused: unknown error");
});

test("any line that did not parse is a warning, never critical", () => {
  assert.equal(malformedLevel(null), "none");
  assert.equal(malformedLevel(0), "ok");
  assert.equal(malformedLevel(1), "warn");
  assert.equal(malformedLevel(1e9), "warn");
});

const health = (over: Partial<BoardHealth> = {}): BoardHealth => ({
  rx_total: null, emitted: null, lost: null, loss_pct: null, drops: {}, uart_bps: null,
  uart_load: null, queue_fill: null, heap: null, heap_min: null, temp_c: null, uptime_ms: null,
  ...over,
});
const fwOf = (over: Partial<NonNullable<Board["firmware"]>> = {}): Board["firmware"] => ({
  chip: "esp32c5", fw: "v2", ver: "2.1.0", elf_sha: null, reset: null, baud: 921600, caps: null,
  booted_at: null, ...over,
});

test("telemetry names the link first, then the boot line, else it is a UART", () => {
  assert.equal(boardLink({ health: health({ link: "usb" }), firmware: fwOf({ link: "uart" }) }), "usb");
  assert.equal(boardLink({ health: health({ link: "uart" }), firmware: fwOf({ link: "usb" }) }), "uart");
  assert.equal(boardLink({ health: health(), firmware: fwOf({ link: "usb" }) }), "usb");
  assert.equal(boardLink({ health: health({ link: null }), firmware: fwOf({ link: "usb" }) }), "usb");
  assert.equal(boardLink({ health: health(), firmware: fwOf() }), "uart");
  assert.equal(boardLink({ health: health(), firmware: null }), "uart");
});

test("a USB board shows throughput and refused lines, never a UART load", () => {
  const s = linkStat({
    health: health({ link: "usb", usb_bps: 6400, drop_usb: 860, uart_load: 0.95, queue_fill: 0.035 }),
    firmware: fwOf({ link: "usb" }),
  });
  assert.deepEqual(s, {
    label: "USB link", value: "6.4 KB/s", level: "none",
    sub: "queue peak 4% · 860 refused since boot",
  });
  assert.equal(linkStat({ health: health({ link: "usb" }), firmware: null }).sub, undefined);
  assert.equal(linkStat({ health: health({ link: "usb", drop_usb: 0 }), firmware: null }).sub,
    "0 refused since boot");
  assert.equal(linkStat({ health: health({ link: "usb", queue_fill: 0.5 }), firmware: null }).sub,
    "queue peak 50%");
});

test("a UART board shows its load against the line rate", () => {
  assert.deepEqual(linkStat({ health: health({ uart_load: 0.92, queue_fill: 0.86 }), firmware: fwOf() }), {
    label: "UART load", value: "92%", level: "crit", sub: "queue peak 86%",
  });
  assert.deepEqual(linkStat({ health: health({ uart_load: 0.1 }), firmware: fwOf() }),
    { label: "UART load", value: "10%", level: "ok", sub: undefined });
});

test("rates read in bytes or kilobytes per second", () => {
  assert.equal(fmtRate(null), "—");
  assert.equal(fmtRate(undefined), "—");
  assert.equal(fmtRate(Number.NaN), "—");
  assert.equal(fmtRate(0), "0 B/s");
  assert.equal(fmtRate(999.4), "999 B/s");
  assert.equal(fmtRate(1000), "1.0 KB/s");
  assert.equal(fmtRate(87_600), "87.6 KB/s");
});

test("the firmware cell names native USB instead of a baud it does not use", () => {
  assert.equal(linkText({ health: health({ link: "usb" }), firmware: fwOf() }), "native USB");
  assert.equal(linkText({ health: health(), firmware: fwOf() }), "921600 baud");
  assert.equal(linkText({ health: health(), firmware: fwOf({ baud: null }) }), "baud ?");
  assert.equal(linkText({ health: health(), firmware: null }), "baud ?");
});
