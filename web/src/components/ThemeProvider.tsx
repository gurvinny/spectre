/**
 * Runtime theme switching. The initial skin is applied before hydration by a tiny
 * bootstrap script in the root layout (no flash); this provider syncs React state
 * with that attribute and persists changes. Switching sets html[data-theme] — the
 * CSS recolors the whole app — and fires a window event so canvas/ECharts visuals
 * that read CSS vars can re-tint themselves.
 * Author: gurvinny
 */
"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useState,
} from "react";
import {
  DEFAULT_THEME,
  THEME_EVENT,
  THEME_KEY,
  isThemeId,
  type ThemeId,
} from "@/lib/theme";

interface ThemeCtx {
  theme: ThemeId;
  setTheme: (t: ThemeId) => void;
}

const Ctx = createContext<ThemeCtx>({
  theme: DEFAULT_THEME,
  setTheme: () => {},
});

/** Inline bootstrap — runs before first paint to avoid an unstyled flash. */
export const themeBootstrap = `(function(){try{var t=localStorage.getItem('${THEME_KEY}');var ok=['phosphor','amber','ice','nightvision'];document.documentElement.setAttribute('data-theme',ok.indexOf(t)>=0?t:'${DEFAULT_THEME}');}catch(e){document.documentElement.setAttribute('data-theme','${DEFAULT_THEME}');}})();`;

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [theme, setThemeState] = useState<ThemeId>(DEFAULT_THEME);

  // Adopt whatever the bootstrap script already applied.
  useEffect(() => {
    const applied = document.documentElement.getAttribute("data-theme");
    if (isThemeId(applied)) setThemeState(applied);
  }, []);

  const setTheme = useCallback((t: ThemeId) => {
    document.documentElement.setAttribute("data-theme", t);
    try {
      localStorage.setItem(THEME_KEY, t);
    } catch {
      /* private mode — theme just won't persist */
    }
    setThemeState(t);
    window.dispatchEvent(new CustomEvent(THEME_EVENT, { detail: t }));
  }, []);

  return <Ctx.Provider value={{ theme, setTheme }}>{children}</Ctx.Provider>;
}

export const useTheme = () => useContext(Ctx);
