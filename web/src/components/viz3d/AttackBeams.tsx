/**
 * Directed attack vectors, styled by rule so an operator can read the attack at
 * a glance: a deauth flood strobes a red dashed beam attacker→victim; an evil
 * twin draws a violet beam doubled by an amber "impostor" ghost line rogue→legit.
 * Transient and threat-critical, so they run at every quality tier with the same
 * self-terminating invalidate() as ThreatFx (at the low tier the travelling head
 * parks near the target with an arrowhead so direction still reads without
 * animation). Author: gurvinny
 */
"use client";

import { useMemo, useRef } from "react";
import { useFrame, useThree } from "@react-three/fiber";
import {
  AdditiveBlending,
  Mesh,
  MeshBasicMaterial,
  Quaternion,
  Vector3,
} from "three";
import { Line } from "@react-three/drei";
import type { Vec3 } from "@/lib/viz3d/layout";
import type { AttackBeam } from "@/lib/viz3d/types";
import { useThemeColors3d } from "@/hooks/viz3d/useThemeColors3d";
import { useQuality } from "./QualityProvider";

const LIFETIME_S = 4;
const UP = new Vector3(0, 1, 0);

/** Perpendicular offset for the evil-twin ghost line. */
function ghostOffset(a: Vec3, b: Vec3): Vec3 {
  const dir = new Vector3(b[0] - a[0], b[1] - a[1], b[2] - a[2]).normalize();
  const perp = new Vector3().crossVectors(dir, UP).normalize().multiplyScalar(0.09);
  // If the beam is near-vertical, cross with UP degenerates — fall back to x.
  if (!isFinite(perp.x) || perp.lengthSq() < 1e-6) perp.set(0.09, 0, 0);
  return [perp.x, perp.y, perp.z];
}

export function AttackBeams({
  beams,
  posById,
}: {
  beams: AttackBeam[];
  posById: Map<string, Vec3>;
}) {
  const { tier } = useQuality();
  const colors = useThemeColors3d();
  const animate = tier !== "low";

  const resolved = beams
    .map((b) => ({ b, from: posById.get(b.fromId), to: posById.get(b.toId) }))
    .filter((x): x is { b: AttackBeam; from: Vec3; to: Vec3 } => !!x.from && !!x.to);

  return (
    <>
      {resolved.map(({ b, from, to }) => (
        <Beam
          key={b.id}
          beam={b}
          from={from}
          to={to}
          animate={animate}
          alert={`#${colors.alert.getHexString()}`}
          violet={`#${colors.violet.getHexString()}`}
          amber={`#${colors.amber.getHexString()}`}
        />
      ))}
    </>
  );
}

function Beam({
  beam,
  from,
  to,
  animate,
  alert,
  violet,
  amber,
}: {
  beam: AttackBeam;
  from: Vec3;
  to: Vec3;
  animate: boolean;
  alert: string;
  violet: string;
  amber: string;
}) {
  const invalidate = useThree((s) => s.invalidate);
  const headRef = useRef<Mesh>(null);
  const headMatRef = useRef<MeshBasicMaterial>(null);
  // drei Line forwards a Line2 (has a .material); typed loosely to fade opacity.
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const coreRef = useRef<any>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const ghostRef = useRef<any>(null);

  const deauth = beam.rule === "deauth_flood";
  const color = deauth ? alert : violet;
  const traverse = deauth ? 0.5 : 1.6; // seconds head takes to cross the beam

  const ghostPts = useMemo<[Vec3, Vec3]>(() => {
    const o = ghostOffset(from, to);
    return [
      [from[0] + o[0], from[1] + o[1], from[2] + o[2]],
      [to[0] + o[0], to[1] + o[1], to[2] + o[2]],
    ];
  }, [from, to]);

  // Static arrowhead orientation (low tier) — cone points along the beam.
  const headQuat = useMemo(() => {
    const dir = new Vector3(to[0] - from[0], to[1] - from[1], to[2] - from[2]).normalize();
    return new Quaternion().setFromUnitVectors(UP, dir);
  }, [from, to]);

  useFrame(() => {
    const now = Date.now() / 1000;
    const t = (now - beam.ts) / LIFETIME_S;
    if (t >= 1) {
      if (headRef.current) headRef.current.visible = false;
      return; // expired — stop requesting frames
    }
    const fade = 1 - t;
    const frac = animate ? ((now - beam.ts) / traverse) % 1 : 0.7;

    const head = headRef.current;
    if (head) {
      head.visible = true;
      head.position.set(
        from[0] + (to[0] - from[0]) * frac,
        from[1] + (to[1] - from[1]) * frac,
        from[2] + (to[2] - from[2]) * frac,
      );
      if (headMatRef.current) headMatRef.current.opacity = fade;
    }
    if (coreRef.current?.material) coreRef.current.material.opacity = fade * 0.9;
    if (ghostRef.current?.material) ghostRef.current.material.opacity = fade * 0.6;
    invalidate();
  });

  return (
    <>
      <Line
        ref={coreRef}
        points={[from, to]}
        color={color}
        lineWidth={deauth ? 2 : 1.5}
        dashed={deauth}
        dashSize={0.35}
        gapSize={0.2}
        transparent
        opacity={0.9}
        renderOrder={6}
      />
      {!deauth && (
        <Line
          ref={ghostRef}
          points={ghostPts}
          color={amber}
          lineWidth={1}
          transparent
          opacity={0.6}
          renderOrder={6}
        />
      )}
      {/* travelling head (animated tiers) / parked arrowhead (low tier) */}
      <mesh
        ref={headRef}
        quaternion={animate ? undefined : headQuat}
        raycast={() => null}
        renderOrder={6}
      >
        {animate ? (
          <octahedronGeometry args={[0.13, 0]} />
        ) : (
          <coneGeometry args={[0.12, 0.3, 8]} />
        )}
        <meshBasicMaterial
          ref={headMatRef}
          color={color}
          transparent
          opacity={0.9}
          depthWrite={false}
          toneMapped={false}
          blending={AdditiveBlending}
        />
      </mesh>
    </>
  );
}
