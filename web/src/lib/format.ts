/** Formatting + color helpers shared across the console. Author: gurvinny */

export const SEVERITY_ORDER = ["critical", "high", "medium", "low", "info"] as const;
export type Severity = (typeof SEVERITY_ORDER)[number];

export function severityColor(sev: string): string {
  switch (sev) {
    case "critical": return "var(--color-sev-critical)";
    case "high": return "var(--color-sev-high)";
    case "medium": return "var(--color-sev-medium)";
    case "low": return "var(--color-sev-low)";
    default: return "var(--color-sev-info)";
  }
}

export function bandColor(band: string): string {
  if (band.startsWith("2.4")) return "var(--color-phosphor)";
  if (band.startsWith("5")) return "var(--color-violet)";
  return "var(--color-ink-mute)";
}

/** Map an RSSI (dBm) to a 0–1 signal strength for meters. */
export function rssiToStrength(rssi: number | null): number {
  if (rssi === null || rssi === undefined) return 0;
  // -30 dBm ≈ excellent, -90 dBm ≈ floor.
  return Math.max(0, Math.min(1, (rssi + 90) / 60));
}

export function rssiColor(rssi: number | null): string {
  const s = rssiToStrength(rssi);
  if (s > 0.66) return "var(--color-phosphor)";
  if (s > 0.33) return "var(--color-rf-amber)";
  return "var(--color-alert)";
}

const FRAME_COLORS: Record<string, string> = {
  BEACON: "var(--color-phosphor-dim)",
  PROBE_REQ: "var(--color-rf-amber)",
  PROBE_RESP: "var(--color-phosphor)",
  DATA: "var(--color-ink-dim)",
  DEAUTH: "var(--color-alert)",
  DISASSOC: "var(--color-alert)",
  AUTH: "var(--color-violet)",
};
export function frameColor(type: string): string {
  return FRAME_COLORS[type] ?? "var(--color-ink-mute)";
}

export function timeAgo(epoch: number): string {
  const s = Math.max(0, Date.now() / 1000 - epoch);
  if (s < 60) return `${Math.floor(s)}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 86400) return `${Math.floor(s / 3600)}h`;
  return `${Math.floor(s / 86400)}d`;
}

export function fmtClock(epoch: number): string {
  return new Date(epoch * 1000).toLocaleTimeString([], {
    hour12: false,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

export function fmtUptime(seconds: number): string {
  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (d) return `${d}d ${h}h`;
  if (h) return `${h}h ${m}m`;
  return `${m}m ${Math.floor(seconds % 60)}s`;
}

/** Build a per-channel activity histogram from a live frame window. */
export function channelsFromFrames(
  frames: { ch: number | null }[],
): Record<string, number> {
  const out: Record<string, number> = {};
  for (const f of frames) {
    if (f.ch === null || f.ch === undefined) continue;
    const k = String(f.ch);
    out[k] = (out[k] ?? 0) + 1;
  }
  return out;
}

/** Count frames per channel that arrived at/after `sinceTs` — one waterfall row. */
export function countByChannel(
  frames: { ch: number | null; ts: number }[],
  sinceTs: number,
): Record<number, number> {
  const out: Record<number, number> = {};
  for (const f of frames) {
    if (f.ch == null || f.ts < sinceTs) continue;
    out[f.ch] = (out[f.ch] ?? 0) + 1;
  }
  return out;
}

/** True for a 2.4 GHz channel number (1–14). */
export function is24(ch: number): boolean {
  return ch <= 14;
}

/** Sort a set of channel numbers so 2.4 GHz (1–14) leads, then 5 GHz ascending. */
export function sortChannels(chs: Iterable<number>): number[] {
  return [...new Set(chs)].sort((a, b) => a - b);
}

export function compact(n: number): string {
  if (n < 1000) return `${n}`;
  if (n < 1_000_000) return `${(n / 1000).toFixed(1)}k`;
  return `${(n / 1_000_000).toFixed(2)}M`;
}
