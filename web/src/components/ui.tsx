/**
 * Small shared UI primitives for the console (panels, stat tiles, pills, section
 * headers). Stat tiles tween their value and flash on change so the console reads
 * as live. Author: gurvinny
 */
"use client";

import { cn } from "@/lib/utils";
import { useCountUp, useFlashOnChange } from "@/hooks/useReactive";

export function Panel({
  title,
  right,
  className,
  bodyClassName,
  accent = false,
  children,
}: {
  title?: string;
  right?: React.ReactNode;
  className?: string;
  bodyClassName?: string;
  accent?: boolean;
  children: React.ReactNode;
}) {
  return (
    <section className={cn("panel flex flex-col", accent && "panel-accent", className)}>
      {title && (
        <header className="flex items-center justify-between px-4 h-9 border-b border-scope-line">
          <span className="panel-head">{title}</span>
          {right}
        </header>
      )}
      <div className={cn("p-4 flex-1 min-h-0", bodyClassName)}>{children}</div>
    </section>
  );
}

/** A run-in section heading with an eyebrow index and a hairline rule. */
export function SectionHeader({
  index,
  title,
  sub,
  right,
}: {
  index?: string;
  title: string;
  sub?: string;
  right?: React.ReactNode;
}) {
  return (
    <div className="flex items-end gap-3 mb-1">
      {index && <span className="eyebrow text-phosphor-dim leading-none pb-1">{index}</span>}
      <h1 className="font-display text-lg tracking-wide text-ink leading-none">{title}</h1>
      {sub && <span className="font-mono text-[0.66rem] text-ink-mute pb-0.5">{sub}</span>}
      {right && <div className="ml-auto">{right}</div>}
    </div>
  );
}

/**
 * Live KPI tile. Numeric values tween via count-up and the tile flashes when the
 * value changes; pass a preformatted string for non-numeric values.
 */
export function StatTile({
  label,
  value,
  sub,
  accent = "var(--color-ink)",
}: {
  label: string;
  value: number | string;
  sub?: React.ReactNode;
  accent?: string;
}) {
  const numeric = typeof value === "number";
  const tween = useCountUp(numeric ? value : 0);
  const flash = useFlashOnChange(value);
  const shown = numeric ? Math.round(tween).toLocaleString() : value;

  return (
    <div className={cn("panel px-4 py-3 flex flex-col gap-1 relative overflow-hidden", flash && "flash-accent")}>
      <span
        className="absolute left-0 top-0 h-full w-[2px]"
        style={{ background: accent, opacity: 0.5 }}
      />
      <span className="eyebrow">{label}</span>
      <span
        className="font-display text-2xl font-600 tabular-nums leading-none"
        style={{ color: accent }}
      >
        {shown}
      </span>
      {sub && <span className="font-mono text-[0.66rem] text-ink-mute">{sub}</span>}
    </div>
  );
}

export function Pill({
  children,
  color = "var(--color-ink-dim)",
  filled,
}: {
  children: React.ReactNode;
  color?: string;
  filled?: boolean;
}) {
  return (
    <span
      className="inline-flex items-center gap-1 font-mono text-[0.62rem] tracking-wider px-1.5 py-0.5 rounded-sm border"
      style={{
        color,
        borderColor: `color-mix(in oklab, ${color} 45%, transparent)`,
        background: filled ? `color-mix(in oklab, ${color} 14%, transparent)` : "transparent",
      }}
    >
      {children}
    </span>
  );
}

export function Empty({ children }: { children: React.ReactNode }) {
  return (
    <div className="h-full min-h-32 grid place-items-center text-center">
      <p className="font-mono text-xs text-ink-mute max-w-xs leading-relaxed">
        {children}
      </p>
    </div>
  );
}
