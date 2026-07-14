/**
 * Access-point nodes as dual-shell holographic crystals — an outer icosahedral
 * wireframe (the pickable shell) around a translucent solid core. Two instanced
 * batches (two draw calls), scaled by beacon rate, colored by band, faded toward
 * the background as a node goes stale. Author: gurvinny
 */
"use client";

import { useMemo } from "react";
import { Instance, Instances } from "@react-three/drei";
import { Color } from "three";
import type { ApNode, SelectedNode } from "@/lib/viz3d/types";
import { ageOpacity } from "@/lib/viz3d/aging";
import { useThemeColors3d, bandColor3d } from "@/hooks/viz3d/useThemeColors3d";

const LIMIT = 256;

function apScale(beacons: number): number {
  return 0.55 + Math.min(0.65, Math.log10(beacons + 1) * 0.3);
}

export function ApNodes({
  nodes,
  onSelect,
}: {
  nodes: ApNode[];
  onSelect: (n: SelectedNode) => void;
}) {
  const colors = useThemeColors3d();
  const now = Date.now() / 1000;
  const shown = nodes.length > LIMIT ? nodes.slice(0, LIMIT) : nodes;

  // Reused scratch color to avoid per-node allocation churn.
  const tmp = useMemo(() => new Color(), []);

  // One mapping loop drives both instanced batches so the shell and core can
  // never drift out of sync on position/scale/age.
  const drawn = shown.map((n) => {
    const opacity = ageOpacity(n.lastSeen, now);
    const scale = apScale(n.beacons);
    // Outer wireframe: band accent, nudged toward phosphor when known, age-faded.
    tmp.copy(bandColor3d(colors, n.band));
    if (n.known) tmp.lerp(colors.phosphor, 0.15);
    tmp.lerp(colors.bg, 1 - opacity);
    const shellColor = tmp.clone();
    // Inner core: dimmer translucent volume in the band hue.
    tmp.copy(bandColor3d(colors, n.band));
    tmp.lerp(colors.phosphorDim, 0.5);
    tmp.lerp(colors.bg, 1 - opacity);
    const coreColor = tmp.clone();
    return { n, scale, shellColor, coreColor };
  });

  return (
    <>
      {/* Inner solid core — translucent volume, not additive. Decorative only:
          never raycast so picking stays on the outer shell. */}
      <Instances
        limit={LIMIT}
        range={drawn.length}
        frustumCulled={false}
        raycast={() => null}
      >
        <icosahedronGeometry args={[0.26, 0]} />
        <meshBasicMaterial
          transparent
          opacity={0.22}
          depthWrite={false}
          toneMapped={false}
        />
        {drawn.map(({ n, scale, coreColor }) => (
          <Instance key={n.id} position={n.pos} scale={scale} color={coreColor} />
        ))}
      </Instances>

      {/* Outer wireframe shell — the pickable target. */}
      <Instances limit={LIMIT} range={drawn.length} frustumCulled={false}>
        <icosahedronGeometry args={[0.4, 0]} />
        <meshBasicMaterial wireframe transparent opacity={0.72} toneMapped={false} />
        {drawn.map(({ n, scale, shellColor }) => (
          <Instance
            key={n.id}
            position={n.pos}
            scale={scale}
            color={shellColor}
            onClick={(e) => {
              e.stopPropagation();
              onSelect({ kind: "ap", ...n });
            }}
            onPointerOver={(e) => {
              e.stopPropagation();
              document.body.style.cursor = "pointer";
            }}
            onPointerOut={() => {
              document.body.style.cursor = "";
            }}
          />
        ))}
      </Instances>
    </>
  );
}
