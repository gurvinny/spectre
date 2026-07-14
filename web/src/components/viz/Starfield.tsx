/**
 * Ambient backdrop: a slow drift of faint stars with the occasional shooting-star
 * streak tinted to the active accent. Fixed behind the app content. Pauses under
 * prefers-reduced-motion and whenever the tab is hidden, so it never burns CPU on
 * the 4 GB box while nobody's watching. Author: gurvinny
 */
"use client";

import { useEffect, useRef } from "react";
import { THEME_EVENT } from "@/lib/theme";

interface Star {
  x: number;
  y: number;
  r: number;
  a: number; // base alpha
  tw: number; // twinkle phase speed
  vx: number;
}
interface Shooter {
  x: number;
  y: number;
  vx: number;
  vy: number;
  life: number;
  max: number;
}

export function Starfield() {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)");
    let accent = readAccent();
    let stars: Star[] = [];
    let shooters: Shooter[] = [];
    let raf = 0;
    let running = false;
    let last = 0;
    let nextShooter = 0;
    let w = 0;
    let h = 0;

    const dpr = Math.min(window.devicePixelRatio || 1, 2);

    function resize() {
      w = window.innerWidth;
      h = window.innerHeight;
      canvas!.width = w * dpr;
      canvas!.height = h * dpr;
      canvas!.style.width = `${w}px`;
      canvas!.style.height = `${h}px`;
      ctx!.setTransform(dpr, 0, 0, dpr, 0, 0);
      // density scales with area but stays bounded
      const count = Math.min(120, Math.round((w * h) / 14000));
      stars = Array.from({ length: count }, () => ({
        x: Math.random() * w,
        y: Math.random() * h,
        r: Math.random() * 1.1 + 0.3,
        a: Math.random() * 0.4 + 0.15,
        tw: Math.random() * 1.6 + 0.4,
        vx: -(Math.random() * 4 + 1) / 60, // gentle leftward drift px/frame
      }));
    }

    function spawnShooter() {
      const fromTop = Math.random() > 0.4;
      const speed = Math.random() * 6 + 7;
      shooters.push({
        x: Math.random() * w,
        y: fromTop ? -20 : Math.random() * h * 0.5,
        vx: -(speed * 0.9),
        vy: speed * 0.5,
        life: 0,
        max: Math.random() * 40 + 40,
      });
    }

    function frame(t: number) {
      if (!running) return;
      const dt = last ? Math.min((t - last) / 16.67, 3) : 1;
      last = t;
      ctx!.clearRect(0, 0, w, h);

      // stars
      for (const s of stars) {
        s.x += s.vx * dt;
        if (s.x < -2) s.x = w + 2;
        const tw = s.a + Math.sin(t * 0.001 * s.tw) * 0.12;
        ctx!.globalAlpha = Math.max(0, tw);
        ctx!.fillStyle = s.r > 0.9 ? accent : "#8fa4b3";
        ctx!.beginPath();
        ctx!.arc(s.x, s.y, s.r, 0, Math.PI * 2);
        ctx!.fill();
      }

      // shooting stars
      if (t > nextShooter) {
        spawnShooter();
        nextShooter = t + Math.random() * 6000 + 3500;
      }
      for (const sh of shooters) {
        sh.x += sh.vx * dt;
        sh.y += sh.vy * dt;
        sh.life += dt;
        const p = sh.life / sh.max;
        const alpha = Math.sin(Math.min(1, p) * Math.PI); // fade in/out
        const len = 90;
        const tx = sh.x - sh.vx * (len / Math.hypot(sh.vx, sh.vy));
        const ty = sh.y - sh.vy * (len / Math.hypot(sh.vx, sh.vy));
        const grad = ctx!.createLinearGradient(sh.x, sh.y, tx, ty);
        grad.addColorStop(0, accent);
        grad.addColorStop(1, "transparent");
        ctx!.globalAlpha = alpha * 0.9;
        ctx!.strokeStyle = grad;
        ctx!.lineWidth = 1.6;
        ctx!.beginPath();
        ctx!.moveTo(sh.x, sh.y);
        ctx!.lineTo(tx, ty);
        ctx!.stroke();
        // bright head
        ctx!.globalAlpha = alpha;
        ctx!.fillStyle = accent;
        ctx!.beginPath();
        ctx!.arc(sh.x, sh.y, 1.6, 0, Math.PI * 2);
        ctx!.fill();
      }
      shooters = shooters.filter((s) => s.life < s.max && s.y < h + 30);
      ctx!.globalAlpha = 1;
      raf = requestAnimationFrame(frame);
    }

    function start() {
      if (running || reduce.matches || document.hidden) return;
      running = true;
      last = 0;
      raf = requestAnimationFrame(frame);
    }
    function stop() {
      running = false;
      cancelAnimationFrame(raf);
      ctx!.clearRect(0, 0, w, h);
    }

    function onVisibility() {
      if (document.hidden) stop();
      else start();
    }
    function onReduce() {
      if (reduce.matches) stop();
      else start();
    }
    function onTheme() {
      accent = readAccent();
    }

    resize();
    start();
    window.addEventListener("resize", resize);
    document.addEventListener("visibilitychange", onVisibility);
    reduce.addEventListener("change", onReduce);
    window.addEventListener(THEME_EVENT, onTheme);

    return () => {
      stop();
      window.removeEventListener("resize", resize);
      document.removeEventListener("visibilitychange", onVisibility);
      reduce.removeEventListener("change", onReduce);
      window.removeEventListener(THEME_EVENT, onTheme);
    };
  }, []);

  return (
    <canvas
      ref={ref}
      aria-hidden="true"
      className="pointer-events-none fixed inset-0"
      style={{ zIndex: 0 }}
    />
  );
}

function readAccent(): string {
  if (typeof window === "undefined") return "#35e0c4";
  return (
    getComputedStyle(document.documentElement)
      .getPropertyValue("--color-phosphor")
      .trim() || "#35e0c4"
  );
}
