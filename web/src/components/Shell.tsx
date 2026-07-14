/**
 * App shell: fixed sidebar navigation + top status rail, wrapping all authed
 * pages inside the shared live-feed provider.
 * Author: gurvinny
 */
"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  Radar, AudioLines, Orbit, Activity, Boxes, ShieldAlert, Settings2, LogOut, Search,
} from "lucide-react";
import { LiveProvider, useLive } from "@/components/LiveProvider";
import { SpectreMark } from "@/components/SpectreMark";
import { ThemeSwitcher } from "@/components/ThemeSwitcher";
import { CommandPalette, OPEN_SEARCH_EVENT } from "@/components/CommandPalette";
import { api } from "@/lib/api";
import { cn } from "@/lib/utils";

const NAV = [
  { href: "/", label: "Command Center", icon: Radar },
  { href: "/spectrum", label: "Spectrum", icon: AudioLines },
  { href: "/battlespace", label: "Battlespace", icon: Orbit },
  { href: "/live", label: "Live Feed", icon: Activity },
  { href: "/inventory", label: "Inventory", icon: Boxes },
  { href: "/threats", label: "Threats", icon: ShieldAlert },
  { href: "/settings", label: "Settings", icon: Settings2 },
];

function StatusRail() {
  const { conn, fps, threats, overview } = useLive();
  const activeThreats = threats.filter(
    (t) => Date.now() / 1000 - t.ts < 300,
  ).length;
  const dot =
    conn === "live"
      ? "var(--color-phosphor)"
      : conn === "connecting"
        ? "var(--color-rf-amber)"
        : "var(--color-alert)";
  return (
    <div className="h-11 border-b border-scope-line flex items-center gap-6 px-5 bg-scope-panel/60 backdrop-blur">
      <div className="flex items-center gap-2">
        <span
          className="w-2 h-2 rounded-full armed-dot"
          style={{ background: dot, boxShadow: `0 0 8px ${dot}` }}
        />
        <span className="font-mono text-[0.68rem] tracking-widest text-ink-dim">
          {conn === "live" ? "ARMED" : conn === "connecting" ? "LINKING" : "LINK DOWN"}
        </span>
      </div>
      <Metric label="FPS" value={fps.toFixed(0)} />
      <Metric label="DEVICES" value={overview?.devices ?? "—"} />
      <Metric label="APS" value={overview?.access_points ?? "—"} />
      <Metric
        label="THREATS/H"
        value={overview?.threats_last_hour ?? "—"}
        alert={(overview?.threats_last_hour ?? 0) > 0}
      />
      <div className="ml-auto flex items-center gap-3 font-mono text-[0.68rem] text-ink-mute">
        <button
          onClick={() => window.dispatchEvent(new Event(OPEN_SEARCH_EVENT))}
          className="flex items-center gap-2 px-2 py-1 rounded-sm border border-scope-line text-ink-mute hover:text-ink hover:border-ink-mute"
          title="Search (⌘K)"
        >
          <Search size={12} />
          <span className="hidden sm:inline">search</span>
          <kbd className="hidden sm:inline text-[0.58rem] text-ink-mute border border-scope-line rounded px-1">
            ⌘K
          </kbd>
        </button>
        <span
          className={cn(
            "px-2 py-0.5 rounded-sm border",
            activeThreats > 0
              ? "border-alert/50 text-alert"
              : "border-scope-line text-ink-mute",
          )}
        >
          {activeThreats} ACTIVE
        </span>
        <ThemeSwitcher />
      </div>
    </div>
  );
}

function Metric({
  label,
  value,
  alert,
}: {
  label: string;
  value: React.ReactNode;
  alert?: boolean;
}) {
  return (
    <div className="flex items-baseline gap-1.5">
      <span className="font-mono text-[0.6rem] tracking-widest text-ink-mute">
        {label}
      </span>
      <span
        className={cn(
          "font-mono text-sm tabular-nums",
          alert ? "text-alert" : "text-ink",
        )}
      >
        {value}
      </span>
    </div>
  );
}

function Sidebar() {
  const pathname = usePathname();
  async function logout() {
    await api.post("/api/logout");
    location.reload();
  }
  return (
    <aside className="w-56 shrink-0 border-r border-scope-line bg-scope-panel/50 flex flex-col">
      <div className="h-11 flex items-center px-5 border-b border-scope-line">
        <SpectreMark size="sm" subtitle={false} />
      </div>
      <nav className="flex-1 min-h-0 overflow-y-auto py-4 flex flex-col gap-0.5 px-3">
        {NAV.map(({ href, label, icon: Icon }) => {
          const active = pathname === href;
          return (
            <Link
              key={href}
              href={href}
              className={cn(
                "group flex items-center gap-3 px-3 py-2 rounded-sm font-mono text-[0.8rem] tracking-wide transition-colors",
                active
                  ? "bg-phosphor/10 text-phosphor"
                  : "text-ink-dim hover:text-ink hover:bg-scope-panel2",
              )}
            >
              <Icon
                size={15}
                className={active ? "text-phosphor" : "text-ink-mute group-hover:text-ink-dim"}
              />
              {label}
              {active && <span className="ml-auto text-phosphor">▸</span>}
            </Link>
          );
        })}
      </nav>
      <button
        onClick={logout}
        className="m-3 flex items-center gap-3 px-3 py-2 rounded-sm font-mono text-[0.8rem] text-ink-mute hover:text-alert hover:bg-scope-panel2"
      >
        <LogOut size={15} /> Lock console
      </button>
    </aside>
  );
}

export function Shell({ children }: { children: React.ReactNode }) {
  return (
    <LiveProvider>
      <div className="relative z-10 flex h-screen overflow-hidden">
        <Sidebar />
        <div className="flex-1 flex flex-col min-w-0 min-h-0">
          <StatusRail />
          <main className="flex-1 min-w-0 min-h-0 overflow-y-auto p-5">{children}</main>
        </div>
      </div>
      <CommandPalette />
    </LiveProvider>
  );
}
