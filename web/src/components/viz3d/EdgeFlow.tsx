/**
 * Live edge data-flow: light pulses that travel along association and mesh links,
 * their count and brightness set by each link's recent traffic (activity). One
 * raw InstancedMesh of camera-facing halo billboards — the same technique as
 * NodeHalos — driven by the pure pulse math in lib/viz3d/flow. Gated on the
 * quality tier's edgeFlow flag; the underlying segments stay static so nothing
 * rewrites line buffers per frame. Author: gurvinny
 */
"use client";

import { useMemo, useRef } from "react";
import { useFrame } from "@react-three/fiber";
import {
  AdditiveBlending,
  Color,
  InstancedMesh,
  Matrix4,
  Vector3,
} from "three";
import type { Vec3 } from "@/lib/viz3d/layout";
import type { EdgeModel } from "@/lib/viz3d/types";
import { pulseFrac, pulsesForEdges, PULSE_LIMIT, type FlowPulse } from "@/lib/viz3d/flow";
import { getHaloTexture } from "@/lib/viz3d/textures";
import { useThemeColors3d } from "@/hooks/viz3d/useThemeColors3d";
import { useQuality, useContinuousMotion } from "./QualityProvider";

const PULSE_SIZE = 0.16;

interface ResolvedPulse extends FlowPulse {
  a: Vec3;
  b: Vec3;
}

export function EdgeFlow({
  edges,
  meshLinks,
  posById,
  renderOrder = 4,
}: {
  edges: EdgeModel[];
  meshLinks: EdgeModel[];
  posById: Map<string, Vec3>;
  renderOrder?: number;
}) {
  const { tier, flags } = useQuality();
  if (!flags.edgeFlow) return null;
  return (
    <FlowPulses
      edges={edges}
      meshLinks={meshLinks}
      posById={posById}
      tier={tier}
      renderOrder={renderOrder}
    />
  );
}

function FlowPulses({
  edges,
  meshLinks,
  posById,
  tier,
  renderOrder,
}: {
  edges: EdgeModel[];
  meshLinks: EdgeModel[];
  posById: Map<string, Vec3>;
  tier: "low" | "med" | "high";
  renderOrder: number;
}) {
  useContinuousMotion(true); // only mounted while edgeFlow is on

  const colors = useThemeColors3d();
  const texture = useMemo(() => getHaloTexture(), []);
  const ref = useRef<InstancedMesh>(null);

  // Resolve each selected pulse's endpoints to world positions once.
  const pulses = useMemo<ResolvedPulse[]>(() => {
    const selected = pulsesForEdges(edges, meshLinks, tier);
    const out: ResolvedPulse[] = [];
    for (const p of selected) {
      const a = posById.get(p.from);
      const b = posById.get(p.to);
      if (a && b) out.push({ ...p, a, b });
      if (out.length >= PULSE_LIMIT) break;
    }
    return out;
  }, [edges, meshLinks, tier, posById]);

  const scratch = useMemo(
    () => ({ mat: new Matrix4(), pos: new Vector3(), scl: new Vector3(), col: new Color() }),
    [],
  );

  useFrame(({ camera, clock }) => {
    const mesh = ref.current;
    if (!mesh) return;
    mesh.count = pulses.length;
    const t = clock.elapsedTime;
    const { mat, pos, scl, col } = scratch;
    for (let i = 0; i < pulses.length; i++) {
      const p = pulses[i];
      const frac = pulseFrac(t, p.phase);
      pos.set(
        p.a[0] + (p.b[0] - p.a[0]) * frac,
        p.a[1] + (p.b[1] - p.a[1]) * frac,
        p.a[2] + (p.b[2] - p.a[2]) * frac,
      );
      scl.setScalar(PULSE_SIZE);
      mat.compose(pos, camera.quaternion, scl);
      mesh.setMatrixAt(i, mat);
      // mesh links glow amber, association pulses ride the phosphor accent.
      col.copy(p.kind === "mesh" ? colors.amber : colors.phosphor).multiplyScalar(p.intensity);
      mesh.setColorAt(i, col);
    }
    mesh.instanceMatrix.needsUpdate = true;
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
  });

  return (
    <instancedMesh
      ref={ref}
      args={[undefined, undefined, PULSE_LIMIT]}
      frustumCulled={false}
      raycast={() => null}
      renderOrder={renderOrder}
    >
      <planeGeometry args={[1, 1]} />
      <meshBasicMaterial
        map={texture}
        transparent
        depthWrite={false}
        toneMapped={false}
        blending={AdditiveBlending}
      />
    </instancedMesh>
  );
}
