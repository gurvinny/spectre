// Polar layout: RSSI drives radius and height.
export const TARGET = "src/lib/viz3d/layout.ts";
export const TESTS = "src/lib/viz3d/layout.test.ts";
export const MUTATIONS = [
  ["hash-not-unsigned", "return (h >>> 0) / 4294967295;", "return h / 4294967295;", "hashUnit is deterministic and within [0,1)"],
  ["strength-unclamped", "  return Math.max(0, Math.min(1, (rssi + 90) / 60));\n}\n\n", "  return (rssi + 90) / 60;\n}\n\n", "strengthOf maps dBm to 0..1, clamped"],
  ["radius-inverted", "return R_MAX * (0.15 + 0.85 * (1 - strength));\n}", "return R_MAX * (0.15 + 0.85 * strength);\n}", "shellRadius: strong signal near axis, weak splayed out"],
  ["height-inverted", "return Y_FLOOR + strength * (Y_TOP - Y_FLOOR);\n}", "return Y_TOP - strength * (Y_TOP - Y_FLOOR);\n}", "shellHeight: strong rides high, weak sinks"],
];
export const SURVIVORS = {};
