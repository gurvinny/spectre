/**
 * Local scene-model types for the 3D RF battlespace. Deliberately kept out of the
 * shared `src/lib/types.ts` so nothing outside the /battlespace route imports the
 * 3D layer and breaks its dynamic-import (ssr:false) bundle isolation.
 * Author: gurvinny
 */
import type { Vec3 } from "@/lib/viz3d/layout";

export interface ApNode {
  id: string; // bssid (uppercased)
  pos: Vec3;
  azimuth: number; // cluster angle (radians) — used by the radar-sweep flare
  band: string;
  rssi: number | null;
  lastSeen: number; // epoch seconds
  beacons: number;
  known: boolean;
  ssid: string | null;
}

export interface ClientNode {
  id: string; // mac (uppercased)
  pos: Vec3;
  azimuth: number; // cluster angle (radians) — used by the radar-sweep flare
  band: string;
  rssi: number | null;
  lastSeen: number; // epoch seconds
  assocBssid: string | null;
  ssid: string | null;
  frames: number;
  random: boolean;
  /** max_rssi − min_rssi (dB) for inventory clients; null when unknown. */
  rssiSpread: number | null;
}

export interface EdgeModel {
  from: string; // client id (assoc) / hub bssid (mesh)
  to: string; // ap id (assoc) / member bssid (mesh)
  /** 0..1 recent-traffic heat for the data-flow pulses. */
  activity: number;
}

/** A directed attack vector derived from a threat's rule + detail. */
export interface AttackBeam {
  id: string; // stable per (rule+from+to+ts)
  fromId: string; // attacker node id (must be a visible node)
  toId: string; // target node id (must be a visible node)
  rule: string; // "deauth_flood" | "evil_twin"
  severity: string;
  ts: number; // epoch seconds
}

export interface ThreatFlash {
  id: string; // stable per (nodeId+ts)
  nodeId: string;
  severity: string;
  ts: number; // epoch seconds
}

export interface BattlespaceModel {
  apNodes: ApNode[];
  clientNodes: ClientNode[];
  edges: EdgeModel[];
  /** AP↔AP links between BSSIDs sharing one SSID (mesh / dual-band). */
  meshLinks: EdgeModel[];
  channelActivity: Record<string, number>;
  threatFlashes: ThreatFlash[];
  /** Directed attack vectors for the current threat window. */
  attackBeams: AttackBeam[];
}

/** Union used by the click-to-inspect HUD panel. */
export type SelectedNode =
  | ({ kind: "ap" } & ApNode)
  | ({ kind: "client" } & ClientNode);
