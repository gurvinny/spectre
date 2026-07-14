/**
 * Live frame feed — the raw packet stream in the firmware's monospace idiom.
 * Author: gurvinny
 */
"use client";

import type { Frame } from "@/lib/types";
import { frameColor, bandColor, rssiColor, fmtClock } from "@/lib/format";

export function FrameFeed({
  frames,
  dense = false,
}: {
  frames: Frame[];
  dense?: boolean;
}) {
  if (!frames.length) {
    return (
      <div className="h-full min-h-24 grid place-items-center">
        <p className="font-mono text-xs text-ink-mute armed-dot">
          awaiting frames…
        </p>
      </div>
    );
  }
  return (
    <div className="font-mono text-[0.72rem] leading-relaxed">
      {frames.map((f, i) => (
        <div
          key={`${f.ts}-${i}`}
          className="flex items-center gap-2 px-1 py-[1px] hover:bg-scope-panel2/50 whitespace-nowrap"
        >
          <span className="text-ink-mute shrink-0">{fmtClock(f.ts)}</span>
          {!dense && (
            <span style={{ color: bandColor(f.band) }} className="w-9 shrink-0">
              {f.band.replace("GHz", "G")}
            </span>
          )}
          <span className="text-ink-mute w-8 shrink-0">c{f.ch ?? "—"}</span>
          <span
            className="w-20 shrink-0 font-600"
            style={{ color: frameColor(f.type) }}
          >
            {f.type}
          </span>
          <span
            className="w-10 shrink-0 text-right"
            style={{ color: rssiColor(f.rssi) }}
          >
            {f.rssi ?? "—"}
          </span>
          <span className="text-ink-dim shrink-0">{f.src ?? "—"}</span>
          <span className="text-ink-mute shrink-0">▸</span>
          <span className="text-ink-mute shrink-0">{f.dst ?? "—"}</span>
          {f.ssid && <span className="text-phosphor-dim truncate">"{f.ssid}"</span>}
        </div>
      ))}
    </div>
  );
}
