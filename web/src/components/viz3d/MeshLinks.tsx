/**
 * Mesh/SSID backbone links — AP↔AP lines between BSSIDs that share one SSID
 * (dual-band radios + roaming mesh satellites), so a network reads
 * as one system distinct from its neighbours. Thicker/amber vs the thin phosphor
 * client-association edges. Author: gurvinny
 */
"use client";

import { useMemo } from "react";
import { Segment, Segments } from "@react-three/drei";
import type { Line2 } from "three-stdlib";
import type { Vec3 } from "@/lib/viz3d/layout";
import type { EdgeModel } from "@/lib/viz3d/types";
import { useThemeColors3d } from "@/hooks/viz3d/useThemeColors3d";

const LIMIT = 96;

export function MeshLinks({
  links,
  posById,
  renderOrder = 0,
}: {
  links: EdgeModel[];
  posById: Map<string, Vec3>;
  renderOrder?: number;
}) {
  const colors = useThemeColors3d();
  const drawable = useMemo(
    () =>
      links
        .map((e) => ({ e, a: posById.get(e.from), b: posById.get(e.to) }))
        .filter((x) => x.a && x.b)
        .slice(0, LIMIT),
    [links, posById],
  );

  if (!drawable.length) return null;

  return (
    <Segments
      // drei <Segments> doesn't forward renderOrder — set it on the Line2 root.
      ref={(obj: Line2 | null) => {
        if (obj) obj.renderOrder = renderOrder;
      }}
      limit={LIMIT}
      lineWidth={1.1}
      transparent
    >
      {drawable.map(({ e, a, b }) => (
        <Segment
          key={`${e.from}~${e.to}`}
          start={a as Vec3}
          end={b as Vec3}
          color={colors.amber}
        />
      ))}
    </Segments>
  );
}
