/**
 * Client shell for the RF battlespace. Owns the react-three-fiber canvas (demand
 * rendering, low-power GL), subscribes to the shared live feed + polled inventory
 * — no new socket — and renders the 2D HUD overlays (legend, counts, click-to-
 * inspect) as plain DOM over the canvas. Pauses rendering when the tab is hidden.
 * Author: gurvinny
 */
"use client";

import { useEffect, useMemo, useState } from "react";
import { Canvas } from "@react-three/fiber";
import { useLive } from "@/components/LiveProvider";
import { usePoll } from "@/hooks/usePoll";
import { useBattlespaceModel } from "@/hooks/viz3d/useBattlespaceModel";
import { BattlespaceScene } from "@/components/viz3d/BattlespaceScene";
import { CanvasErrorBoundary } from "@/components/viz3d/CanvasErrorBoundary";
import { PerfToggle } from "@/components/viz3d/PerfToggle";
import { Pill } from "@/components/ui";
import { timeAgo, rssiColor, bandColor } from "@/lib/format";
import type { AccessPoint, Device, Threat } from "@/lib/types";
import type { SelectedNode } from "@/lib/viz3d/types";
import type { PerfMode, Tier } from "@/lib/viz3d/quality";

const PERF_KEY = "spectre-bsp-perf";
const isPerfMode = (v: string | null): v is PerfMode =>
  v === "performance" || v === "balanced" || v === "beauty";

/** Dev-only: `?fx=demo` injects synthetic threats so the attack-beam layer can
 *  be seen without waiting on a real deauth flood / evil twin. Never in prod. */
const demoEnabled = (): boolean =>
  typeof window !== "undefined" &&
  process.env.NODE_ENV !== "production" &&
  new URLSearchParams(window.location.search).get("fx") === "demo";

function buildDemoThreats(aps: AccessPoint[], devices: Device[]): Threat[] {
  const now = Date.now() / 1000;
  const out: Threat[] = [];
  // Prefer AP↔AP endpoints (always rendered) so the demo beams are guaranteed
  // visible; fall back to a client target when only one AP is known.
  const target = aps[1]?.bssid ?? devices[0]?.mac ?? null;
  if (aps[0] && target) {
    out.push({
      ts: now,
      rule: "deauth_flood",
      severity: "high",
      rank: 2,
      title: "[demo] deauth flood",
      band: aps[0].band,
      bssid: aps[0].bssid,
      ssid: aps[0].ssid,
      src: aps[0].bssid,
      detail: { target_dst: target, rate_per_sec: 42 },
    });
  }
  if (aps[0] && aps[1]) {
    out.push({
      ts: now,
      rule: "evil_twin",
      severity: "critical",
      rank: 1,
      title: "[demo] evil twin",
      band: aps[1].band,
      bssid: aps[1].bssid,
      ssid: aps[0].ssid,
      src: null,
      detail: { rogue_bssid: aps[1].bssid, known_bssids: [aps[0].bssid] },
    });
  }
  return out;
}

export function BattlespaceView() {
  const { frames, threats, overview } = useLive();
  const { data: apData } = usePoll<{ access_points: AccessPoint[] }>("/api/access-points", 6000);
  const { data: devData } = usePoll<{ devices: Device[] }>("/api/devices", 8000);

  // Dev-only synthetic threats (?fx=demo), refreshed on a cycle so the beams
  // replay. `useMemo` keeps the threats array identity stable between cycles.
  const [demoTick, setDemoTick] = useState(0);
  const demo = demoEnabled();
  useEffect(() => {
    if (!demo) return;
    const id = setInterval(() => setDemoTick((n) => n + 1), 6000);
    return () => clearInterval(id);
  }, [demo]);
  const demoThreats = useMemo(
    () =>
      demo
        ? buildDemoThreats(apData?.access_points ?? [], devData?.devices ?? [])
        : [],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [demo, demoTick, apData, devData],
  );

  const mergedThreats = useMemo(
    () => (demoThreats.length ? [...threats, ...demoThreats] : threats),
    [threats, demoThreats],
  );

  const model = useBattlespaceModel({
    aps: apData?.access_points ?? [],
    devices: devData?.devices ?? [],
    frames,
    threats: mergedThreats,
  });

  const [selected, setSelected] = useState<SelectedNode | null>(null);
  const [hidden, setHidden] = useState(false);
  const [reduced, setReduced] = useState(false);
  const [mode, setMode] = useState<PerfMode>(() => {
    if (typeof window === "undefined") return "balanced";
    const v = window.localStorage.getItem(PERF_KEY);
    return isPerfMode(v) ? v : "balanced";
  });
  const [tier, setTier] = useState<Tier>("med");

  const changeMode = (m: PerfMode) => {
    setMode(m);
    try {
      window.localStorage.setItem(PERF_KEY, m);
    } catch {
      /* storage unavailable — session-only */
    }
  };

  useEffect(() => {
    const onVis = () => setHidden(document.visibilityState === "hidden");
    document.addEventListener("visibilitychange", onVis);
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    const onMq = () => setReduced(mq.matches);
    onMq();
    mq.addEventListener("change", onMq);
    return () => {
      document.removeEventListener("visibilitychange", onVis);
      mq.removeEventListener("change", onMq);
    };
  }, []);

  const sensors = overview?.sensors ?? [];
  const counts = useMemo(
    () => ({
      aps: model.apNodes.length,
      clients: model.clientNodes.length,
      edges: model.edges.length,
      mesh: model.meshLinks.length,
      channels: Object.keys(model.channelActivity).length,
    }),
    [model],
  );

  return (
    <div className="relative w-full h-[74vh] min-h-[520px] rounded-sm border border-scope-line overflow-hidden bg-scope-bg">
      <CanvasErrorBoundary>
        <Canvas
          frameloop={hidden ? "never" : "demand"}
          dpr={1}
          camera={{ position: [0, 10, 24], fov: 45 }}
          gl={{
            antialias: false,
            alpha: false,
            powerPreference: "low-power",
            failIfMajorPerformanceCaveat: false,
          }}
          onPointerMissed={() => setSelected(null)}
          onCreated={({ gl }) => {
            // Don't let a lost GPU context hard-crash the tab; log and let r3f
            // restore it when possible.
            gl.domElement.addEventListener(
              "webglcontextlost",
              (e) => {
                e.preventDefault();
                console.warn("[battlespace] WebGL context lost");
              },
              { passive: false },
            );
          }}
        >
          <BattlespaceScene
            model={model}
            sensors={sensors}
            wazuh={overview?.wazuh ?? null}
            reducedMotion={reduced}
            mode={mode}
            onTierChange={setTier}
            onSelect={setSelected}
          />
        </Canvas>
      </CanvasErrorBoundary>

      {/* top-right: adaptive-quality control */}
      <div className="absolute top-3 right-3">
        <PerfToggle mode={mode} onMode={changeMode} tier={tier} />
      </div>

      {/* top-left: live counts */}
      <div className="absolute top-3 left-3 flex flex-wrap gap-1.5 pointer-events-none">
        <Pill color="var(--color-phosphor)">{counts.aps} APS</Pill>
        <Pill color="var(--color-violet)">{counts.clients} CLIENTS</Pill>
        <Pill color="var(--color-ink-dim)">{counts.edges} LINKS</Pill>
        <Pill color="var(--color-rf-amber)">{counts.mesh} MESH</Pill>
        <Pill color="var(--color-ink-dim)">{counts.channels} CH</Pill>
      </div>

      {/* bottom-left: legend */}
      <div className="absolute bottom-3 left-3 flex flex-col gap-1 font-mono text-[0.6rem] text-ink-mute pointer-events-none">
        <LegendRow color="var(--color-phosphor)" label="2.4 GHz" />
        <LegendRow color="var(--color-violet)" label="5 GHz" />
        <LegendRow color="var(--color-rf-amber)" label="mesh · same SSID" />
        <LegendRow color="var(--color-alert)" label="threat" />
        <span className="text-ink-mute/70 mt-0.5">height = signal · sensor on top</span>
        <span className="text-ink-mute/70">drag orbit · scroll zoom · click a node</span>
      </div>

      {/* right: inspector (below the perf toggle) */}
      {selected && (
        <div className="absolute top-12 right-3 w-64 panel pointer-events-auto">
          <header className="flex items-center justify-between px-3 h-8 border-b border-scope-line">
            <span className="panel-head">{selected.kind === "ap" ? "Access point" : "Client"}</span>
            <button
              onClick={() => setSelected(null)}
              className="font-mono text-[0.7rem] text-ink-mute hover:text-alert"
              aria-label="Close inspector"
            >
              ✕
            </button>
          </header>
          <div className="p-3 flex flex-col gap-1.5 font-mono text-[0.68rem]">
            <Row label="ID" value={selected.id} mono />
            <Row label="SSID" value={selected.ssid || "—"} />
            <Row label="Band" value={<Pill color={bandColor(selected.band)}>{selected.band}</Pill>} />
            <Row
              label="RSSI"
              value={
                <span style={{ color: rssiColor(selected.rssi) }}>
                  {selected.rssi != null ? `${selected.rssi} dBm` : "—"}
                </span>
              }
            />
            {selected.kind === "ap" ? (
              <>
                <Row label="Beacons" value={selected.beacons.toLocaleString()} />
                <Row label="Known" value={selected.known ? "yes" : "no"} />
              </>
            ) : (
              <>
                <Row label="Frames" value={selected.frames.toLocaleString()} />
                <Row label="Assoc" value={selected.assocBssid || "—"} mono />
                <Row label="Random MAC" value={selected.random ? "yes" : "no"} />
              </>
            )}
            <Row label="Last seen" value={`${timeAgo(selected.lastSeen)} ago`} />
          </div>
        </div>
      )}
    </div>
  );
}

function LegendRow({ color, label }: { color: string; label: string }) {
  return (
    <span className="flex items-center gap-1.5">
      <span className="w-2 h-2 rounded-full" style={{ background: color }} />
      {label}
    </span>
  );
}

function Row({
  label,
  value,
  mono,
}: {
  label: string;
  value: React.ReactNode;
  mono?: boolean;
}) {
  return (
    <div className="flex items-center justify-between gap-2">
      <span className="text-ink-mute tracking-wide">{label}</span>
      <span className={mono ? "text-ink truncate max-w-[9rem]" : "text-ink"}>{value}</span>
    </div>
  );
}
