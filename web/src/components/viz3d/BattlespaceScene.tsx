/**
 * The in-canvas scene graph for the RF battlespace: lighting, fog, camera
 * controls and every data layer. Kept declarative so react-three-fiber's demand
 * renderer invalidates automatically when the model changes. Author: gurvinny
 */
"use client";

import { useMemo } from "react";
import type { Vec3 } from "@/lib/viz3d/layout";
import { R_MAX } from "@/lib/viz3d/layout";
import type { BattlespaceModel, SelectedNode } from "@/lib/viz3d/types";
import type { Sensor, WazuhStatus } from "@/lib/types";
import type { PerfMode, Tier } from "@/lib/viz3d/quality";
import { useThemeColors3d } from "@/hooks/viz3d/useThemeColors3d";
import { QualityProvider } from "./QualityProvider";
import { RangeRings } from "./RangeRings";
import { SceneGrid } from "./SceneGrid";
import { ApNodes } from "./ApNodes";
import { ClientNodes } from "./ClientNodes";
import { AssociationEdges } from "./AssociationEdges";
import { MeshLinks } from "./MeshLinks";
import { ChannelPylons } from "./ChannelPylons";
import { NodeHalos } from "./NodeHalos";
import { VolatilityHalos } from "./VolatilityHalos";
import { EdgeFlow } from "./EdgeFlow";
import { RadarSweep } from "./RadarSweep";
import { AttackBeams } from "./AttackBeams";
import { SceneControls } from "./SceneControls";
import { ThreatFx } from "./ThreatFx";
import { SensorMarkers } from "./SensorMarkers";

export function BattlespaceScene({
  model,
  sensors,
  wazuh,
  reducedMotion,
  mode,
  onTierChange,
  onSelect,
}: {
  model: BattlespaceModel;
  sensors: Sensor[];
  wazuh: WazuhStatus | null;
  reducedMotion: boolean;
  mode: PerfMode;
  onTierChange: (tier: Tier) => void;
  onSelect: (n: SelectedNode | null) => void;
}) {
  const colors = useThemeColors3d();
  const bg = `#${colors.bg.getHexString()}`;

  const posById = useMemo(() => {
    const m = new Map<string, Vec3>();
    for (const a of model.apNodes) m.set(a.id, a.pos);
    for (const c of model.clientNodes) m.set(c.id, c.pos);
    return m;
  }, [model.apNodes, model.clientNodes]);

  return (
    <QualityProvider
      mode={mode}
      reducedMotion={reducedMotion}
      onTierChange={onTierChange}
    >
      <color attach="background" args={[bg]} />
      <fog attach="fog" args={[bg, R_MAX * 1.5, R_MAX * 3.8]} />

      {/* Materials are unlit (meshBasicMaterial) for cheap software-WebGL
          rendering, so the scene needs no lights. */}

      {/* renderOrder ladder so additive transparency sorts predictably:
          0 solids/wireframe nodes + grid/rings · 1 pylons · (2 volatility
          rings reserved) · 3 node halos · 4 edges + sweep flares · 5 sweep
          blade/trail · 6 threat FX. */}
      <SceneGrid />
      <RangeRings />
      <ApNodes nodes={model.apNodes} onSelect={onSelect} />
      <ClientNodes nodes={model.clientNodes} onSelect={onSelect} />
      <ChannelPylons activity={model.channelActivity} renderOrder={1} />
      <VolatilityHalos clientNodes={model.clientNodes} renderOrder={2} />
      <NodeHalos
        apNodes={model.apNodes}
        clientNodes={model.clientNodes}
        renderOrder={3}
      />
      <RadarSweep apNodes={model.apNodes} clientNodes={model.clientNodes} />
      <MeshLinks links={model.meshLinks} posById={posById} renderOrder={4} />
      <AssociationEdges edges={model.edges} posById={posById} renderOrder={4} />
      <EdgeFlow
        edges={model.edges}
        meshLinks={model.meshLinks}
        posById={posById}
        renderOrder={4}
      />
      <SensorMarkers sensors={sensors} wazuh={wazuh} />
      <AttackBeams beams={model.attackBeams} posById={posById} />
      {!reducedMotion && <ThreatFx flashes={model.threatFlashes} posById={posById} />}

      <SceneControls />
    </QualityProvider>
  );
}
