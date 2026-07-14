/**
 * Throughput scope — frames/sec over time as an oscilloscope trace. Single series,
 * so the panel title names it (no legend). Author: gurvinny
 */
"use client";

import type { EChartsCoreOption } from "echarts";
import { Chart } from "./Chart";
import { axisStyle, chartBase } from "@/lib/echartsTheme";
import { fmtClock } from "@/lib/format";

export function ThroughputScope({
  data,
  height = 220,
}: {
  data: { ts: number; fps: number }[];
  height?: number;
}) {
  if (!data.length) {
    return (
      <div
        className="grid place-items-center font-mono text-xs text-ink-mute"
        style={{ height }}
      >
        collecting throughput…
      </div>
    );
  }

  const build = (p: Parameters<typeof chartBase>[0]): EChartsCoreOption => ({
    ...chartBase(p),
    grid: { top: 14, right: 14, bottom: 24, left: 40, containLabel: true },
    xAxis: {
      type: "category",
      data: data.map((d) => fmtClock(d.ts)),
      boundaryGap: false,
      ...axisStyle(p),
      splitLine: { show: false },
      axisLabel: { color: p.inkMute, fontFamily: p.mono, fontSize: 9, showMaxLabel: true },
    },
    yAxis: {
      type: "value",
      name: "fps",
      nameTextStyle: { color: p.inkMute, fontFamily: p.mono, fontSize: 9 },
      ...axisStyle(p),
    },
    series: [
      {
        type: "line",
        smooth: true,
        showSymbol: false,
        data: data.map((d) => d.fps),
        lineStyle: { color: p.phosphor, width: 1.6, shadowColor: p.phosphor, shadowBlur: 6 },
        areaStyle: {
          color: {
            type: "linear",
            x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0, color: `${p.phosphor}66` },
              { offset: 1, color: `${p.phosphor}00` },
            ],
          },
        },
      },
    ],
  });

  return <Chart build={build} deps={[data]} style={{ height }} />;
}
