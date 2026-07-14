/**
 * Compact accent-swatch control for the status rail. Keyboard-accessible; the
 * active skin gets a phosphor ring. Author: gurvinny
 */
"use client";

import { useTheme } from "@/components/ThemeProvider";
import { THEMES } from "@/lib/theme";

export function ThemeSwitcher() {
  const { theme, setTheme } = useTheme();
  return (
    <div
      role="group"
      aria-label="Console theme"
      className="flex items-center gap-1.5 rounded-sm border border-scope-line bg-scope-bg/60 px-1.5 py-1"
    >
      {THEMES.map((t) => {
        const active = t.id === theme;
        return (
          <button
            key={t.id}
            type="button"
            onClick={() => setTheme(t.id)}
            title={t.label}
            aria-label={`${t.label} theme`}
            aria-pressed={active}
            className="relative grid place-items-center w-4 h-4 rounded-full transition-transform hover:scale-110"
          >
            <span
              className="w-2.5 h-2.5 rounded-full"
              style={{
                background: t.accent,
                boxShadow: active ? `0 0 8px ${t.accent}` : "none",
              }}
            />
            {active && (
              <span
                className="absolute inset-0 rounded-full border"
                style={{ borderColor: t.accent }}
              />
            )}
          </button>
        );
      })}
    </div>
  );
}
