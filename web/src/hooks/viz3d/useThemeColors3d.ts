/**
 * Reads the active console skin's accent colors off the document root as
 * THREE.Color instances for use in the 3D scene, mirroring the getComputedStyle
 * pattern in RadarPPI/echartsTheme. Re-reads on the app's theme-switch event so
 * the battlespace retints instantly alongside the rest of the console — the
 * scene reacts to the same CSS-variable swap, not a React prop.
 * Author: gurvinny
 */
"use client";

import { useEffect, useState } from "react";
import { Color } from "three";
import { THEME_EVENT } from "@/lib/theme";

const VARS = {
  phosphor: "--color-phosphor",
  phosphorDim: "--color-phosphor-dim",
  violet: "--color-violet",
  alert: "--color-alert",
  amber: "--color-rf-amber",
  bg: "--color-scope-bg",
  grid: "--color-scope-grid",
  line: "--color-scope-line",
  inkMute: "--color-ink-mute",
} as const;

export type ThemeColors3d = Record<keyof typeof VARS, Color>;

function readColors(): ThemeColors3d {
  const cs = getComputedStyle(document.documentElement);
  const out = {} as ThemeColors3d;
  for (const key of Object.keys(VARS) as (keyof typeof VARS)[]) {
    const v = cs.getPropertyValue(VARS[key]).trim();
    out[key] = new Color(v || "#888888");
  }
  return out;
}

export function useThemeColors3d(): ThemeColors3d {
  // The whole 3D subtree is dynamically imported with ssr:false, so `document`
  // is always available on first render here.
  const [colors, setColors] = useState<ThemeColors3d>(() => readColors());

  useEffect(() => {
    setColors(readColors());
    const onTheme = () => setColors(readColors());
    window.addEventListener(THEME_EVENT, onTheme);
    return () => window.removeEventListener(THEME_EVENT, onTheme);
  }, []);

  return colors;
}

/** Pick the band accent (2.4 GHz phosphor / 5 GHz violet) for a node. */
export function bandColor3d(colors: ThemeColors3d, band: string): Color {
  return band.startsWith("5") ? colors.violet : colors.phosphor;
}
