/**
 * Transient shockwave rings that erupt from a node when a threat references it.
 * Short-lived and capped — kept off the instanced path since each needs its own
 * mount/unmount lifecycle. Self-terminating animation: only requests frames while
 * a flash is alive, honoring demand rendering. Author: gurvinny
 */
"use client";

import { useMemo, useRef } from "react";
import { useFrame, useThree } from "@react-three/fiber";
import { AdditiveBlending, Mesh, MeshBasicMaterial } from "three";
import type { Vec3 } from "@/lib/viz3d/layout";
import type { ThreatFlash } from "@/lib/viz3d/types";
import { useThemeColors3d } from "@/hooks/viz3d/useThemeColors3d";

const CAP = 12;
const LIFETIME_S = 2.5;
const MAX_SCALE = 3.5;

function Flash({ pos, ts, color }: { pos: Vec3; ts: number; color: string }) {
  const ref = useRef<Mesh>(null);
  const matRef = useRef<MeshBasicMaterial>(null);
  const invalidate = useThree((s) => s.invalidate);

  useFrame(() => {
    const t = (Date.now() / 1000 - ts) / LIFETIME_S;
    if (!ref.current || !matRef.current) return;
    if (t >= 1) {
      ref.current.visible = false;
      return; // stop requesting frames — flash is over
    }
    const s = 0.4 + t * MAX_SCALE;
    ref.current.scale.set(s, s, s);
    matRef.current.opacity = (1 - t) * 0.85;
    invalidate();
  });

  return (
    <mesh ref={ref} position={pos} rotation={[-Math.PI / 2, 0, 0]}>
      <ringGeometry args={[0.85, 1, 40]} />
      <meshBasicMaterial
        ref={matRef}
        color={color}
        transparent
        opacity={0.85}
        blending={AdditiveBlending}
        depthWrite={false}
        toneMapped={false}
      />
    </mesh>
  );
}

export function ThreatFx({
  flashes,
  posById,
}: {
  flashes: ThreatFlash[];
  posById: Map<string, Vec3>;
}) {
  const colors = useThemeColors3d();
  const active = useMemo(
    () =>
      flashes
        .map((f) => ({ f, pos: posById.get(f.nodeId) }))
        .filter((x): x is { f: ThreatFlash; pos: Vec3 } => !!x.pos)
        .slice(0, CAP),
    [flashes, posById],
  );

  const alert = `#${colors.alert.getHexString()}`;
  const amber = `#${colors.amber.getHexString()}`;

  return (
    <>
      {active.map(({ f, pos }) => (
        <Flash
          key={f.id}
          pos={pos}
          ts={f.ts}
          color={f.severity === "critical" || f.severity === "high" ? alert : amber}
        />
      ))}
    </>
  );
}
