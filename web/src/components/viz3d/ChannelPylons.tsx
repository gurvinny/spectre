/**
 * Per-channel activity pylons standing around the rim — the 3D fold-in of the
 * spectrum analyzer's channel occupancy. One instanced mesh; heights track the
 * live per-channel frame counts. Author: gurvinny
 */
"use client";

import { useMemo } from "react";
import { Instance, Instances } from "@react-three/drei";
import { AdditiveBlending, Color } from "three";
import { R_MAX, H_MAX } from "@/lib/viz3d/layout";
import { is24 } from "@/lib/format";
import { useThemeColors3d } from "@/hooks/viz3d/useThemeColors3d";

const LIMIT = 64;
const RIM = R_MAX * 1.12;

/** Ground azimuth for a channel: 2.4 GHz spread across the left hemisphere,
 *  5 GHz across the right, matching the AP band sectors. */
function channelAzimuth(ch: number): number {
  const span = Math.PI * 0.9;
  if (is24(ch)) {
    const frac = Math.min(1, Math.max(0, (ch - 1) / 13));
    return Math.PI / 2 - span / 2 + frac * span;
  }
  const frac = Math.min(1, Math.max(0, (ch - 36) / (165 - 36)));
  return -Math.PI / 2 - span / 2 + frac * span;
}

export function ChannelPylons({
  activity,
  renderOrder = 0,
}: {
  activity: Record<string, number>;
  renderOrder?: number;
}) {
  const colors = useThemeColors3d();
  const tmp = useMemo(() => new Color(), []);
  const pylons = useMemo(() => {
    const entries = Object.entries(activity).filter(([, n]) => n > 0);
    const max = Math.max(1, ...entries.map(([, n]) => n));
    return entries.map(([k, n]) => {
      const ch = Number(k);
      const az = channelAzimuth(ch);
      const h = 0.4 + (Math.log10(n + 1) / Math.log10(max + 1)) * H_MAX * 0.9;
      return {
        ch,
        h,
        pos: [Math.cos(az) * RIM, h / 2, Math.sin(az) * RIM] as [number, number, number],
        band: is24(ch) ? "2.4" : "5",
        intensity: n / max,
      };
    });
  }, [activity]);

  if (!pylons.length) return null;

  return (
    <Instances
      limit={LIMIT}
      range={Math.min(pylons.length, LIMIT)}
      frustumCulled={false}
      renderOrder={renderOrder}
    >
      {/* Open-ended glass columns — additive so overlapping pylons glow. */}
      <cylinderGeometry args={[0.09, 0.09, 1, 6, 1, true]} />
      <meshBasicMaterial
        transparent
        opacity={0.38}
        depthWrite={false}
        toneMapped={false}
        blending={AdditiveBlending}
      />
      {pylons.slice(0, LIMIT).map((p) => {
        tmp.copy(p.band === "5" ? colors.violet : colors.phosphor);
        tmp.lerp(colors.amber, p.intensity * 0.5);
        return (
          <Instance
            key={p.ch}
            position={p.pos}
            scale={[1, p.h, 1]}
            color={tmp.clone()}
          />
        );
      })}
    </Instances>
  );
}
