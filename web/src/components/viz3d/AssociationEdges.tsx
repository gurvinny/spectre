/**
 * Client→AP association edges — the RF topology the 2D radar can't show. One
 * instanced line-segment batch. Author: gurvinny
 */
"use client";

import { useMemo } from "react";
import { Segment, Segments } from "@react-three/drei";
import type { Line2 } from "three-stdlib";
import type { Vec3 } from "@/lib/viz3d/layout";
import type { EdgeModel } from "@/lib/viz3d/types";
import { useThemeColors3d } from "@/hooks/viz3d/useThemeColors3d";

const LIMIT = 128;

export function AssociationEdges({
  edges,
  posById,
  renderOrder = 0,
}: {
  edges: EdgeModel[];
  posById: Map<string, Vec3>;
  renderOrder?: number;
}) {
  const colors = useThemeColors3d();
  // Dimmed base line so future travelling pulses read as the live signal.
  const lineColor = useMemo(
    () => colors.phosphor.clone().lerp(colors.bg, 0.35),
    [colors],
  );
  const drawable = useMemo(
    () =>
      edges
        .map((e) => ({ e, a: posById.get(e.from), b: posById.get(e.to) }))
        .filter((x) => x.a && x.b)
        .slice(0, LIMIT),
    [edges, posById],
  );

  if (!drawable.length) return null;

  return (
    <Segments
      // drei <Segments> doesn't forward renderOrder — set it on the Line2 root.
      ref={(obj: Line2 | null) => {
        if (obj) obj.renderOrder = renderOrder;
      }}
      limit={LIMIT}
      lineWidth={0.6}
      transparent
    >
      {drawable.map(({ e, a, b }) => (
        <Segment
          key={`${e.from}-${e.to}`}
          start={a as Vec3}
          end={b as Vec3}
          color={lineColor}
        />
      ))}
    </Segments>
  );
}
