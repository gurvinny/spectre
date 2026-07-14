/**
 * Thin React wrapper around an ECharts canvas instance. Builds its option from the
 * live palette, resizes with its container, re-tints on theme change, and disposes
 * cleanly. `build` receives the resolved palette so charts never hardcode color.
 * Author: gurvinny
 */
"use client";

import { useEffect, useRef } from "react";
import * as echarts from "echarts";
import { readPalette, type Palette } from "@/lib/echartsTheme";
import { THEME_EVENT } from "@/lib/theme";

export function Chart({
  build,
  deps = [],
  className,
  style,
}: {
  build: (p: Palette) => echarts.EChartsCoreOption;
  deps?: unknown[];
  className?: string;
  style?: React.CSSProperties;
}) {
  const host = useRef<HTMLDivElement>(null);
  const inst = useRef<echarts.ECharts | null>(null);
  const buildRef = useRef(build);
  buildRef.current = build;

  // init once
  useEffect(() => {
    if (!host.current) return;
    const chart = echarts.init(host.current, undefined, { renderer: "canvas" });
    inst.current = chart;
    const render = () => chart.setOption(buildRef.current(readPalette()), true);
    render();

    const ro = new ResizeObserver(() => chart.resize());
    ro.observe(host.current);
    window.addEventListener(THEME_EVENT, render);

    return () => {
      window.removeEventListener(THEME_EVENT, render);
      ro.disconnect();
      chart.dispose();
      inst.current = null;
    };
  }, []);

  // re-render on data changes
  useEffect(() => {
    inst.current?.setOption(buildRef.current(readPalette()), true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return (
    <div
      ref={host}
      className={className}
      style={{ width: "100%", height: "100%", ...style }}
    />
  );
}
