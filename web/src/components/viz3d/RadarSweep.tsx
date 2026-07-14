/**
 * Rotating radar-sweep centerpiece for the RF battlespace: a faint vertical
 * phosphor blade sweeping the funnel, a vertex-color trail wedge fading behind
 * it, and analytic node flares that ping each node as the blade passes its
 * azimuth. One useFrame owns the angle accumulator so blade, trail and flares
 * can never drift apart; brightness is encoded by dimming colors toward black
 * (additive layers never share per-instance opacity). Gated on the quality
 * tier's sweep flag so low/PERF pays nothing. Kept deliberately subtle.
 * Author: gurvinny
 */
"use client";

import { useEffect, useMemo, useRef } from "react";
import { useFrame } from "@react-three/fiber";
import {
  AdditiveBlending,
  BufferGeometry,
  Color,
  DoubleSide,
  Float32BufferAttribute,
  Group,
  InstancedMesh,
  Matrix4,
  Vector3,
} from "three";
import type { ApNode, ClientNode } from "@/lib/viz3d/types";
import { R_MAX, SENSOR_TOP, shellHeight } from "@/lib/viz3d/layout";
import { ageOpacity } from "@/lib/viz3d/aging";
import { getHaloTexture } from "@/lib/viz3d/textures";
import { useThemeColors3d, bandColor3d } from "@/hooks/viz3d/useThemeColors3d";
import { useQuality, useContinuousMotion } from "./QualityProvider";

const TAU = Math.PI * 2;
/** The weakest-signal shell height — the floor of the funnel. */
const FLOOR_Y = shellHeight(0);
/** Blade reach: just inside the outermost shell so it never pokes the rings. */
const BLADE_W = R_MAX * 0.95;
const BLADE_H = SENSOR_TOP - FLOOR_Y;
const BLADE_Y = (SENSOR_TOP + FLOOR_Y) / 2;
/** Additive brightness of the leading blade. Barely-there by design. */
const BLADE_OPACITY = 0.08;

/** Trail wedge: discrete vertical slices fading to black behind the blade. */
const TRAIL_SLICES = 15;
const TRAIL_ARC = (42 * Math.PI) / 180;
/** Peak trail intensity at the blade edge (dims toward black at the tail). */
const TRAIL_DIM = 0.3;

/** Angular window (radians) behind the blade in which a node flares. */
const FLARE_WIDTH = 0.5;
const FLARE_LIMIT = 160;
/** Flare billboard sizes — a touch larger than the node visuals. */
const FLARE_SIZE_AP = 0.5;
const FLARE_SIZE_CLIENT = 0.38;

interface Flare {
  pos: [number, number, number];
  azimuth: number;
  color: Color; // band accent, cloned so per-frame math never mutates theme
  lastSeen: number;
  size: number;
}

export function RadarSweep({
  apNodes,
  clientNodes,
}: {
  apNodes: ApNode[];
  clientNodes: ClientNode[];
}) {
  const { flags } = useQuality();
  // Low/PERF tier (which already folds in reduced-motion): mount nothing.
  if (!flags.sweep) return null;
  return (
    <SweepSystem
      apNodes={apNodes}
      clientNodes={clientNodes}
      period={flags.sweepPeriod}
    />
  );
}

function SweepSystem({
  apNodes,
  clientNodes,
  period,
}: {
  apNodes: ApNode[];
  clientNodes: ClientNode[];
  period: number;
}) {
  useContinuousMotion(true); // this subtree only mounts while the sweep runs

  const colors = useThemeColors3d();
  const texture = useMemo(() => getHaloTexture(), []);

  const angleRef = useRef(0);
  const groupRef = useRef<Group>(null);
  const flareRef = useRef<InstancedMesh>(null);

  // Trail wedge: TRAIL_SLICES vertical quads (axis → rim) at local azimuths
  // behind the blade (the group spins so local −φ trails the local-0 blade),
  // vertex colors fading quadratically from dim phosphor to black.
  const trailGeometry = useMemo(() => {
    const positions: number[] = [];
    const vertexColors: number[] = [];
    const index: number[] = [];
    const c = new Color();
    for (let i = 0; i < TRAIL_SLICES; i++) {
      const frac = (i + 0.5) / TRAIL_SLICES; // 0 at blade edge → 1 at tail
      const phi = -TRAIL_ARC * frac;
      const x = BLADE_W * Math.cos(phi);
      const z = BLADE_W * Math.sin(phi);
      // Quad: inner-bottom, outer-bottom, outer-top, inner-top.
      positions.push(0, FLOOR_Y, 0, x, FLOOR_Y, z, x, SENSOR_TOP, z, 0, SENSOR_TOP, 0);
      const t = 1 - frac;
      c.copy(colors.phosphor).multiplyScalar(TRAIL_DIM * t * t);
      for (let v = 0; v < 4; v++) vertexColors.push(c.r, c.g, c.b);
      const b = i * 4;
      index.push(b, b + 1, b + 2, b, b + 2, b + 3);
    }
    const geo = new BufferGeometry();
    geo.setAttribute("position", new Float32BufferAttribute(positions, 3));
    geo.setAttribute("color", new Float32BufferAttribute(vertexColors, 3));
    geo.setIndex(index);
    return geo;
  }, [colors.phosphor]);
  useEffect(() => () => trailGeometry.dispose(), [trailGeometry]);

  // Flare roster — APs first; if the cap bites, keep the freshest clients.
  const flares = useMemo<Flare[]>(() => {
    const out: Flare[] = [];
    for (const n of apNodes) {
      if (out.length >= FLARE_LIMIT) break;
      out.push({
        pos: n.pos,
        azimuth: n.azimuth,
        color: bandColor3d(colors, n.band).clone(),
        lastSeen: n.lastSeen,
        size: FLARE_SIZE_AP,
      });
    }
    const clients =
      out.length + clientNodes.length > FLARE_LIMIT
        ? [...clientNodes].sort((a, b) => b.lastSeen - a.lastSeen)
        : clientNodes;
    for (const n of clients) {
      if (out.length >= FLARE_LIMIT) break;
      out.push({
        pos: n.pos,
        azimuth: n.azimuth,
        color: bandColor3d(colors, n.band).clone(),
        lastSeen: n.lastSeen,
        size: FLARE_SIZE_CLIENT,
      });
    }
    return out;
  }, [apNodes, clientNodes, colors]);

  // Scratch objects — no per-frame allocation.
  const scratch = useMemo(
    () => ({
      mat: new Matrix4(),
      pos: new Vector3(),
      scl: new Vector3(),
      col: new Color(),
    }),
    [],
  );

  // The single loop: advance the angle, spin the blade group, and light the
  // flares analytically from the SAME angle so nothing can drift out of sync.
  // The MotionDriver owns invalidate(); this only mutates objects.
  useFrame(({ camera }, delta) => {
    if (period > 0) {
      angleRef.current = (angleRef.current + delta * (TAU / period)) % TAU;
    }
    const angle = angleRef.current;

    // rotation.y = −angle maps the local +x blade to world azimuth `angle`
    // (layout azimuth runs +x → +z, opposite the y-rotation handedness).
    if (groupRef.current) groupRef.current.rotation.y = -angle;

    const mesh = flareRef.current;
    if (!mesh) return;
    mesh.count = flares.length;
    const now = Date.now() / 1000;
    const { mat, pos, scl, col } = scratch;
    for (let i = 0; i < flares.length; i++) {
      const f = flares[i];
      // Forward-only angular distance since the blade passed this node.
      let d = (angle - f.azimuth) % TAU;
      if (d < 0) d += TAU;
      let intensity = 0;
      if (d <= FLARE_WIDTH) {
        const t = 1 - d / FLARE_WIDTH;
        intensity = t * t * ageOpacity(f.lastSeen, now);
      }
      col.copy(f.color).multiplyScalar(intensity); // 0 → black → invisible
      mesh.setColorAt(i, col);
      pos.set(f.pos[0], f.pos[1], f.pos[2]);
      scl.setScalar(f.size);
      mat.compose(pos, camera.quaternion, scl);
      mesh.setMatrixAt(i, mat);
    }
    mesh.instanceMatrix.needsUpdate = true;
    if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
  });

  return (
    <>
      <group ref={groupRef}>
        {/* Leading blade: a faint vertical phosphor quad from axis to rim. */}
        <mesh
          position={[BLADE_W / 2, BLADE_Y, 0]}
          frustumCulled={false}
          raycast={() => null}
          renderOrder={5}
        >
          <planeGeometry args={[BLADE_W, BLADE_H]} />
          <meshBasicMaterial
            color={colors.phosphor}
            transparent
            opacity={BLADE_OPACITY}
            depthWrite={false}
            toneMapped={false}
            blending={AdditiveBlending}
            side={DoubleSide}
          />
        </mesh>
        {/* Trail wedge: vertex colors carry the fade, so no shared opacity. */}
        <mesh
          geometry={trailGeometry}
          frustumCulled={false}
          raycast={() => null}
          renderOrder={5}
        >
          <meshBasicMaterial
            vertexColors
            transparent
            depthWrite={false}
            toneMapped={false}
            blending={AdditiveBlending}
            side={DoubleSide}
          />
        </mesh>
      </group>

      {/* Sweep flares: camera-facing halo billboards lit analytically as the
          blade passes each node's azimuth. Same technique as NodeHalos. */}
      <instancedMesh
        ref={flareRef}
        args={[undefined, undefined, FLARE_LIMIT]}
        frustumCulled={false}
        raycast={() => null}
        renderOrder={4}
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
    </>
  );
}
