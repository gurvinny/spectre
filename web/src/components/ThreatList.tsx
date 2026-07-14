/**
 * Threat list with a severity spine, expandable detail, and Wazuh-uplink state.
 * Author: gurvinny
 */
"use client";

import { useState } from "react";
import { CheckCircle2, CircleSlash } from "lucide-react";
import type { Threat } from "@/lib/types";
import { severityColor, fmtClock, timeAgo } from "@/lib/format";

function ThreatRow({ t, expandable }: { t: Threat; expandable: boolean }) {
  const [open, setOpen] = useState(false);
  const color = severityColor(t.severity);
  return (
    <div
      className="border-b border-scope-line/60 last:border-0"
      style={{ borderLeft: `2px solid ${color}` }}
    >
      <button
        onClick={() => expandable && setOpen((o) => !o)}
        className="w-full text-left flex items-start gap-3 px-3 py-2 hover:bg-scope-panel2/60"
      >
        <span
          className="font-mono text-[0.58rem] tracking-wider mt-0.5 px-1.5 py-0.5 rounded-sm shrink-0"
          style={{ color, background: `color-mix(in oklab, ${color} 14%, transparent)` }}
        >
          {t.severity.toUpperCase()}
        </span>
        <div className="min-w-0 flex-1">
          <div className="text-sm text-ink truncate">{t.title}</div>
          <div className="font-mono text-[0.66rem] text-ink-mute flex items-center gap-2 flex-wrap">
            <span className="text-ink-dim">{t.rule}</span>
            {t.band && t.band !== "unknown" && <span>· {t.band}</span>}
            {t.bssid && <span>· {t.bssid}</span>}
            <span>· {fmtClock(t.ts)}</span>
          </div>
        </div>
        <div className="flex items-center gap-2 shrink-0">
          {t.wazuh_sent !== undefined &&
            (t.wazuh_sent ? (
              <CheckCircle2 size={13} className="text-phosphor-dim" aria-label="forwarded to Wazuh" />
            ) : (
              <CircleSlash size={13} className="text-ink-mute" aria-label="not forwarded" />
            ))}
          <span className="font-mono text-[0.66rem] text-ink-mute w-8 text-right">
            {timeAgo(t.ts)}
          </span>
        </div>
      </button>
      {open && (
        <pre className="mx-3 mb-2 p-3 bg-scope-bg border border-scope-line rounded-sm font-mono text-[0.66rem] text-ink-dim overflow-x-auto">
          {JSON.stringify(t.detail, null, 2)}
        </pre>
      )}
    </div>
  );
}

export function ThreatList({
  threats,
  expandable = true,
  empty = "No threats detected. Airspace nominal.",
}: {
  threats: Threat[];
  expandable?: boolean;
  empty?: string;
}) {
  if (!threats.length) {
    return (
      <div className="h-full min-h-24 grid place-items-center">
        <p className="font-mono text-xs text-phosphor-dim">✓ {empty}</p>
      </div>
    );
  }
  return (
    <div className="flex flex-col">
      {threats.map((t, i) => (
        <ThreatRow key={`${t.ts}-${t.rule}-${i}`} t={t} expandable={expandable} />
      ))}
    </div>
  );
}
