/**
 * Command Center — the SPECTRE at-a-glance console: live KPIs, spectrum analyzer,
 * threat radar, active detections and the raw feed. Author: gurvinny
 */
"use client";

import { useMemo } from "react";
import { useLive } from "@/components/LiveProvider";
import { usePoll } from "@/hooks/usePoll";
import { ConsoleBanner } from "@/components/ConsoleBanner";
import { SpectrumAnalyzer } from "@/components/viz/SpectrumAnalyzer";
import { RadarPPI } from "@/components/viz/RadarPPI";
import { ThreatList } from "@/components/ThreatList";
import { FrameFeed } from "@/components/FrameFeed";
import { Panel, StatTile, Pill } from "@/components/ui";
import { channelsFromFrames } from "@/lib/format";
import type { AccessPoint, Device } from "@/lib/types";

export default function CommandCenterPage() {
  const { overview, threats, frames } = useLive();
  const liveChannels = useMemo(() => channelsFromFrames(frames), [frames]);

  // Radar needs the current inventory; poll lightly.
  const { data: apData } = usePoll<{ access_points: AccessPoint[] }>("/api/access-points", 6000);
  const { data: devData } = usePoll<{ devices: Device[] }>("/api/devices", 8000);

  // MACs/BSSIDs tied to recent threats light up red on the radar.
  const threatIds = useMemo(() => {
    const s = new Set<string>();
    for (const t of threats.slice(0, 60)) {
      if (t.bssid) s.add(t.bssid.toUpperCase());
      if (t.src) s.add(t.src.toUpperCase());
    }
    return s;
  }, [threats]);

  return (
    <div className="flex flex-col gap-3 max-w-[1600px] w-full mx-auto lg:h-full lg:min-h-0">
      <ConsoleBanner overview={overview} />

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <StatTile
          label="Frames captured"
          value={overview?.total_frames ?? 0}
          sub={`${overview?.fps.toFixed(0) ?? 0} frames/sec`}
          accent="var(--color-phosphor)"
        />
        <StatTile
          label="Devices seen"
          value={overview?.devices ?? 0}
          sub={`${overview?.top_talkers.length ?? 0} active talkers`}
        />
        <StatTile
          label="Access points"
          value={overview?.access_points ?? 0}
          sub={`${overview?.known_aps ?? 0} known / trusted`}
          accent="var(--color-violet)"
        />
        <StatTile
          label="Threats / hour"
          value={overview?.threats_last_hour ?? 0}
          sub="rolling 60 min"
          accent={(overview?.threats_last_hour ?? 0) > 0 ? "var(--color-alert)" : "var(--color-ink)"}
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-3">
        <Panel
          title="Channel spectrum"
          accent
          className="lg:col-span-2"
          right={<span className="font-mono text-[0.62rem] text-ink-mute">live · peak-hold</span>}
        >
          <SpectrumAnalyzer
            channels={Object.keys(liveChannels).length ? liveChannels : overview?.channels ?? {}}
            height={150}
          />
        </Panel>

        <Panel
          title="Threat radar"
          right={<Pill color="var(--color-alert)">{threatIds.size} flagged</Pill>}
        >
          <RadarPPI
            aps={apData?.access_points ?? []}
            devices={devData?.devices ?? []}
            threatIds={threatIds}
            height={196}
          />
        </Panel>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-3 lg:flex-1 lg:min-h-0">
        <Panel
          title="Active threats"
          className="lg:min-h-0"
          bodyClassName="p-0 overflow-y-auto max-h-80 lg:max-h-none"
          right={<Pill color="var(--color-alert)">{threats.length} recent</Pill>}
        >
          <ThreatList threats={threats.slice(0, 40)} />
        </Panel>

        <Panel
          title="Live feed"
          className="lg:col-span-2 lg:min-h-0"
          bodyClassName="p-2 overflow-y-auto max-h-80 lg:max-h-none"
          right={<span className="font-mono text-[0.62rem] text-phosphor-dim">▚ streaming</span>}
        >
          <FrameFeed frames={frames.slice(0, 80)} />
        </Panel>
      </div>
    </div>
  );
}
