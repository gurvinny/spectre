/**
 * Theme registry for the console skins. The applied colors live in globals.css
 * (html[data-theme=…]); the `accent` here is only for the switcher swatches and
 * must stay in sync with the CSS. Author: gurvinny
 */
export type ThemeId = "phosphor" | "amber" | "ice" | "nightvision";

export interface ThemeMeta {
  id: ThemeId;
  label: string;
  accent: string; // preview swatch — mirrors --color-phosphor for this skin
}

export const THEMES: ThemeMeta[] = [
  { id: "phosphor", label: "Phosphor", accent: "#35e0c4" },
  { id: "amber", label: "Amber", accent: "#f5b53d" },
  { id: "ice", label: "Ice", accent: "#48b4ff" },
  { id: "nightvision", label: "Nightvision", accent: "#48f09a" },
];

export const DEFAULT_THEME: ThemeId = "phosphor";
export const THEME_KEY = "spectre-theme";
export const THEME_EVENT = "spectre-theme";

export function isThemeId(v: string | null): v is ThemeId {
  return !!v && THEMES.some((t) => t.id === v);
}
