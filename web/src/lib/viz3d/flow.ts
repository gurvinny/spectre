/**
 * Pure math for the live edge data-flow layer: decide how many traveling pulses
 * each association/mesh link gets (by traffic activity + quality tier) and where
 * a pulse sits along its edge at time t. No three/react imports so the selection
 * and phase math stay unit-testable; the component just reads positions.
 * Author: gurvinny
 */
import type { Vec3 } from "@/lib/viz3d/layout";
import { hashUnit } from "@/lib/viz3d/layout";
import type { EdgeModel } from "@/lib/viz3d/types";
import type { Tier } from "@/lib/viz3d/quality";

/** Seconds for a pulse to travel one edge end-to-end. */
export const PULSE_PERIOD = 2.6;
/** Hard cap on simultaneous pulses (shared across assoc + mesh). */
export const PULSE_LIMIT = 96;

export interface FlowPulse {
  from: string;
  to: string;
  kind: "assoc" | "mesh";
  /** 0..1 start offset so pulses on different edges don't march in lockstep. */
  phase: number;
  /** 0..1 brightness/heat, from edge activity. */
  intensity: number;
}

/** Fraction (0..1) along the edge at time `t`, wrapping each period. */
export function pulseFrac(t: number, phase: number, period = PULSE_PERIOD): number {
  const f = (t / period + phase) % 1;
  return f < 0 ? f + 1 : f;
}

/** Linear interpolate a world position along the edge. */
export function pulsePos(a: Vec3, b: Vec3, frac: number): Vec3 {
  return [
    a[0] + (b[0] - a[0]) * frac,
    a[1] + (b[1] - a[1]) * frac,
    a[2] + (b[2] - a[2]) * frac,
  ];
}

/**
 * Build the pulse set for the current tier. Busy edges get more/brighter pulses;
 * at high tier hot links (activity ≥ 0.6) carry a second, phase-offset pulse.
 * Edges are taken activity-first and truncated at PULSE_LIMIT.
 */
export function pulsesForEdges(
  assoc: EdgeModel[],
  mesh: EdgeModel[],
  tier: Tier,
  cap = PULSE_LIMIT,
): FlowPulse[] {
  if (tier === "low") return [];
  const minActivity = tier === "high" ? 0.05 : 0.15;

  const tagged: { e: EdgeModel; kind: "assoc" | "mesh" }[] = [
    ...assoc.map((e) => ({ e, kind: "assoc" as const })),
    ...mesh.map((e) => ({ e, kind: "mesh" as const })),
  ]
    .filter(({ e }) => (e.activity ?? 0) >= minActivity)
    .sort((a, b) => (b.e.activity ?? 0) - (a.e.activity ?? 0));

  const pulses: FlowPulse[] = [];
  for (const { e, kind } of tagged) {
    const phase = hashUnit(e.from + "→" + e.to);
    const intensity = Math.max(0.15, Math.min(1, e.activity ?? 0));
    pulses.push({ from: e.from, to: e.to, kind, phase, intensity });
    if (pulses.length >= cap) break;
    // High tier: a second pulse on genuinely hot links.
    if (tier === "high" && (e.activity ?? 0) >= 0.6) {
      pulses.push({
        from: e.from,
        to: e.to,
        kind,
        phase: (phase + 0.5) % 1,
        intensity,
      });
      if (pulses.length >= cap) break;
    }
  }
  return pulses;
}
