/**
 * Board health panel logic: liveness, warning levels, and building the
 * commands the console may send. The firmware validates every command again
 * and acks errors; this only catches mistakes before they reach the board.
 * Author: gurvinny
 */
import type { BoardAck } from "@/lib/types";

/** Telemetry every 10 s and a sweep every few seconds: 30 s of silence is odd. */
export const STALE_S = 30;
export const SILENT_S = 120;
export const DWELL_MIN_MS = 50;
export const DWELL_MAX_MS = 5000;
export const MAX_CHANNELS = 32;

export type Liveness = "live" | "stale" | "silent";
export type Level = "ok" | "warn" | "crit" | "none";

export function liveness(lastSeen: number | null, nowS: number): Liveness {
  if (lastSeen == null) return "silent";
  const age = nowS - lastSeen;
  if (age <= STALE_S) return "live";
  if (age <= SILENT_S) return "stale";
  return "silent";
}

function level(v: number | null, warn: number, crit: number): Level {
  if (v == null || !Number.isFinite(v)) return "none";
  if (v >= crit) return "crit";
  if (v >= warn) return "warn";
  return "ok";
}

/** Percent of received frames lost before the host (ring full, line overflow). */
export const lossLevel = (pct: number | null) => level(pct, 0.5, 2);
/** Fraction of the UART line rate in use; past ~90% lines start queueing. */
export const loadLevel = (frac: number | null) => level(frac, 0.7, 0.9);
/** Lines from the board that did not parse since the sensor started: any is worth a look. */
export const malformedLevel = (n: number | null) => level(n, 1, Infinity);

export function levelColor(l: Level | Liveness): string {
  switch (l) {
    case "ok": case "live": return "var(--color-phosphor)";
    case "warn": case "stale": return "var(--color-rf-amber)";
    case "crit": case "silent": return "var(--color-alert)";
    default: return "var(--color-ink-mute)";
  }
}

export function fmtPct(v: number | null, digits = 1): string {
  return v == null || !Number.isFinite(v) ? "—" : `${v.toFixed(digits)}%`;
}

export function fmtFrac(v: number | null): string {
  return v == null ? "—" : fmtPct(v * 100, 0);
}

export type Parsed<T> = { ok: true; value: T } | { ok: false; error: string };

/** "1, 6, 11" -> [1, 6, 11]; blank means "leave the list alone". */
export function parseChannels(text: string): Parsed<number[] | undefined> {
  const t = text.trim();
  if (!t) return { ok: true, value: undefined };
  const parts = t.split(/[\s,]+/).filter(Boolean);
  const out: number[] = [];
  for (const p of parts) {
    if (!/^\d+$/.test(p)) return { ok: false, error: `"${p}" is not a channel number` };
    const n = Number(p);
    if (out.includes(n)) return { ok: false, error: `channel ${n} is listed twice` };
    out.push(n);
  }
  if (out.length > MAX_CHANNELS) {
    return { ok: false, error: `at most ${MAX_CHANNELS} channels` };
  }
  return { ok: true, value: out };
}

function parseInteger(text: string, name: string, min: number, max: number): Parsed<number | undefined> {
  const t = text.trim();
  if (!t) return { ok: true, value: undefined };
  if (!/^\d+$/.test(t)) return { ok: false, error: `${name} must be a whole number` };
  const n = Number(t);
  if (n < min || n > max) return { ok: false, error: `${name} must be ${min}-${max}` };
  return { ok: true, value: n };
}

export type SetForm = { channels: string; dwell: string; pin: string };

/** A `set` command from the form, holding only the fields that were filled in. */
export function buildSetCommand(form: SetForm): Parsed<Record<string, unknown>> {
  const cmd: Record<string, unknown> = { cmd: "set" };
  const ch = parseChannels(form.channels);
  if (!ch.ok) return ch;
  if (ch.value) cmd.channels = ch.value;
  const dwell = parseInteger(form.dwell, "dwell", DWELL_MIN_MS, DWELL_MAX_MS);
  if (!dwell.ok) return dwell;
  if (dwell.value !== undefined) cmd.dwell_ms = dwell.value;
  // 0 unpins; the firmware checks the channel against the band.
  const pin = parseInteger(form.pin, "pin", 0, 196);
  if (!pin.ok) return pin;
  if (pin.value !== undefined) cmd.pin = pin.value;
  if (Object.keys(cmd).length === 1) return { ok: false, error: "nothing to change" };
  return { ok: true, value: cmd };
}

export function ackText(ack: BoardAck | null | undefined): string {
  if (!ack) return "no reply yet";
  if (ack.ok === true) return `${ack.cmd ?? "command"} ok`;
  return `${ack.cmd ?? "command"} refused: ${ack.err ?? "unknown error"}`;
}
