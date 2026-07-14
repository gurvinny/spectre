/**
 * Threat timeline — a scatter of detections over time by severity. Severity is a
 * reserved status palette (never a series color); marker size encodes rank.
 * Author: gurvinny
 */
"use client";

import type { EChartsCoreOption } from "echarts";
import { Chart } from "./Chart";
import { axisStyle, chartBase } from "@/lib/echartsTheme";
import type { Threat } from "@/lib/types";

const LEVELS = ["critical", "high", "medium", "low", "info"] as const;

export function ThreatTimeline({
  threats,
  height = 200,
}: {
  threats: Threat[];
  height?: number;
}) {
  if (!threats.length) {
    return (
      <div
        className="grid place-items-center font-mono text-xs text-phosphor-dim"
        style={{ height }}
      >
        ✓ no threats in range — airspace nominal
      </div>
    );
  }

  const build = (p: Parameters<typeof chartBase>[0]): EChartsCoreOption => {
    const sevColor: Record<string, string> = {
      critical: p.sev.critical,
      high: p.sev.high,
      medium: p.sev.medium,
      low: p.sev.low,
      info: p.sev.info,
    };
    const present = LEVELS.filter((l) => threats.some((t) => t.severity === l));

    return {
      ...chartBase(p),
      grid: { top: 12, right: 16, bottom: 22, left: 70, containLabel: true },
      legend: {
        show: present.length > 1,
        top: 0,
        right: 0,
        itemWidth: 8,
        itemHeight: 8,
        textStyle: { color: p.inkMute, fontFamily: p.mono, fontSize: 9 },
        data: present.map((l) => l.toUpperCase()),
      },
      tooltip: {
        ...((chartBase(p) as { tooltip: object }).tooltip),
        formatter: (o: unknown) => {
          const d = (o as { data: { value: [number, number]; t: Threat } }).data;
          const t = d.t;
          return `<b>${t.title}</b><br/>${t.severity.toUpperCase()} · ${t.rule}<br/>${new Date(
            t.ts * 1000,
          ).toLocaleTimeString([], { hour12: false })}`;
        },
      },
      xAxis: {
        type: "time",
        ...axisStyle(p),
        splitLine: { show: false },
      },
      yAxis: {
        type: "category",
        data: LEVELS.map((l) => l.toUpperCase()),
        ...axisStyle(p),
        splitLine: { show: false },
      },
      series: present.map((level) => ({
        name: level.toUpperCase(),
        type: "scatter",
        symbolSize: (val: unknown, params: unknown) => {
          const t = (params as { data: { t: Threat } }).data.t;
          return 7 + (5 - t.rank) * 2.2;
        },
        itemStyle: {
          color: sevColor[level],
          shadowColor: sevColor[level],
          shadowBlur: 6,
          opacity: 0.9,
        },
        data: threats
          .filter((t) => t.severity === level)
          .map((t) => ({ value: [t.ts * 1000, level.toUpperCase()], t })),
      })),
    };
  };

  return <Chart build={build} deps={[threats]} style={{ height }} />;
}
