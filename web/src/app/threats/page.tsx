/**
 * Threats — full detection log with severity filter. Author: gurvinny
 */
"use client";

import { useMemo, useState } from "react";
import { usePoll } from "@/hooks/usePoll";
import { Panel, Pill, SectionHeader } from "@/components/ui";
import { ThreatList } from "@/components/ThreatList";
import { ThreatTimeline } from "@/components/viz/ThreatTimeline";
import { SEVERITY_ORDER, severityColor } from "@/lib/format";
import type { Threat } from "@/lib/types";
import { cn } from "@/lib/utils";

export default function ThreatsPage() {
  const { data } = usePoll<{ threats: Threat[] }>("/api/threats?limit=300", 4000);
  const [sev, setSev] = useState<string>("ALL");

  const rows = useMemo(() => {
    const list = data?.threats ?? [];
    return sev === "ALL" ? list : list.filter((t) => t.severity === sev);
  }, [data, sev]);

  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    (data?.threats ?? []).forEach((t) => (c[t.severity] = (c[t.severity] ?? 0) + 1));
    return c;
  }, [data]);

  return (
    <div className="flex flex-col gap-3 max-w-[1200px] mx-auto">
      <SectionHeader
        index="⚠ SEC"
        title="Threats"
        sub="detection log"
        right={<Pill>{data?.threats.length ?? 0} logged</Pill>}
      />

      <Panel title="Detection timeline">
        <ThreatTimeline threats={data?.threats ?? []} height={190} />
      </Panel>

      <div className="flex items-center gap-1.5 flex-wrap">
        <Chip label="ALL" active={sev === "ALL"} onClick={() => setSev("ALL")} />
        {SEVERITY_ORDER.map((s) => (
          <Chip
            key={s}
            label={`${s} ${counts[s] ?? 0}`}
            color={severityColor(s)}
            active={sev === s}
            onClick={() => setSev(s)}
          />
        ))}
      </div>

      <Panel bodyClassName="p-0 max-h-[calc(100vh-24rem)] overflow-y-auto">
        <ThreatList threats={rows} empty="No threats in the log." />
      </Panel>
    </div>
  );
}

function Chip({
  label,
  color = "var(--color-ink-dim)",
  active,
  onClick,
}: {
  label: string;
  color?: string;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className={cn(
        "font-mono text-[0.62rem] uppercase tracking-wider px-2 py-1 rounded-sm border",
      )}
      style={{
        color: active ? color : "var(--color-ink-mute)",
        borderColor: active ? `color-mix(in oklab, ${color} 50%, transparent)` : "var(--color-scope-line)",
        background: active ? `color-mix(in oklab, ${color} 12%, transparent)` : "transparent",
      }}
    >
      {label}
    </button>
  );
}
