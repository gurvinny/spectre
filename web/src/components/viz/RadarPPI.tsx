/**
 * PPI threat radar. Devices and APs are plotted by signal strength (distance from
 * center = weaker) and band (2.4 GHz left arc, 5 GHz right arc). A sweep rotates and
 * "pings" each blip as it passes; blips tied to a recent threat flash in alert red.
 * Static, all-visible frame under prefers-reduced-motion. Author: gurvinny
 */
"use client";

import { useEffect, useRef } from "react";
import { rssiToStrength } from "@/lib/format";
import type { AccessPoint, Device } from "@/lib/types";

interface Blip {
  id: string;
  angle: number;
  radius: number; // 0 center (strong) → 1 edge (weak)
  size: number;
  band: string;
  hot: boolean;
  glow: number;
}

function hash(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return (h >>> 0) / 4294967295;
}

export function RadarPPI({
  aps = [],
  devices = [],
  threatIds,
  height = 340,
}: {
  aps?: AccessPoint[];
  devices?: Device[];
  threatIds?: Set<string>;
  height?: number;
}) {
  const ref = useRef<HTMLCanvasElement>(null);
  const dataRef = useRef({ aps, devices, threatIds });
  dataRef.current = { aps, devices, threatIds };

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)");
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    let raf = 0;
    let size = 0;
    let sweep = 0;
    const blips = new Map<string, Blip>();

    const css = (n: string, fb: string) =>
      getComputedStyle(document.documentElement).getPropertyValue(n).trim() || fb;

    function resize() {
      size = Math.min(canvas!.clientWidth, height);
      canvas!.width = size * dpr;
      canvas!.height = size * dpr;
      canvas!.style.height = `${height}px`;
      ctx!.setTransform(dpr, 0, 0, dpr, 0, 0);
    }

    // Map raw entities to blips, reusing existing glow state.
    function rebuild() {
      const { aps, devices, threatIds } = dataRef.current;
      const next = new Set<string>();
      const place = (id: string, band: string, rssi: number | null, size: number) => {
        next.add(id);
        const strong = rssiToStrength(rssi); // 1 = strong
        const radius = Math.min(0.96, Math.max(0.14, 1 - strong));
        // 2.4 GHz → left arc (90°..270°), 5 GHz → right arc (−90°..90°)
        const is5 = band.startsWith("5");
        const base = is5 ? -Math.PI / 2 : Math.PI / 2;
        const angle = base + (hash(id) - 0.5) * Math.PI * 0.92;
        const hot = !!threatIds?.has(id.toUpperCase());
        const ex = blips.get(id);
        blips.set(id, {
          id,
          angle,
          radius,
          size,
          band,
          hot,
          glow: ex?.glow ?? 0,
        });
      };
      for (const a of aps)
        place(a.bssid, a.band, a.last_rssi, 3 + Math.min(4, Math.log10((a.beacons || 1) + 1) * 2));
      for (const d of devices.slice(0, 60))
        place(d.mac, d.bands || "2.4", d.last_rssi, 2.4 + Math.min(3.5, Math.log10((d.frames || 1) + 1)));
      for (const id of [...blips.keys()]) if (!next.has(id)) blips.delete(id);
    }

    function draw() {
      const accent = css("--color-phosphor", "#35e0c4");
      const violet = css("--color-violet", "#9b8cff");
      const alert = css("--color-alert", "#ff4d5e");
      const grid = css("--color-scope-grid", "#1e2a35");
      const line = css("--color-scope-line", "#263542");
      const mute = css("--color-ink-mute", "#5b6b78");
      const mono = css("--font-plex-mono", "monospace");

      const c = size / 2;
      const R = c - 14;
      ctx!.clearRect(0, 0, size, size);

      // range rings + rssi labels
      ctx!.strokeStyle = grid;
      ctx!.lineWidth = 1;
      ctx!.font = `9px ${mono}`;
      ctx!.fillStyle = mute;
      ctx!.textAlign = "left";
      const rings = [0.25, 0.5, 0.75, 1];
      const dbs = ["-45", "-60", "-75", "-90"];
      rings.forEach((r, i) => {
        ctx!.globalAlpha = 0.7;
        ctx!.beginPath();
        ctx!.arc(c, c, R * r, 0, Math.PI * 2);
        ctx!.stroke();
        ctx!.globalAlpha = 0.5;
        ctx!.fillText(dbs[i], c + 3, c - R * r + 8);
      });
      ctx!.globalAlpha = 1;

      // spokes + vertical band divider
      ctx!.strokeStyle = line;
      ctx!.beginPath();
      ctx!.moveTo(c, c - R);
      ctx!.lineTo(c, c + R);
      ctx!.moveTo(c - R, c);
      ctx!.lineTo(c + R, c);
      ctx!.stroke();

      // band sector labels
      ctx!.fillStyle = accent;
      ctx!.globalAlpha = 0.7;
      ctx!.textAlign = "center";
      ctx!.fillText("2.4 GHz", c - R * 0.6, c + R + 2);
      ctx!.fillStyle = violet;
      ctx!.fillText("5 GHz", c + R * 0.6, c + R + 2);
      ctx!.globalAlpha = 1;
      ctx!.textAlign = "left";

      // rotating sweep wedge
      if (!reduce.matches) {
        const wedge = 0.5;
        ctx!.save();
        ctx!.translate(c, c);
        ctx!.beginPath();
        ctx!.moveTo(0, 0);
        ctx!.arc(0, 0, R, sweep - wedge, sweep);
        ctx!.closePath();
        const rad = ctx!.createRadialGradient(0, 0, 0, 0, 0, R);
        rad.addColorStop(0, `${accent}00`);
        rad.addColorStop(1, `${accent}30`);
        ctx!.fillStyle = rad;
        ctx!.fill();
        // leading edge line
        ctx!.strokeStyle = accent;
        ctx!.globalAlpha = 0.7;
        ctx!.beginPath();
        ctx!.moveTo(0, 0);
        ctx!.lineTo(Math.cos(sweep) * R, Math.sin(sweep) * R);
        ctx!.stroke();
        ctx!.globalAlpha = 1;
        ctx!.restore();
      }

      // blips
      const twoPi = Math.PI * 2;
      for (const b of blips.values()) {
        // ping when sweep passes
        if (!reduce.matches) {
          const diff = Math.abs(((sweep - b.angle + Math.PI) % twoPi) - Math.PI);
          if (diff < 0.06) b.glow = 1;
          b.glow *= 0.97;
        } else {
          b.glow = 0.5;
        }
        const bx = c + Math.cos(b.angle) * R * b.radius;
        const by = c + Math.sin(b.angle) * R * b.radius;
        const col = b.hot ? alert : b.band.startsWith("5") ? violet : accent;
        const a = 0.28 + b.glow * 0.72;
        ctx!.globalAlpha = a;
        ctx!.fillStyle = col;
        if (b.glow > 0.3 || b.hot) {
          ctx!.shadowColor = col;
          ctx!.shadowBlur = 8 * (b.hot ? 1 : b.glow);
        }
        ctx!.beginPath();
        ctx!.arc(bx, by, b.size, 0, twoPi);
        ctx!.fill();
        ctx!.shadowBlur = 0;
        if (b.hot) {
          ctx!.globalAlpha = 0.5 + 0.5 * Math.abs(Math.sin(sweep * 3));
          ctx!.strokeStyle = alert;
          ctx!.lineWidth = 1;
          ctx!.beginPath();
          ctx!.arc(bx, by, b.size + 3, 0, twoPi);
          ctx!.stroke();
        }
        ctx!.globalAlpha = 1;
      }
    }

    let acc = 0;
    function loop() {
      acc++;
      if (acc % 30 === 0) rebuild();
      sweep = (sweep + 0.02) % (Math.PI * 2);
      draw();
      if (!reduce.matches) raf = requestAnimationFrame(loop);
    }

    resize();
    rebuild();
    const ro = new ResizeObserver(resize);
    ro.observe(canvas);

    if (reduce.matches) {
      const id = setInterval(() => {
        rebuild();
        draw();
      }, 3000);
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
    <div className="grid place-items-center">
      <canvas ref={ref} className="block" style={{ height, width: "100%", maxWidth: height }} />
    </div>
  );
}
