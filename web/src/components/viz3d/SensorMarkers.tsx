/**
 * Sensor "instrument" markers — one per configured board at the funnel apex,
 * rendered as a wireframe/solid octahedron with an additive halo. A board pulses
 * at its live fps (a hot sensor beats faster) and flips to the alert color when
 * offline. Beneath the pair, a Wazuh ring reflects SIEM-forwarding health: it
 * brightens when the sent count climbs and turns alert on failures. Fixed
 * positions — instruments, not data. No in-scene text. Author: gurvinny
 */
"use client";

import { useEffect, useMemo, useRef } from "react";
import { useFrame } from "@react-three/fiber";
import {
  AdditiveBlending,
  Color,
  Mesh,
  MeshBasicMaterial,
} from "three";
import { SENSOR_TOP } from "@/lib/viz3d/layout";
import type { Sensor, WazuhStatus } from "@/lib/types";
import { getHaloTexture } from "@/lib/viz3d/textures";
import { useThemeColors3d } from "@/hooks/viz3d/useThemeColors3d";
import { useQuality, useContinuousMotion } from "./QualityProvider";

// Both boards sit together above the coverage area — anchor them
// side by side at the funnel apex so the scene reads "sensor on top".
function markerPos(band: string): [number, number, number] {
  return band.startsWith("5") ? [0.7, SENSOR_TOP, 0] : [-0.7, SENSOR_TOP, 0];
}

export function SensorMarkers({
  sensors,
  wazuh,
}: {
  sensors: Sensor[];
  wazuh: WazuhStatus | null;
}) {
  const colors = useThemeColors3d();
  const { flags } = useQuality();
  const anyOnline = sensors.some((s) => s.online);
  // Keep the demand loop alive while any board is pulsing or the ring rotates.
  useContinuousMotion(flags.sensorPulse && (anyOnline || !!wazuh?.enabled));

  return (
    <>
      {sensors.map((s) => (
        <SensorMarker key={s.sensor} sensor={s} colors={colors} pulse={flags.sensorPulse} />
      ))}
      {wazuh && <WazuhRing wazuh={wazuh} colors={colors} rotate={flags.sensorPulse} />}
    </>
  );
}

function SensorMarker({
  sensor,
  colors,
  pulse,
}: {
  sensor: Sensor;
  colors: ReturnType<typeof useThemeColors3d>;
  pulse: boolean;
}) {
  const coreRef = useRef<Mesh>(null);
  const haloRef = useRef<Mesh>(null);
  const texture = useMemo(() => getHaloTexture(), []);
  const pos = markerPos(sensor.band);
  const online = sensor.online;
  const col = online ? colors.phosphor : colors.alert;

  useFrame(({ camera, clock }) => {
    if (haloRef.current) haloRef.current.quaternion.copy(camera.quaternion);
    const core = coreRef.current;
    if (!core) return;
    if (pulse && online) {
      // Hot board → shorter period. fps→period clamped to a readable range.
      const period = Math.max(0.5, Math.min(3, 60 / Math.max(sensor.fps, 4)));
      core.scale.setScalar(1 + 0.15 * Math.sin((clock.elapsedTime * Math.PI * 2) / period));
    } else {
      core.scale.setScalar(1);
    }
  });

  return (
    <group position={pos}>
      {/* additive halo bloom */}
      <mesh ref={haloRef} raycast={() => null} renderOrder={3}>
        <planeGeometry args={[1.4, 1.4]} />
        <meshBasicMaterial
          map={texture}
          color={col}
          transparent
          opacity={online ? 0.5 : 0.25}
          depthWrite={false}
          toneMapped={false}
          blending={AdditiveBlending}
        />
      </mesh>
      {/* solid core (pulses) */}
      <mesh ref={coreRef} raycast={() => null}>
        <octahedronGeometry args={[0.26, 0]} />
        <meshBasicMaterial color={col} transparent opacity={0.6} toneMapped={false} />
      </mesh>
      {/* wireframe shell */}
      <mesh raycast={() => null}>
        <octahedronGeometry args={[0.42, 0]} />
        <meshBasicMaterial color={col} wireframe transparent opacity={0.85} toneMapped={false} />
      </mesh>
    </group>
  );
}

const RING_Y = SENSOR_TOP - 0.75;

function WazuhRing({
  wazuh,
  colors,
  rotate,
}: {
  wazuh: WazuhStatus;
  colors: ReturnType<typeof useThemeColors3d>;
  rotate: boolean;
}) {
  const ref = useRef<Mesh>(null);
  const matRef = useRef<MeshBasicMaterial>(null);
  const prevSent = useRef(wazuh.sent);
  const bumpAt = useRef(0);
  const scratch = useMemo(() => new Color(), []);

  // Note when the forwarded count climbs so we can flash the ring brighter.
  useEffect(() => {
    if (wazuh.sent > prevSent.current) bumpAt.current = Date.now() / 1000;
    prevSent.current = wazuh.sent;
  }, [wazuh.sent]);

  // Target color/intensity by SIEM health.
  const unhealthy = wazuh.failures > 0 || !!wazuh.last_error;
  const base = !wazuh.enabled
    ? { color: colors.inkMute, op: 0.15 }
    : unhealthy
      ? { color: colors.alert, op: 0.5 }
      : { color: colors.phosphor, op: 0.35 };

  useFrame(({ clock }) => {
    if (rotate && ref.current) ref.current.rotation.z += 0.003;
    const mat = matRef.current;
    if (!mat) return;
    const bright =
      wazuh.enabled && !unhealthy && Date.now() / 1000 - bumpAt.current < 5 ? 0.6 : base.op;
    scratch.copy(base.color);
    mat.color.copy(scratch);
    mat.opacity = bright;
    // subtle idle shimmer only when healthy + rotating
    if (rotate && wazuh.enabled && !unhealthy) {
      mat.opacity = bright + 0.05 * Math.sin(clock.elapsedTime * 2);
    }
  });

  return (
    <mesh ref={ref} position={[0, RING_Y, 0]} rotation={[-Math.PI / 2, 0, 0]} raycast={() => null}>
      <ringGeometry args={[0.55, 0.62, 40]} />
      <meshBasicMaterial
        ref={matRef}
        color={base.color}
        transparent
        opacity={base.op}
        depthWrite={false}
        toneMapped={false}
        blending={AdditiveBlending}
      />
    </mesh>
  );
}
