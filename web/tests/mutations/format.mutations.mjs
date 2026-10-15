// Console formatting helpers. channelsFromFrames is the one fed by sniffed JSON.
export const TARGET = "src/lib/format.ts";
export const TESTS = "src/lib/format.test.ts";
export const MUTATIONS = [
  ["null-channel-counted-as-0", "    if (f.ch == null) continue;\n    const ch = Number(f.ch);\n    if (!Number.isInteger(ch)) continue;\n    const k",
   "    const ch = Number(f.ch);\n    if (!Number.isInteger(ch)) continue;\n    const k",
   "channelsFromFrames counts per channel and skips null"],
  ["non-integer-channel-accepted", "    if (!Number.isInteger(ch)) continue;\n    const k = String(ch);",
   "    const k = String(ch);", "channelsFromFrames ignores a non-integer channel"],
  ["prototype-map-restored", "  const out: Record<string, number> = Object.create(null);\n  for (const f of frames) {\n    // Reject",
   "  const out: Record<string, number> = {};\n  for (const f of frames) {\n    // Reject",
   "channelsFromFrames ignores a non-integer channel"],
  ["waterfall-window-ignored", "if (!Number.isInteger(ch) || f.ts < sinceTs) continue;",
   "if (!Number.isInteger(ch)) continue;", "countByChannel respects the time window and skips null"],
  ["strength-not-clamped-low", "return Math.max(0, Math.min(1, (rssi + 90) / 60));",
   "return Math.min(1, (rssi + 90) / 60);",
   "rssiToStrength maps -90..-30 dBm onto 0..1 and clamps"],
  ["strength-wrong-floor", "return Math.max(0, Math.min(1, (rssi + 90) / 60));",
   "return Math.max(0, Math.min(1, (rssi + 100) / 70));",
   "rssiToStrength maps -90..-30 dBm onto 0..1 and clamps"],
  ["rssi-colour-bands-swapped", 'if (s > 0.66) return "var(--color-phosphor)";',
   'if (s > 0.66) return "var(--color-rf-amber)";',
   "rssiColor bands strong, middling and weak signal"],
  ["uptime-days-dropped", "if (d) return `${d}d ${h}h`;", "",
   "fmtUptime picks the two most significant units"],
  ["compact-wrong-precision", "return `${(n / 1_000_000).toFixed(2)}M`;",
   "return `${(n / 1_000_000).toFixed(1)}M`;", "compact abbreviates thousands and millions"],
];
export const SURVIVORS = {};
