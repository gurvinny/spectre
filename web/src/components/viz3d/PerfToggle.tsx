/**
 * DOM HUD control for the battlespace's adaptive-quality engine: a three-segment
 * PERF / BAL / BEAUTY mode switch plus a live badge of the effective render tier.
 * Rendered over the canvas as plain DOM (no in-scene text). Author: gurvinny
 */
"use client";

import { cn } from "@/lib/utils";
import type { PerfMode, Tier } from "@/lib/viz3d/quality";

const MODES: { key: PerfMode; label: string }[] = [
  { key: "performance", label: "PERF" },
  { key: "balanced", label: "BAL" },
  { key: "beauty", label: "BEAUTY" },
];

const TIER_COLOR: Record<Tier, string> = {
  low: "var(--color-ink-dim)",
  med: "var(--color-rf-amber)",
  high: "var(--color-phosphor)",
};

export function PerfToggle({
  mode,
  onMode,
  tier,
}: {
  mode: PerfMode;
  onMode: (m: PerfMode) => void;
  tier: Tier;
}) {
  return (
    <div className="flex items-center gap-1.5 pointer-events-auto">
      <div className="inline-flex rounded-sm border border-scope-line overflow-hidden bg-scope-bg/70 backdrop-blur-sm">
        {MODES.map((m) => (
          <button
            key={m.key}
            onClick={() => onMode(m.key)}
            aria-pressed={mode === m.key}
            className={cn(
              "font-mono text-[0.6rem] tracking-wider px-2 py-0.5 transition-colors",
              mode === m.key
                ? "text-scope-bg bg-phosphor"
                : "text-ink-mute hover:text-ink",
            )}
          >
            {m.label}
          </button>
        ))}
      </div>
      <span
        className="inline-flex items-center gap-1 font-mono text-[0.58rem] tracking-wider px-1.5 py-0.5 rounded-sm border tabular-nums"
        style={{
          color: TIER_COLOR[tier],
          borderColor: `color-mix(in oklab, ${TIER_COLOR[tier]} 45%, transparent)`,
        }}
        title="Live render quality tier (auto in BAL mode)"
      >
        ◉ {tier.toUpperCase()}
      </span>
    </div>
  );
}
