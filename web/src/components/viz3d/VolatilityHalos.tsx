/**
 * RSSI-volatility rings: a flat halo under any client whose signal swings widely
 * (max_rssi − min_rssi), flagging movement or possible spoofing. Radius grows
 * with the spread; color escalates ink→amber→alert. One raw InstancedMesh of
 * additive annuli; at the high tier they breathe, de-phased per node so they
 * never pulse in unison. Author: gurvinny
 */
"use client";

import { useEffect, useMemo, useRef } from "react";
import { useFrame, useThree } from "@react-three/fiber";
import {
  AdditiveBlending,
  Color,
  InstancedMesh,
  Matrix4,
  Euler,
  Quaternion,
  Vector3,
} from "three";
import type { ClientNode } from "@/lib/viz3d/types";
import { hashUnit } from "@/lib/viz3d/layout";
import { ageOpacity } from "@/lib/viz3d/aging";
import { useThemeColors3d } from "@/hooks/viz3d/useThemeColors3d";
import { useQuality, useContinuousMotion } from "./QualityProvider";

const LIMIT = 64;
/** Minimum spread (dB) worth flagging. */
const MIN_SPREAD = 12;
const SPREAD_HI = 40; // spread that maps to the largest ring
const R_MIN = 0.35;
const R_MAX_RING = 1.1;
/** Flat on the floor plane. */
const FLAT = new Quaternion().setFromEuler(new Euler(-Math.PI / 2, 0, 0));

interface Ring {
  pos: [number, number, number];
  radius: number;
  color: Color;
  phase: number;
}

export function VolatilityHalos({
  clientNodes,
  renderOrder = 2,
}: {
  clientNodes: ClientNode[];
  renderOrder?: number;
}) {
  const invalidate = useThree((s) => s.invalidate);
  const colors = useThemeColors3d();
  const { flags } = useQuality();
  const ref = useRef<InstancedMesh>(null);
  useContinuousMotion(flags.haloBreathing);

  const rings = useMemo<Ring[]>(() => {
    const now = Date.now() / 1000;
    const out: Ring[] = [];
    for (const n of clientNodes) {
      if (out.length >= LIMIT) break;
      const s = n.rssiSpread;
      if (s == null || s < MIN_SPREAD) continue;
      const f = Math.min(1, (s - MIN_SPREAD) / (SPREAD_HI - MIN_SPREAD));
      const radius = R_MIN + f * (R_MAX_RING - R_MIN);
      // ink → amber (12–25 dB) → alert (>25 dB), dimmed toward black by age.
      const col = colors.inkMute.clone();
      col.lerp(colors.amber, Math.min(1, (s - MIN_SPREAD) / (25 - MIN_SPREAD)));
      if (s > 25) col.lerp(colors.alert, Math.min(1, (s - 25) / (SPREAD_HI - 25)));
      col.multiplyScalar(ageOpacity(n.lastSeen, now) * 0.7);
      out.push({
        pos: [n.pos[0], n.pos[1] - 0.05, n.pos[2]],
        radius,
        color: col,
        phase: hashUnit(n.id) * Math.PI * 2,
      });
    }
    return out;
  }, [clientNodes, colors]);

  const scratch = useMemo(
    () => ({ mat: new Matrix4(), pos: new Vector3(), scl: new Vector3() }),
    [],
  );

  const writeMatrix = (i: number, scaleMul: number) => {
    const mesh = ref.current!;
    const r = rings[i];
    const { mat, pos, scl } = scratch;
    pos.set(r.pos[0], r.pos[1], r.pos[2]);
    scl.setScalar(r.radius * scaleMul);
    mat.compose(pos, FLAT, scl);
    mesh.setMatrixAt(i, mat);
  };

  // Colors + base matrices; a nudge so the static case paints under demand mode.
  useEffect(() => {
    const mesh = ref.current;
    if (!mesh) return;
    mesh.count = rings.length;
    for (let i = 0; i < rings.length; i++) {
      mesh.setColorAt(i, rings[i].color);
      writeMatrix(i, 1);
    }
    mesh.instanceMatrix.needsUpdate = true;
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
    invalidate();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [rings, invalidate]);

  // High tier only: gentle breathing, de-phased per node.
  useFrame(({ clock }) => {
    if (!flags.haloBreathing) return;
    const mesh = ref.current;
    if (!mesh) return;
    const t = clock.elapsedTime;
    for (let i = 0; i < rings.length; i++) {
      writeMatrix(i, 1 + 0.08 * Math.sin((t * Math.PI * 2) / 3 + rings[i].phase));
    }
    mesh.instanceMatrix.needsUpdate = true;
  });

  return (
    <instancedMesh
      ref={ref}
      args={[undefined, undefined, LIMIT]}
      frustumCulled={false}
      raycast={() => null}
      renderOrder={renderOrder}
    >
      <ringGeometry args={[0.85, 1, 32]} />
      <meshBasicMaterial
        transparent
        depthWrite={false}
        toneMapped={false}
        blending={AdditiveBlending}
      />
    </instancedMesh>
  );
}
