/**
 * Faint ground grid for spatial anchoring. Uses three's gridHelper (plain lines)
 * rather than drei's <Grid> — its analytic shader is far too heavy for software
 * WebGL on low-end/GPU-less clients. Author: gurvinny
 */
"use client";

import { useThemeColors3d } from "@/hooks/viz3d/useThemeColors3d";
import { R_MAX } from "@/lib/viz3d/layout";

const SIZE = R_MAX * 4;
const DIVISIONS = 24;

export function SceneGrid() {
  const colors = useThemeColors3d();
  return (
    <gridHelper
      position={[0, -0.02, 0]}
      args={[SIZE, DIVISIONS, colors.line, colors.grid]}
    />
  );
}
