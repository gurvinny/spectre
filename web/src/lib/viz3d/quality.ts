/**
 * Adaptive quality tiers for the 3D battlespace. Pure logic — no three/react —
 * so the FPS→tier policy stays unit-testable. A live sampler feeds observed FPS
 * into `classifyFps`; `nextTier` applies hysteresis (demote fast, promote slow)
 * so the scene doesn't oscillate; `effectiveTier` folds in the user's manual mode
 * and the OS reduced-motion preference; `motionForTier` is the single source of
 * truth for which continuous animations are allowed to run. Author: gurvinny
 */

export type Tier = "low" | "med" | "high";
export type PerfMode = "performance" | "balanced" | "beauty";

export interface MotionFlags {
  /** Rotating radar sweep + node flares. */
  sweep: boolean;
  /** Sweep rotation period in seconds (0 when sweep is off). */
  sweepPeriod: number;
  /** Traveling pulses along association + mesh edges. */
  edgeFlow: boolean;
  /** Sensor markers pulse at their live fps. */
  sensorPulse: boolean;
  /** Volatility halos breathe (high tier only). */
  haloBreathing: boolean;
  /** Slow cinematic idle camera drift (high tier only). */
  autoRotate: boolean;
}

const RANK: Record<Tier, number> = { low: 0, med: 1, high: 2 };
const BY_RANK: Tier[] = ["low", "med", "high"];

/** Observed average FPS → a target tier. */
export function classifyFps(avgFps: number): Tier {
  if (avgFps >= 45) return "high";
  if (avgFps >= 24) return "med";
  return "low";
}

/**
 * Hysteresis reducer. A bad window (sample below current) demotes immediately so
 * a struggling client recovers fast; a good window (sample above current) only
 * promotes after two consecutive good windows, one step at a time, so we don't
 * bounce back into a tier the client can't hold. Returns the new tier + streak.
 */
export function nextTier(
  cur: Tier,
  sample: Tier,
  streak: number,
): { tier: Tier; streak: number } {
  const c = RANK[cur];
  const s = RANK[sample];
  if (s < c) return { tier: sample, streak: 0 }; // demote fast
  if (s > c) {
    const ns = streak + 1;
    if (ns >= 2) return { tier: BY_RANK[c + 1], streak: 0 }; // promote one step
    return { tier: cur, streak: ns };
  }
  return { tier: cur, streak: 0 }; // steady
}

/**
 * Fold the auto tier together with the manual override and reduced-motion. The
 * accessibility preference wins over everything; explicit modes hard-pin the
 * tier; "balanced" defers to the adaptive auto tier.
 */
export function effectiveTier(
  auto: Tier,
  mode: PerfMode,
  reducedMotion: boolean,
): Tier {
  if (reducedMotion) return "low";
  if (mode === "performance") return "low";
  if (mode === "beauty") return "high";
  return auto;
}

/** Which continuous animations run at a given tier. Low = fully static/idle. */
export function motionForTier(tier: Tier): MotionFlags {
  switch (tier) {
    case "high":
      return {
        sweep: true,
        sweepPeriod: 6,
        edgeFlow: true,
        sensorPulse: true,
        haloBreathing: true,
        autoRotate: true,
      };
    case "med":
      return {
        sweep: true,
        sweepPeriod: 8,
        edgeFlow: true,
        sensorPulse: true,
        haloBreathing: false,
        autoRotate: false,
      };
    default:
      return {
        sweep: false,
        sweepPeriod: 0,
        edgeFlow: false,
        sensorPulse: false,
        haloBreathing: false,
        autoRotate: false,
      };
  }
}
