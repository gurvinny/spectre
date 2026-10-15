// Edge-flow pulses.
export const TARGET = "src/lib/viz3d/flow.ts";
export const TESTS = "src/lib/viz3d/flow.test.ts";
export const MUTATIONS = [
  ["negative-frac-not-wrapped", "return f < 0 ? f + 1 : f;", "return f;", "pulseFrac wraps within [0,1)"],
  ["lerp-wrong-axis", "a[1] + (b[1] - a[1]) * frac,", "a[1],", "pulsePos lerps endpoints"],
  ["low-tier-pulses", "if (tier === \"low\") return [];", "", "low tier emits no pulses"],
  ["med-threshold-lowered", "const minActivity = tier === \"high\" ? 0.05 : 0.15;", "const minActivity = 0.05;", "med tier: one pulse per edge above 0.15 threshold"],
  ["no-hot-second-pulse", "if (tier === \"high\" && (e.activity ?? 0) >= 0.6) {", "if (false) {", "high tier: hot edge (>=0.6) gets a second, phase-offset pulse"],
  ["second-pulse-same-phase", "phase: (phase + 0.5) % 1,", "phase,", "high tier: hot edge (>=0.6) gets a second, phase-offset pulse"],
  ["unsorted-by-activity", ".sort((a, b) => (b.e.activity ?? 0) - (a.e.activity ?? 0));", ";", "mesh edges are tagged and sorted with assoc by activity"],
  ["cap-ignored", "    if (pulses.length >= cap) break;\n    if (tier", "    if (tier", "pulses are capped at PULSE_LIMIT"],
];
export const SURVIVORS = {};
