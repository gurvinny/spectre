/**
 * Live spectrum analyzer. Bars ease toward the current per-channel activity, a
 * decaying peak-hold line tops each channel, a scan highlight sweeps across, and a
 * dB-style grid frames it. 2.4 GHz channels read in the accent, 5 GHz in violet.
 * Canvas-rendered for smooth 60 fps; falls back to a static frame under
 * prefers-reduced-motion. Author: gurvinny
 */
"use client";

import { useEffect, useRef } from "react";
import { is24, sortChannels } from "@/lib/format";

interface Bar {
  ch: number;
  target: number; // 0..1
  cur: number;
  peak: number;
}

export function SpectrumAnalyzer({
  channels,
  height = 170,
}: {
  channels: Record<string, number>;
  height?: number;
}) {
  const ref = useRef<HTMLCanvasElement>(null);
  const bars = useRef<Map<number, Bar>>(new Map());
  const targetsRef = useRef(channels);
  targetsRef.current = channels;

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)");
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    let raf = 0;
    let w = 0;
    const h = height;
    let sweep = -0.1;

    const css = (name: string, fb: string) =>
      getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fb;

    function resize() {
      w = canvas!.clientWidth;
      canvas!.width = w * dpr;
      canvas!.height = h * dpr;
      canvas!.style.height = `${h}px`;
      ctx!.setTransform(dpr, 0, 0, dpr, 0, 0);
    }

    function syncBars() {
      const data = targetsRef.current;
      const chs = sortChannels(Object.keys(data).map(Number).filter((n) => !Number.isNaN(n)));
      const max = Math.max(1, ...chs.map((c) => data[String(c)] ?? 0));
      const seen = new Set<number>();
      for (const ch of chs) {
        seen.add(ch);
        const t = (data[String(ch)] ?? 0) / max;
        const b = bars.current.get(ch);
        if (b) b.target = t;
        else bars.current.set(ch, { ch, target: t, cur: t, peak: t });
      }
      // decay channels that dropped out of the window toward zero
      for (const [ch, b] of bars.current) {
        if (!seen.has(ch)) b.target = 0;
        if (b.target === 0 && b.cur < 0.02 && b.peak < 0.02) bars.current.delete(ch);
      }
    }

    function draw() {
      const accent = css("--color-phosphor", "#35e0c4");
      const violet = css("--color-violet", "#9b8cff");
      const grid = css("--color-scope-grid", "#1e2a35");
      const mute = css("--color-ink-mute", "#5b6b78");
      const mono = css("--font-plex-mono", "monospace");

      ctx!.clearRect(0, 0, w, h);
      const padB = 16; // room for channel labels
      const plotH = h - padB;

      // dB grid lines
      ctx!.strokeStyle = grid;
      ctx!.lineWidth = 1;
      ctx!.font = `9px ${mono}`;
      ctx!.fillStyle = mute;
      ctx!.textBaseline = "middle";
      const dbLabels = ["-30", "-50", "-70", "-90"];
      for (let i = 0; i < dbLabels.length; i++) {
        const y = (plotH / (dbLabels.length - 1)) * i + 0.5;
        ctx!.globalAlpha = 0.6;
        ctx!.beginPath();
        ctx!.moveTo(24, y);
        ctx!.lineTo(w, y);
        ctx!.stroke();
        ctx!.globalAlpha = 1;
        ctx!.fillText(dbLabels[i], 2, y);
      }

      const list = [...bars.current.values()].sort((a, b) => a.ch - b.ch);
      if (!list.length) {
        ctx!.fillStyle = mute;
        ctx!.textAlign = "center";
        ctx!.fillText("no channel activity yet", w / 2, plotH / 2);
        ctx!.textAlign = "left";
        return;
      }

      const plotX = 26;
      const plotW = w - plotX;
      const slot = plotW / list.length;
      const bw = Math.max(3, slot * 0.62);

      list.forEach((b, i) => {
        // animate toward target
        b.cur += (b.target - b.cur) * 0.18;
        b.peak = Math.max(b.peak - 0.006, b.cur);
        const color = is24(b.ch) ? accent : violet;
        const x = plotX + i * slot + (slot - bw) / 2;
        const bh = Math.max(1, b.cur * plotH);
        const y = plotH - bh;

        // bar with vertical gradient
        const g = ctx!.createLinearGradient(0, plotH, 0, y);
        g.addColorStop(0, color);
        g.addColorStop(1, `${color}44`);
        ctx!.fillStyle = g;
        if (b.cur > 0.6) {
          ctx!.shadowColor = color;
          ctx!.shadowBlur = 10;
        }
        ctx!.fillRect(x, y, bw, bh);
        ctx!.shadowBlur = 0;

        // peak-hold tick
        const py = plotH - Math.max(1, b.peak * plotH);
        ctx!.fillStyle = color;
        ctx!.globalAlpha = 0.85;
        ctx!.fillRect(x, py, bw, 1.5);
        ctx!.globalAlpha = 1;

        // sparse channel labels
        if (list.length <= 18 || i % 3 === 0) {
          ctx!.fillStyle = mute;
          ctx!.font = `9px ${mono}`;
          ctx!.textAlign = "center";
          ctx!.fillText(String(b.ch), x + bw / 2, h - 6);
          ctx!.textAlign = "left";
        }
      });

      // scan highlight sweep
      if (!reduce.matches) {
        const sx = plotX + sweep * plotW;
        const sg = ctx!.createLinearGradient(sx - 40, 0, sx + 40, 0);
        sg.addColorStop(0, "transparent");
        sg.addColorStop(0.5, `${accent}22`);
        sg.addColorStop(1, "transparent");
        ctx!.fillStyle = sg;
        ctx!.fillRect(sx - 40, 0, 80, plotH);
        sweep += 0.004;
        if (sweep > 1.1) sweep = -0.1;
      }
    }

    let acc = 0;
    function loop(t: number) {
      // resync targets a few times/sec; draw every frame for smooth easing
      acc += 1;
      if (acc % 6 === 0) syncBars();
      draw();
      if (!reduce.matches) raf = requestAnimationFrame(loop);
    }

    resize();
    syncBars();
    const ro = new ResizeObserver(resize);
    ro.observe(canvas);

    if (reduce.matches) {
      // static single paint
      const id = setInterval(() => {
        syncBars();
        // snap to targets so no easing
        for (const b of bars.current.values()) {
          b.cur = b.target;
          b.peak = b.target;
        }
        draw();
      }, 1500);
      draw();
      return () => {
        clearInterval(id);
        ro.disconnect();
      };
    }

    raf = requestAnimationFrame(loop);
    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
    };
  }, [height]);

  return (
    <div>
      <canvas ref={ref} className="w-full block" style={{ height }} />
      <div className="flex justify-between mt-1 font-mono text-[0.6rem] text-ink-mute">
        <span className="text-phosphor-dim">▚ 2.4 GHz</span>
        <span className="text-ink-mute">channel utilization</span>
        <span className="text-violet">5 GHz ▚</span>
      </div>
    </div>
  );
}
