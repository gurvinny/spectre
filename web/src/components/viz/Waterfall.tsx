/**
 * Spectrogram waterfall — a scrolling time × channel heatmap. Every second a new
 * row is folded from the live frame stream (activity per channel) and pushed to the
 * top; intensity is a single-hue accent ramp (magnitude). Author: gurvinny
 */
"use client";

import { useEffect, useRef, useState } from "react";
import type { EChartsCoreOption } from "echarts";
import { Chart } from "./Chart";
import { chartBase } from "@/lib/echartsTheme";
import { countByChannel, fmtClock, is24, sortChannels } from "@/lib/format";
import type { Frame } from "@/lib/types";

const SLICES = 48; // rows retained (~48 s of history)
const SLICE_MS = 1000; // one row per second

interface Row {
  t: number;
  counts: Record<number, number>;
}

export function Waterfall({
  frames,
  height = 340,
}: {
  frames: Frame[];
  height?: number;
}) {
  const framesRef = useRef(frames);
  framesRef.current = frames;
  const [rows, setRows] = useState<Row[]>([]);
  const colsRef = useRef<Set<number>>(new Set());
  // Watermark of the newest frame we've already binned. Using the frames' own
  // (server-stamped) timestamps instead of the browser wall clock makes the
  // waterfall immune to clock skew between this browser and the sensor host.
  const lastTs = useRef(0);

  useEffect(() => {
    const tick = () => {
      const fr = framesRef.current;
      let newest = lastTs.current;
      for (const f of fr) if (f.ts > newest) newest = f.ts;
      // first tick: seed with the last ~2 s of buffer; after that, only frames
      // that arrived since the previous tick.
      const since = lastTs.current > 0 ? lastTs.current : newest - 2;
      const counts = countByChannel(fr, since);
      lastTs.current = newest;
      for (const k of Object.keys(counts)) colsRef.current.add(Number(k));
      setRows((prev) => [{ t: Date.now() / 1000, counts }, ...prev].slice(0, SLICES));
    };
    tick();
    const id = setInterval(tick, SLICE_MS);
    return () => clearInterval(id);
  }, []);

  const channels = sortChannels(colsRef.current);
  const hasData = rows.some((r) => Object.keys(r.counts).length > 0);

  if (!channels.length || !hasData) {
    return (
      <div
        className="grid place-items-center font-mono text-xs text-ink-mute"
        style={{ height }}
      >
        <span className="armed-dot">acquiring spectrum…</span>
      </div>
    );
  }

  const build = (p: Parameters<typeof chartBase>[0]): EChartsCoreOption => {
    const chIndex = new Map(channels.map((c, i) => [c, i]));
    let max = 1;
    const cells: [number, number, number][] = [];
    rows.forEach((row, y) => {
      for (const [chStr, n] of Object.entries(row.counts)) {
        const x = chIndex.get(Number(chStr));
        if (x === undefined) continue;
        max = Math.max(max, n);
        cells.push([x, y, n]);
      }
    });

    return {
      ...chartBase(p),
      grid: { top: 8, right: 12, bottom: 46, left: 44, containLabel: true },
      tooltip: {
        ...((chartBase(p) as { tooltip: object }).tooltip),
        formatter: (o: unknown) => {
          const d = (o as { data: [number, number, number] }).data;
          const ch = channels[d[0]];
          return `ch ${ch} · ${is24(ch) ? "2.4G" : "5G"}<br/>${fmtClock(
            rows[d[1]].t,
          )} · <b>${d[2]}</b> frames`;
        },
      },
      xAxis: {
        type: "category",
        data: channels.map(String),
        splitArea: { show: false },
        axisLine: { lineStyle: { color: p.line } },
        axisTick: { show: false },
        axisLabel: { color: p.inkMute, fontFamily: p.mono, fontSize: 9, interval: 0 },
        name: "channel",
        nameLocation: "middle",
        nameGap: 26,
        nameTextStyle: { color: p.inkMute, fontFamily: p.mono, fontSize: 9 },
      },
      yAxis: {
        type: "category",
        inverse: true, // newest row (index 0) on top
        data: rows.map((r) => fmtClock(r.t)),
        axisLine: { lineStyle: { color: p.line } },
        axisTick: { show: false },
        axisLabel: {
          color: p.inkMute,
          fontFamily: p.mono,
          fontSize: 9,
          interval: 7,
        },
      },
      visualMap: {
        min: 0,
        max,
        calculable: false,
        orient: "horizontal",
        left: "center",
        bottom: 0,
        itemWidth: 10,
        itemHeight: 90,
        text: ["high", "idle"],
        textStyle: { color: p.inkMute, fontFamily: p.mono, fontSize: 9 },
        inRange: { color: [p.panel, p.phosphorDim, p.phosphor] },
      },
      series: [
        {
          type: "heatmap",
          data: cells,
          progressive: 400,
          itemStyle: { borderWidth: 0 },
          emphasis: { itemStyle: { borderColor: p.ink, borderWidth: 1 } },
          animation: false,
        },
      ],
    };
  };

  return <Chart build={build} deps={[rows, channels.length]} style={{ height }} />;
}
