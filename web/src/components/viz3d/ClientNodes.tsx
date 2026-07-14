/**
 * Client (station) nodes as dual-shell holographic crystals — an outer
 * octahedral wireframe (the pickable shell) around a small translucent core.
 * Smaller than APs, colored by band, dimmed by staleness. Capped upstream in
 * the model. Author: gurvinny
 */
"use client";

import { useMemo } from "react";
import { Instance, Instances } from "@react-three/drei";
import { Color } from "three";
import type { ClientNode, SelectedNode } from "@/lib/viz3d/types";
import { ageOpacity } from "@/lib/viz3d/aging";
import { useThemeColors3d, bandColor3d } from "@/hooks/viz3d/useThemeColors3d";

const LIMIT = 64;

export function ClientNodes({
  nodes,
  onSelect,
}: {
  nodes: ClientNode[];
  onSelect: (n: SelectedNode) => void;
}) {
  const colors = useThemeColors3d();
  const now = Date.now() / 1000;
  const shown = nodes.length > LIMIT ? nodes.slice(0, LIMIT) : nodes;
  const tmp = useMemo(() => new Color(), []);

  // One mapping loop drives both instanced batches so shell and core stay in sync.
  const drawn = shown.map((n) => {
    const opacity = ageOpacity(n.lastSeen, now);
    // Outer wireframe: band accent; randomised MACs read as cooler/anonymous —
    // nudge toward ink-mute. Age-faded toward the background.
    tmp.copy(bandColor3d(colors, n.band));
    if (n.random) tmp.lerp(colors.inkMute, 0.4);
    tmp.lerp(colors.bg, 1 - opacity);
    const shellColor = tmp.clone();
    // Inner core: dimmer translucent volume in the band hue.
    tmp.copy(bandColor3d(colors, n.band));
    tmp.lerp(colors.phosphorDim, 0.5);
    tmp.lerp(colors.bg, 1 - opacity);
    const coreColor = tmp.clone();
    return { n, shellColor, coreColor };
  });

  return (
    <>
      {/* Inner solid core — translucent volume, decorative only. */}
      <Instances
        limit={LIMIT}
        range={drawn.length}
        frustumCulled={false}
        raycast={() => null}
      >
        <octahedronGeometry args={[0.1, 0]} />
        <meshBasicMaterial
          transparent
          opacity={0.32}
          depthWrite={false}
          toneMapped={false}
        />
        {drawn.map(({ n, coreColor }) => (
          <Instance key={n.id} position={n.pos} color={coreColor} />
        ))}
      </Instances>

      {/* Outer wireframe shell — the pickable target. */}
      <Instances limit={LIMIT} range={drawn.length} frustumCulled={false}>
        <octahedronGeometry args={[0.16, 0]} />
        <meshBasicMaterial wireframe transparent opacity={0.72} toneMapped={false} />
        {drawn.map(({ n, shellColor }) => (
          <Instance
            key={n.id}
            position={n.pos}
            color={shellColor}
            onClick={(e) => {
              e.stopPropagation();
              onSelect({ kind: "client", ...n });
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
