/**
 * Global search — a ⌘K / Ctrl-K command palette that queries the server-side
 * full-text index (/api/search) across devices, APs, threats and known networks,
 * including archived history. Selecting a result jumps to the right page with the
 * ref pre-filled. Fully keyboard-driven. Author: gurvinny
 */
"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { useRouter } from "next/navigation";
import { Search, Cpu, Wifi, ShieldAlert, ShieldCheck, CornerDownLeft } from "lucide-react";
import { api } from "@/lib/api";
import { useDebounce } from "@/hooks/useDebounce";
import type { SearchResult } from "@/lib/types";

export const OPEN_SEARCH_EVENT = "spectre-search-open";

const KIND = {
  device: { icon: Cpu, color: "var(--color-phosphor)", tag: "DEV" },
  ap: { icon: Wifi, color: "var(--color-violet)", tag: "AP" },
  threat: { icon: ShieldAlert, color: "var(--color-alert)", tag: "THREAT" },
  known: { icon: ShieldCheck, color: "var(--color-phosphor)", tag: "KNOWN" },
} as const;

function targetFor(r: SearchResult): string {
  switch (r.kind) {
    case "device":
      return `/inventory?tab=devices&scope=all&q=${encodeURIComponent(r.ref)}`;
    case "ap":
      return `/inventory?tab=aps&scope=all&q=${encodeURIComponent(r.ref)}`;
    case "threat":
      return `/threats`;
    case "known":
      return `/settings`;
  }
}

export function CommandPalette() {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [active, setActive] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const debounced = useDebounce(q, 160);

  const close = useCallback(() => {
    setOpen(false);
    setQ("");
    setResults([]);
    setActive(0);
  }, []);

  // Global open shortcut + programmatic open event (from the status-rail button).
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((o) => !o);
      }
    };
    const onOpen = () => setOpen(true);
    window.addEventListener("keydown", onKey);
    window.addEventListener(OPEN_SEARCH_EVENT, onOpen);
    return () => {
      window.removeEventListener("keydown", onKey);
      window.removeEventListener(OPEN_SEARCH_EVENT, onOpen);
    };
  }, []);

  useEffect(() => {
    if (open) setTimeout(() => inputRef.current?.focus(), 0);
  }, [open]);

  // Fetch results for the debounced query.
  useEffect(() => {
    let alive = true;
    if (!debounced.trim()) {
      setResults([]);
      return;
    }
    api
      .get<{ results: SearchResult[] }>(`/api/search?q=${encodeURIComponent(debounced)}`)
      .then((r) => {
        if (alive) {
          setResults(r.results);
          setActive(0);
        }
      })
      .catch(() => alive && setResults([]));
    return () => {
      alive = false;
    };
  }, [debounced]);

  const choose = useCallback(
    (r: SearchResult | undefined) => {
      if (!r) return;
      close();
      router.push(targetFor(r));
    },
    [close, router],
  );

  function onKeyDown(e: React.KeyboardEvent) {
    if (e.key === "Escape") close();
    else if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((a) => Math.min(a + 1, results.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((a) => Math.max(a - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      choose(results[active]);
    }
  }

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center pt-[12vh] px-4"
      role="dialog"
      aria-modal="true"
      aria-label="Search"
      onMouseDown={close}
    >
      <div className="absolute inset-0 bg-scope-bg/70 backdrop-blur-sm" />
      <div
        className="panel relative w-full max-w-xl overflow-hidden"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-2.5 px-4 h-12 border-b border-scope-line">
          <Search size={15} className="text-phosphor" />
          <input
            ref={inputRef}
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={onKeyDown}
            placeholder="Search devices, APs, SSIDs, threats…"
            className="flex-1 bg-transparent font-mono text-sm text-ink placeholder:text-ink-mute focus:outline-none"
          />
          <kbd className="font-mono text-[0.6rem] text-ink-mute border border-scope-line rounded px-1.5 py-0.5">
            ESC
          </kbd>
        </div>

        <div className="max-h-[52vh] overflow-y-auto py-1">
          {debounced.trim() && results.length === 0 && (
            <p className="px-4 py-6 text-center font-mono text-xs text-ink-mute">
              no matches for “{debounced}”
            </p>
          )}
          {!debounced.trim() && (
            <p className="px-4 py-6 text-center font-mono text-xs text-ink-mute">
              type to search active + archived airspace
            </p>
          )}
          {results.map((r, i) => {
            const meta = KIND[r.kind];
            const Icon = meta.icon;
            const on = i === active;
            return (
              <button
                key={`${r.kind}-${r.ref}-${i}`}
                onMouseEnter={() => setActive(i)}
                onClick={() => choose(r)}
                className={`w-full flex items-center gap-3 px-4 py-2 text-left ${
                  on ? "bg-phosphor/10" : ""
                }`}
              >
                <Icon size={15} style={{ color: meta.color }} className="shrink-0" />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm text-ink">{r.label}</span>
                  <span className="block truncate font-mono text-[0.66rem] text-ink-mute">
                    {r.sub}
                    {r.band ? ` · ${r.band}` : ""}
                  </span>
                </span>
                <span
                  className="font-mono text-[0.55rem] tracking-wider shrink-0"
                  style={{ color: meta.color }}
                >
                  {meta.tag}
                </span>
                {on && <CornerDownLeft size={13} className="text-ink-mute shrink-0" />}
              </button>
            );
          })}
        </div>
      </div>
    </div>
  );
}
