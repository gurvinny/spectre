/**
 * Additive billboard halos behind every node — a cheap "bloom" pass for
 * software WebGL. One raw InstancedMesh of camera-facing quads sharing a single
 * radial-gradient sprite; brightness is encoded per-instance by dimming the
 * band color toward black (additive layers must never use shared opacity for
 * per-node intensity). Purely decorative: never raycast, never invalidates.
 * Author: gurvinny
 */
"use client";

import { useEffect, useMemo, useRef } from "react";
import { useFrame, useThree } from "@react-three/fiber";
import {
  AdditiveBlending,
  Color,
  InstancedMesh,
  Matrix4,
  Vector3,
} from "three";
import type { ApNode, ClientNode } from "@/lib/viz3d/types";
import { ageOpacity } from "@/lib/viz3d/aging";
import { getHaloTexture } from "@/lib/viz3d/textures";
import { useThemeColors3d, bandColor3d } from "@/hooks/viz3d/useThemeColors3d";

const LIMIT = 160;
/** Halo diameter ≈ node visual radius × this factor. Kept tight/subtle. */
const HALO_FACTOR = 1.5;
/** Additive brightness of a halo (dimmed toward black by age). */
const HALO_DIM = 0.3;

/** Mirrors ApNodes' (smaller) outer-shell scale so the halo hugs the crystal. */
function apRadius(beacons: number): number {
  return 0.4 * (0.55 + Math.min(0.65, Math.log10(beacons + 1) * 0.3));
}

interface Halo {
  pos: [number, number, number];
  band: string;
  size: number;
  dim: number; // ageOpacity × 0.5 — additive brightness toward black
}

export function NodeHalos({
  apNodes,
  clientNodes,
  renderOrder = 0,
}: {
  apNodes: ApNode[];
  clientNodes: ClientNode[];
  renderOrder?: number;
}) {
  const ref = useRef<InstancedMesh>(null);
  const invalidate = useThree((s) => s.invalidate);
  const colors = useThemeColors3d();
  const texture = useMemo(() => getHaloTexture(), []);
  const tmp = useMemo(() => new Color(), []);

  // APs first; if the cap bites, keep the most recently seen clients.
  const halos = useMemo<Halo[]>(() => {
    const now = Date.now() / 1000;
    const out: Halo[] = [];
    for (const n of apNodes) {
      if (out.length >= LIMIT) break;
      out.push({
        pos: n.pos,
        band: n.band,
        size: apRadius(n.beacons) * HALO_FACTOR,
        dim: ageOpacity(n.lastSeen, now) * HALO_DIM,
      });
    }
    const clients =
      out.length + clientNodes.length > LIMIT
        ? [...clientNodes].sort((a, b) => b.lastSeen - a.lastSeen)
        : clientNodes;
    for (const n of clients) {
      if (out.length >= LIMIT) break;
      out.push({
        pos: n.pos,
        band: n.band,
        size: 0.16 * HALO_FACTOR,
        dim: ageOpacity(n.lastSeen, now) * HALO_DIM,
      });
    }
    return out;
  }, [apNodes, clientNodes]);

  // Per-instance color = band accent dimmed toward black by age.
  useEffect(() => {
    const mesh = ref.current;
    if (!mesh) return;
    for (let i = 0; i < halos.length; i++) {
      tmp.copy(bandColor3d(colors, halos[i].band)).multiplyScalar(halos[i].dim);
      mesh.setColorAt(i, tmp);
    }
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
    invalidate(); // repaint once so colors show without waiting on a live batch
  }, [halos, colors, tmp, invalidate]);

  // Scratch objects for the matrix loop — no per-frame allocation.
  const scratch = useMemo(
    () => ({ mat: new Matrix4(), pos: new Vector3(), scl: new Vector3() }),
    [],
  );

  // Passive billboarding: only writes matrices during frames that render for
  // other reasons (demand mode) — never calls invalidate(), so idle stays idle.
  useFrame(({ camera }) => {
    const mesh = ref.current;
    if (!mesh) return;
    mesh.count = halos.length;
    const { mat, pos, scl } = scratch;
    for (let i = 0; i < halos.length; i++) {
      const h = halos[i];
      pos.set(h.pos[0], h.pos[1], h.pos[2]);
      scl.setScalar(h.size);
      mat.compose(pos, camera.quaternion, scl);
      mesh.setMatrixAt(i, mat);
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
