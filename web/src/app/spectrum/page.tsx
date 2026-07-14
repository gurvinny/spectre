/**
 * Spectrum — the immersive signal-processing view: analyzer, spectrogram waterfall,
 * PPI radar, throughput scope and frame-type mix. Author: gurvinny
 */
"use client";

import { useMemo } from "react";
import type { EChartsCoreOption } from "echarts";
import { useLive } from "@/components/LiveProvider";
import { usePoll } from "@/hooks/usePoll";
import { SpectrumAnalyzer } from "@/components/viz/SpectrumAnalyzer";
import { Waterfall } from "@/components/viz/Waterfall";
import { RadarPPI } from "@/components/viz/RadarPPI";
import { ThroughputScope } from "@/components/viz/ThroughputScope";
import { Chart } from "@/components/viz/Chart";
import { axisStyle, chartBase } from "@/lib/echartsTheme";
import { Panel, SectionHeader, Pill } from "@/components/ui";
import { channelsFromFrames } from "@/lib/format";
import type { AccessPoint, Device } from "@/lib/types";

interface Summary {
  ts: number;
  fps: number;
}

export default function SpectrumPage() {
  const { overview, frames, threats } = useLive();
  const liveChannels = useMemo(() => channelsFromFrames(frames), [frames]);
  const { data: sum } = usePoll<{ summaries: Summary[] }>("/api/summaries?limit=120", 15000);
  const { data: apData } = usePoll<{ access_points: AccessPoint[] }>("/api/access-points", 6000);
  const { data: devData } = usePoll<{ devices: Device[] }>("/api/devices", 8000);

  const threatIds = useMemo(() => {
    const s = new Set<string>();
    for (const t of threats.slice(0, 60)) {
      if (t.bssid) s.add(t.bssid.toUpperCase());
      if (t.src) s.add(t.src.toUpperCase());
    }
    return s;
  }, [threats]);

  const frameTypes = useMemo(
    () =>
      Object.entries(overview?.frame_types ?? {})
        .sort((a, b) => b[1] - a[1])
        .slice(0, 9),
    [overview],
  );

  const typeBar = (p: Parameters<typeof chartBase>[0]): EChartsCoreOption => ({
    ...chartBase(p),
    grid: { top: 8, right: 16, bottom: 8, left: 8, containLabel: true },
    xAxis: { type: "value", ...axisStyle(p), splitLine: { lineStyle: { color: p.grid } } },
    yAxis: {
      type: "category",
      inverse: true,
      data: frameTypes.map(([t]) => t),
      ...axisStyle(p),
      splitLine: { show: false },
    },
    series: [
      {
        type: "bar",
        data: frameTypes.map(([, n]) => n),
        barWidth: "58%",
        itemStyle: { color: p.phosphor, borderRadius: [0, 3, 3, 0] },
      },
    ],
  });

  return (
    <div className="flex flex-col gap-4 max-w-[1600px] mx-auto">
      <SectionHeader
        index="◈ SIG"
        title="Spectrum"
        sub="live signal processing"
        right={<Pill color="var(--color-phosphor)">{overview?.fps.toFixed(0) ?? 0} fps</Pill>}
      />

      <Panel title="Spectrum analyzer — utilization & peak-hold" accent>
        <SpectrumAnalyzer
          channels={Object.keys(liveChannels).length ? liveChannels : overview?.channels ?? {}}
          height={210}
        />
      </Panel>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <Panel
          title="Spectrogram waterfall"
          className="lg:col-span-2"
          right={<span className="font-mono text-[0.62rem] text-ink-mute">time ↓ · channel →</span>}
        >
          <Waterfall frames={frames} height={360} />
        </Panel>

        <Panel
          title="Threat radar (PPI)"
          right={<Pill color="var(--color-alert)">{threatIds.size} flagged</Pill>}
        >
          <RadarPPI
            aps={apData?.access_points ?? []}
            devices={devData?.devices ?? []}
            threatIds={threatIds}
            height={360}
          />
        </Panel>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <Panel title="Throughput — frames/sec">
          <ThroughputScope
            data={(sum?.summaries ?? []).map((s) => ({ ts: s.ts, fps: s.fps }))}
            height={220}
          />
        </Panel>
        <Panel title="Frame-type distribution">
          {frameTypes.length ? (
            <Chart build={typeBar} deps={[frameTypes]} style={{ height: 220 }} />
          ) : (
            <div className="h-[220px] grid place-items-center font-mono text-xs text-ink-mute">
              awaiting frames…
            </div>
          )}
        </Panel>
      </div>
    </div>
  );
}
