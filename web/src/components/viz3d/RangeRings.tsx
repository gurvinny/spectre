/**
 * Concentric RSSI range rings on the scene floor — the 3D echo of RadarPPI's
 * range rings — plus the elevated funnel-cage rings tracing the signal-strength
 * shells up toward the sensor apex, and a faint additive beam up the central
 * axis. Static geometry, built once. Author: gurvinny
 */
"use client";

import { useMemo } from "react";
import { Line } from "@react-three/drei";
import { AdditiveBlending } from "three";
import {
  R_MAX,
  SENSOR_TOP,
  shellRadius,
  shellHeight,
} from "@/lib/viz3d/layout";
import { useThemeColors3d } from "@/hooks/viz3d/useThemeColors3d";

const RING_FRACTIONS = [0.25, 0.5, 0.75, 1] as const;
/** Signal-strength shells traced by the elevated cage rings. */
const CAGE_STRENGTHS = [0.25, 0.5, 0.75] as const;
const SEGMENTS = 96;

function ringPoints(radius: number, y = 0): [number, number, number][] {
  const pts: [number, number, number][] = [];
  for (let i = 0; i <= SEGMENTS; i++) {
    const a = (i / SEGMENTS) * Math.PI * 2;
    pts.push([Math.cos(a) * radius, y, Math.sin(a) * radius]);
  }
  return pts;
}

export function RangeRings() {
  const colors = useThemeColors3d();
  const rings = useMemo(
    () => RING_FRACTIONS.map((f) => ringPoints(R_MAX * f)),
    [],
  );
  // Funnel cage: one ring per strength shell, at the exact radius/height nodes
  // of that strength occupy, so the cage reads as the coordinate system.
  const cage = useMemo(
    () => CAGE_STRENGTHS.map((s) => ringPoints(shellRadius(s), shellHeight(s))),
    [],
  );
  // Central axis beam: floor shell up to the sensor apex.
  const beam = useMemo(() => {
    const bottom = shellHeight(0);
    const span = SENSOR_TOP - bottom;
    return { span, mid: bottom + span / 2 };
  }, []);

  return (
    <group>
      {rings.map((pts, i) => (
        <Line
          key={i}
          points={pts}
          color={colors.grid}
          lineWidth={1}
          transparent
          opacity={0.45}
        />
      ))}
      {/* elevated signal-strength cage rings */}
      {cage.map((pts, i) => (
        <Line
          key={`cage-${i}`}
          points={pts}
          color={colors.grid}
          lineWidth={1}
          transparent
          opacity={0.14}
        />
      ))}
      {/* central axis beam up to the sensor apex */}
      <mesh position={[0, beam.mid, 0]} raycast={() => null}>
        <cylinderGeometry args={[0.02, 0.02, beam.span, 6, 1, true]} />
        <meshBasicMaterial
          color={colors.phosphor}
          transparent
          opacity={0.07}
          depthWrite={false}
          toneMapped={false}
          blending={AdditiveBlending}
        />
      </mesh>
      {/* central axis spokes for the two band hemispheres */}
      <Line
        points={[
          [-R_MAX, 0, 0],
          [R_MAX, 0, 0],
        ]}
        color={colors.line}
        lineWidth={1}
        transparent
        opacity={0.4}
      />
      <Line
        points={[
          [0, 0, -R_MAX],
          [0, 0, R_MAX],
        ]}
        color={colors.line}
        lineWidth={1}
        transparent
        opacity={0.4}
      />
    </group>
  );
}
