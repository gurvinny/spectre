// Adaptive render quality: the guard that keeps weak clients usable.
export const TARGET = "src/lib/viz3d/quality.ts";
export const TESTS = "src/lib/viz3d/quality.test.ts";
export const MUTATIONS = [
  ["high-threshold-raised", "if (avgFps >= 45) return \"high\";", "if (avgFps >= 50) return \"high\";", "classifyFps thresholds"],
  ["med-threshold-off-by-one", "if (avgFps >= 24) return \"med\";", "if (avgFps > 24) return \"med\";", "classifyFps thresholds"],
  ["demotion-needs-streak", "if (s < c) return { tier: sample, streak: 0 }; // demote fast", "if (s < c && streak > 0) return { tier: sample, streak: 0 };", "nextTier demotes after a single bad window"],
  ["promotes-on-first-good-window", "if (ns >= 2) return", "if (ns >= 1) return", "nextTier promotes only after two consecutive good windows, one step"],
  ["promotes-straight-to-high", "return { tier: BY_RANK[c + 1], streak: 0 }; // promote one step", "return { tier: sample, streak: 0 };", "nextTier promotes only after two consecutive good windows, one step"],
  ["steady-keeps-streak", "return { tier: cur, streak: 0 }; // steady", "return { tier: cur, streak };", "nextTier steady window resets streak"],
  ["reduced-motion-ignored", "if (reducedMotion) return \"low\";", "", "effectiveTier override matrix"],
  ["beauty-ignored", "if (mode === \"beauty\") return \"high\";", "", "effectiveTier override matrix"],
  ["low-tier-still-sweeps", "        sweep: false,\n        sweepPeriod: 0,", "        sweep: true,\n        sweepPeriod: 0,", "motionForTier: low is fully static"],
  ["low-tier-autorotates", "        haloBreathing: false,\n        autoRotate: false,\n      };\n  }", "        haloBreathing: false,\n        autoRotate: true,\n      };\n  }", "motionForTier: low is fully static"],
];
export const SURVIVORS = {};
