/**
 * Bridges the CSS-variable design tokens into ECharts. Canvas can't resolve
 * `var(--…)`, so we read the *computed* hex values off the document root at render
 * time — which means charts pick up the active theme skin automatically. Also
 * provides the shared axis/grid/tooltip styling every SPECTRE chart reuses.
 * Author: gurvinny
 */
import type { EChartsCoreOption } from "echarts";

export interface Palette {
  phosphor: string;
  phosphorDim: string;
  violet: string;
  amber: string;
  alert: string;
  ink: string;
  inkDim: string;
  inkMute: string;
  grid: string;
  line: string;
  panel: string;
  bg: string;
  mono: string;
  sev: { critical: string; high: string; medium: string; low: string; info: string };
}

function v(name: string, fallback: string): string {
  if (typeof window === "undefined") return fallback;
  const raw = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return raw || fallback;
}

/** Snapshot the active theme's resolved colors for a chart render. */
export function readPalette(): Palette {
  return {
    phosphor: v("--color-phosphor", "#35e0c4"),
    phosphorDim: v("--color-phosphor-dim", "#1c8a79"),
    violet: v("--color-violet", "#9b8cff"),
    amber: v("--color-rf-amber", "#f5a623"),
    alert: v("--color-alert", "#ff4d5e"),
    ink: v("--color-ink", "#c9d6df"),
    inkDim: v("--color-ink-dim", "#8598a6"),
    inkMute: v("--color-ink-mute", "#5b6b78"),
    grid: v("--color-scope-grid", "#1e2a35"),
    line: v("--color-scope-line", "#263542"),
    panel: v("--color-scope-panel", "#0f1620"),
    bg: v("--color-scope-bg", "#0a0e12"),
    mono: v("--font-plex-mono", "ui-monospace, monospace"),
    sev: {
      critical: v("--color-sev-critical", "#ff4d5e"),
      high: v("--color-sev-high", "#ff8a3d"),
      medium: v("--color-sev-medium", "#f5c542"),
      low: v("--color-sev-low", "#35e0c4"),
      info: v("--color-sev-info", "#6b8fb0"),
    },
  };
}

/** Common option fragment: recessive grid/axes, monospace ink, dark tooltip. */
export function chartBase(p: Palette): EChartsCoreOption {
  return {
    textStyle: { fontFamily: p.mono, color: p.inkDim },
    grid: { top: 16, right: 16, bottom: 26, left: 40, containLabel: true },
    tooltip: {
      backgroundColor: p.panel,
      borderColor: p.line,
      borderWidth: 1,
      padding: [6, 10],
      textStyle: { color: p.ink, fontFamily: p.mono, fontSize: 11 },
      extraCssText: "border-radius:4px;box-shadow:0 8px 24px -14px #000;",
    },
  };
}

/** Axis styling shared by cartesian charts. */
export function axisStyle(p: Palette) {
  return {
    axisLine: { lineStyle: { color: p.line } },
    axisTick: { show: false },
    axisLabel: { color: p.inkMute, fontFamily: p.mono, fontSize: 10 },
    splitLine: { lineStyle: { color: p.grid, type: "dashed" as const } },
  };
}
