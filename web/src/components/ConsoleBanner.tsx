/**
 * The SPECTRE console banner — the page's signature element. A live readout in
 * the firmware's own monospace idiom: block-character band meters, channel-hop
 * range, armed state, and the Wazuh uplink. Author: gurvinny
 */
"use client";

import type { Overview } from "@/lib/types";
import { bandColor } from "@/lib/format";
import { fmtUptime } from "@/lib/format";

const CELLS = 14;

function meter(ratio: number): string {
  const filled = Math.max(0, Math.min(CELLS, Math.round(ratio * CELLS)));
  return "▓".repeat(filled) + "░".repeat(CELLS - filled);
}

function BandRow({
  band,
  count,
  max,
  hop,
  online,
  fps,
}: {
  band: string;
  count: number;
  max: number;
  hop: string;
  online: boolean;
  fps: number;
}) {
  const color = bandColor(band);
  return (
    <div className="flex items-center gap-3 whitespace-nowrap">
      <span className="text-ink-mute w-14">band</span>
      <span style={{ color }} className="w-12 font-600">
        {band.replace("GHz", "G")}
      </span>
      <span style={{ color }} className="phosphor-glow tracking-tight">
        {meter(max ? count / max : 0)}
      </span>
      <span className="text-ink-mute">ch-hop {hop}</span>
      <span className="text-ink-mute">
        {online ? (
          <span style={{ color }}>{fps.toFixed(0)} fps</span>
        ) : (
          <span className="text-alert">offline</span>
        )}
      </span>
    </div>
  );
}

export function ConsoleBanner({ overview }: { overview: Overview | null }) {
  const bands = overview?.band_breakdown ?? {};
  const max = Math.max(1, ...Object.values(bands));
  const sensor = (b: string) =>
    overview?.sensors.find((s) => s.band.startsWith(b));
  const w = overview?.wazuh;

  return (
    <div className="panel scanlines overflow-hidden">
      {/* top bracket row */}
      <div className="flex items-center gap-3 px-4 pt-3 font-mono text-xs text-ink-mute">
        <span className="text-phosphor phosphor-glow font-600 tracking-[0.25em]">
          ╔═[ SPECTRE ]
        </span>
        <span className="hidden sm:inline">
          Signal Processing · EM Threat Reconnaissance Engine
        </span>
        <span className="ml-auto flex items-center gap-3">
          <span className="text-phosphor armed-dot">● {overview?.armed ? "ARMED" : "IDLE"}</span>
          <span>up {overview ? fmtUptime(overview.uptime_seconds) : "—"}</span>
        </span>
      </div>

      <div className="px-4 py-3 font-mono text-xs flex flex-col gap-1.5 overflow-x-auto">
        <BandRow
          band="2.4GHz"
          count={bands["2.4GHz"] ?? 0}
          max={max}
          hop="1→13"
          online={!!sensor("2.4")?.online}
          fps={sensor("2.4")?.fps ?? 0}
        />
        <BandRow
          band="5GHz"
          count={bands["5GHz"] ?? 0}
          max={max}
          hop="36→165"
          online={!!sensor("5")?.online}
          fps={sensor("5")?.fps ?? 0}
        />
      </div>

      {/* bottom uplink row */}
      <div className="flex items-center gap-2 px-4 pb-3 font-mono text-[0.7rem] text-ink-mute whitespace-nowrap overflow-x-auto">
        <span className="text-phosphor">╚═</span>
        {w?.enabled ? (
          <>
            streaming to wazuh{" "}
            <span className="text-ink-dim">
              {w.host}:{w.port}/{w.proto}
            </span>
            <span className="text-phosphor-dim">· {w.sent} sent</span>
            {w.failures > 0 && <span className="text-alert">· {w.failures} failed</span>}
          </>
        ) : (
          <span>wazuh forwarding disabled</span>
        )}
        <span className="text-scope-line">
          {"═".repeat(24)}
        </span>
      </div>
    </div>
  );
}
