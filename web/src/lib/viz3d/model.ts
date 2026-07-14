/**
 * Pure transform: SPECTRE's polled inventory + live frame/threat stream → the 3D
 * scene model (positioned nodes, association + mesh edges, channel activity,
 * threat flashes). Kept free of React so it can be reasoned about and unit-tested
 * in isolation; the hook in useBattlespaceModel just supplies `now` and memoises.
 *
 * Spatial model: nodes are clustered angularly by SSID (so every BSSID of one
 * network — e.g. a dual-band AP + its mesh satellites, all one SSID —
 * shares a sector), height/radius follow signal strength (sensor-on-top funnel).
 * Author: gurvinny
 */
import type { AccessPoint, Device, Frame, Threat } from "@/lib/types";
import { channelsFromFrames } from "@/lib/format";
import { positionFor, azimuthForGroup } from "@/lib/viz3d/layout";
import { isEvicted } from "@/lib/viz3d/aging";
import type {
  ApNode,
  AttackBeam,
  BattlespaceModel,
  ClientNode,
  EdgeModel,
  ThreatFlash,
} from "@/lib/viz3d/types";

const BROADCAST = "FF:FF:FF:FF:FF:FF";
export const CLIENT_CAP = 40;
const THREAT_FLASH_WINDOW_S = 8;
const BEAM_WINDOW_S = 10;
const BEAM_CAP = 8;
/** Max legit BSSIDs an evil-twin threat fans out to. */
const EVIL_TWIN_FANOUT = 3;
/** Frame types that imply a client is associated/talking to its BSSID. */
const ASSOC_TYPES = new Set([
  "DATA",
  "QOS_DATA",
  "ASSOC_REQ",
  "ASSOC_RESP",
  "REASSOC_REQ",
  "REASSOC_RESP",
  "AUTH",
  "ACTION",
]);

export interface ModelInputs {
  aps: AccessPoint[];
  devices: Device[];
  frames: Frame[];
  threats: Threat[];
}

const up = (s: string | null | undefined): string | null =>
  s ? s.toUpperCase() : null;

/** Normalise an SSID for grouping; hidden/blank names don't cluster. */
function normSsid(ssid: string | null | undefined): string | null {
  const s = (ssid ?? "").trim();
  if (!s || s === "?" || s === "<hidden>") return null;
  return s;
}

export function buildBattlespaceModel(
  { aps, devices, frames, threats }: ModelInputs,
  now: number,
): BattlespaceModel {
  // Which MACs are access points (inventory + any bssid seen live)?
  const bssidSet = new Set<string>();
  for (const a of aps) bssidSet.add(a.bssid.toUpperCase());
  for (const f of frames) {
    const b = up(f.bssid);
    if (b && b !== BROADCAST) bssidSet.add(b);
  }

  // Latest live signal per MAC + current client→AP associations, from the
  // rolling frame window (newest-first).
  const liveSeen = new Map<
    string,
    { ts: number; rssi: number | null; band: string; ch: number | null }
  >();
  const assoc = new Map<string, string>(); // client → bssid (latest wins)
  const pairCount = new Map<string, number>(); // `${mac}|${bssid}` → frames
  const bssidCount = new Map<string, number>(); // bssid → total frames
  for (const f of frames) {
    const note = (mac: string | null) => {
      if (!mac || mac === BROADCAST || liveSeen.has(mac)) return;
      liveSeen.set(mac, { ts: f.ts, rssi: f.rssi, band: f.band, ch: f.ch });
    };
    note(up(f.src));
    note(up(f.dst));
    note(up(f.bssid));

    const b = up(f.bssid);
    const client = up(f.src);
    if (
      b &&
      b !== BROADCAST &&
      client &&
      client !== b &&
      !bssidSet.has(client) &&
      ASSOC_TYPES.has(f.type) &&
      !assoc.has(client) // frames are newest-first, so first hit is latest
    ) {
      assoc.set(client, b);
    }

    // Traffic heat for the data-flow layer: count frames per (endpoint↔bssid)
    // pair (either direction) and per bssid.
    if (b && b !== BROADCAST) {
      bssidCount.set(b, (bssidCount.get(b) ?? 0) + 1);
      for (const end of [up(f.src), up(f.dst)]) {
        if (!end || end === BROADCAST || end === b) continue;
        const key = end + "|" + b;
        pairCount.set(key, (pairCount.get(key) ?? 0) + 1);
      }
    }
  }
  const maxPair = Math.max(1, ...pairCount.values());
  const maxBssid = Math.max(1, ...bssidCount.values());
  const normLog = (raw: number, max: number): number =>
    max <= 0 ? 0 : Math.log10(raw + 1) / Math.log10(max + 1);

  // AP nodes: authoritative inventory, then live-only bssids. Track each AP's
  // SSID and cluster group so clients/mesh links can align to it.
  const apNodes: ApNode[] = [];
  const apIds = new Set<string>();
  const apGroupKey = new Map<string, string>(); // bssid → SSID cluster (or self)
  const groupMembers = new Map<string, string[]>(); // SSID → bssids

  const addAp = (
    id: string,
    ssid: string | null,
    band: string,
    rssi: number | null,
    lastSeen: number,
    beacons: number,
    known: boolean,
  ) => {
    const grpSsid = normSsid(ssid);
    const groupKey = grpSsid ?? id;
    apIds.add(id);
    apGroupKey.set(id, groupKey);
    if (grpSsid) {
      const arr = groupMembers.get(grpSsid) ?? [];
      arr.push(id);
      groupMembers.set(grpSsid, arr);
    }
    apNodes.push({
      id,
      pos: positionFor(groupKey, id, rssi),
      azimuth: azimuthForGroup(groupKey, id),
      band,
      rssi,
      lastSeen,
      beacons,
      known,
      ssid,
    });
  };

  for (const a of aps) {
    const id = a.bssid.toUpperCase();
    const live = liveSeen.get(id);
    const lastSeen = Math.max(a.last_seen, live?.ts ?? 0);
    if (isEvicted(lastSeen, now)) continue;
    const band = a.band && a.band !== "unknown" ? a.band : live?.band ?? "2.4";
    addAp(id, a.ssid, band, live?.rssi ?? a.last_rssi, lastSeen, a.beacons, !!a.is_known);
  }
  for (const [id, live] of liveSeen) {
    if (apIds.has(id) || !bssidSet.has(id) || isEvicted(live.ts, now)) continue;
    addAp(id, null, live.band, live.rssi, live.ts, 0, false);
  }

  // Client nodes: inventory then live-only, minus anything that's really an AP.
  // Cluster each client into its associated network's sector when known.
  const clientNodes: ClientNode[] = [];
  const seenClients = new Set<string>();

  const clientGroup = (mac: string, assocBssid: string | null): string => {
    if (assocBssid && apGroupKey.has(assocBssid)) return apGroupKey.get(assocBssid)!;
    return assocBssid ?? mac;
  };

  for (const d of devices) {
    const id = d.mac.toUpperCase();
    if (bssidSet.has(id) || seenClients.has(id)) continue;
    const live = liveSeen.get(id);
    const lastSeen = Math.max(d.last_seen, live?.ts ?? 0);
    if (isEvicted(lastSeen, now)) continue;
    const band = (d.bands && d.bands !== "unknown" ? d.bands : live?.band) ?? "2.4";
    const assocBssid = assoc.get(id) ?? null;
    const rssi = live?.rssi ?? d.last_rssi;
    const group = clientGroup(id, assocBssid);
    const rssiSpread =
      d.max_rssi != null && d.min_rssi != null ? d.max_rssi - d.min_rssi : null;
    seenClients.add(id);
    clientNodes.push({
      id,
      pos: positionFor(group, id, rssi),
      azimuth: azimuthForGroup(group, id),
      band,
      rssi,
      lastSeen,
      assocBssid,
      ssid: d.last_ssid,
      frames: d.frames,
      random: !!d.is_random,
      rssiSpread,
    });
  }
  for (const [id, live] of liveSeen) {
    if (seenClients.has(id) || bssidSet.has(id) || isEvicted(live.ts, now)) continue;
    const assocBssid = assoc.get(id) ?? null;
    const group = clientGroup(id, assocBssid);
    seenClients.add(id);
    clientNodes.push({
      id,
      pos: positionFor(group, id, live.rssi),
      azimuth: azimuthForGroup(group, id),
      band: live.band,
      rssi: live.rssi,
      lastSeen: live.ts,
      assocBssid,
      ssid: null,
      frames: 0,
      random: "26AE".includes(id[1] ?? ""),
      rssiSpread: null,
    });
  }
  // Cap by recency then signal so the strongest/freshest survive the limit.
  clientNodes.sort(
    (a, b) => b.lastSeen - a.lastSeen || (b.rssi ?? -999) - (a.rssi ?? -999),
  );
  const clients = clientNodes.slice(0, CLIENT_CAP);
  const keptClientIds = new Set(clients.map((c) => c.id));

  // Association edges only where both endpoints are actually in the scene.
  const edges: EdgeModel[] = [];
  for (const c of clients) {
    if (c.assocBssid && apIds.has(c.assocBssid)) {
      const activity = normLog(pairCount.get(c.id + "|" + c.assocBssid) ?? 0, maxPair);
      edges.push({ from: c.id, to: c.assocBssid, activity });
    }
  }

  // Mesh links: within each SSID group of 2+ APs, star-link the strongest member
  // to the rest (dual-band pairs + mesh satellites read as one network). Activity is the
  // combined beacon/frame traffic of the two endpoint BSSIDs.
  const rssiById = new Map(apNodes.map((a) => [a.id, a.rssi ?? -999] as const));
  const meshLinks: EdgeModel[] = [];
  for (const members of groupMembers.values()) {
    if (members.length < 2) continue;
    const sorted = [...members].sort(
      (a, b) => (rssiById.get(b) ?? -999) - (rssiById.get(a) ?? -999),
    );
    const hub = sorted[0];
    for (let i = 1; i < sorted.length; i++) {
      const raw = (bssidCount.get(hub) ?? 0) + (bssidCount.get(sorted[i]) ?? 0);
      meshLinks.push({ from: hub, to: sorted[i], activity: normLog(raw, maxBssid * 2) });
    }
  }

  const channelActivity = channelsFromFrames(frames);

  // Transient flashes for recent threats that map onto a visible node.
  const nodeIds = new Set<string>([...apIds, ...keptClientIds]);
  const threatFlashes: ThreatFlash[] = [];
  for (const t of threats) {
    if (now - t.ts > THREAT_FLASH_WINDOW_S) continue;
    const b = up(t.bssid);
    const s = up(t.src);
    const target = b && nodeIds.has(b) ? b : s && nodeIds.has(s) ? s : null;
    if (!target) continue;
    threatFlashes.push({
      id: `${target}:${t.ts}:${t.rule}`,
      nodeId: target,
      severity: t.severity,
      ts: t.ts,
    });
  }

  const attackBeams = deriveAttackBeams(threats, nodeIds, now);

  return {
    apNodes,
    clientNodes: clients,
    edges,
    meshLinks,
    channelActivity,
    threatFlashes,
    attackBeams,
  };
}

/**
 * Turn recent threats into directed attack vectors between two *visible* nodes.
 * Distinguished by rule (not just severity) so the renderer can style deauth
 * floods and evil twins differently:
 *   • deauth_flood → attacker BSSID (or src) ⇒ detail.target_dst victim;
 *   • evil_twin    → rogue BSSID ⇒ each legit BSSID it's impersonating.
 * Endpoints that aren't on-scene are skipped (the transient ThreatFx ring still
 * fires for them). Capped at BEAM_CAP. Pure/testable.
 */
export function deriveAttackBeams(
  threats: Threat[],
  nodeIds: Set<string>,
  now: number,
): AttackBeam[] {
  const beams: AttackBeam[] = [];
  const push = (from: string | null, to: string | null, t: Threat) => {
    if (beams.length >= BEAM_CAP) return;
    if (!from || !to || from === to || to === BROADCAST) return;
    if (!nodeIds.has(from) || !nodeIds.has(to)) return;
    beams.push({
      id: `${t.rule}:${from}>${to}:${t.ts}`,
      fromId: from,
      toId: to,
      rule: t.rule,
      severity: t.severity,
      ts: t.ts,
    });
  };

  for (const t of threats) {
    if (now - t.ts > BEAM_WINDOW_S) continue;
    if (beams.length >= BEAM_CAP) break;

    if (t.rule === "deauth_flood") {
      const from = up(t.bssid) ?? up(t.src);
      const to = up((t.detail?.target_dst as string) ?? null);
      push(from, to, t);
    } else if (t.rule === "evil_twin") {
      const from = up((t.detail?.rogue_bssid as string) ?? null) ?? up(t.bssid);
      const known = Array.isArray(t.detail?.known_bssids)
        ? (t.detail.known_bssids as string[])
        : [];
      for (const kb of known.slice(0, EVIL_TWIN_FANOUT)) {
        push(from, up(kb), t);
      }
    }
  }
  return beams;
}
