/**
 * Deterministic layout math for the 3D RF battlespace. Pure functions only — no
 * three/react-three-fiber imports — so positioning stays unit-testable with a
 * single source of truth.
 *
 * Physical model: the sensors sit physically above the coverage area
 * *above* everything, so the scene is a funnel with the sensor at the apex —
 *   • height  = signal strength → strong/close signals ride high near the sensor,
 *               weak/distant ones (e.g. a far mesh node) sink toward the floor;
 *   • radius  = signal strength → strong near the central axis, weak splayed out;
 *   • azimuth = a stable hash of the node's GROUP (SSID) so every BSSID of one
 *               network clusters in a single angular sector (mesh stays tight),
 *               with a small per-id spread inside the sector.
 * Band is conveyed by color, not position. Author: gurvinny
 */

export type Vec3 = [number, number, number];

/** Outer radius of the weakest-signal shell, in world units. */
export const R_MAX = 12;
/** Vertical span of the funnel. */
export const H_MAX = 7;
/** Where the sensor apex sits (just above the strongest node height). */
export const SENSOR_TOP = H_MAX * 0.62;

const Y_TOP = H_MAX * 0.42; // strongest signal height
const Y_FLOOR = -H_MAX * 0.55; // weakest signal height
/** Angular width a single SSID group occupies (radians). */
const GROUP_SPREAD = 0.6;

/** FNV-1a hash → unit float [0,1). Stable per string. */
export function hashUnit(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return (h >>> 0) / 4294967295;
}

/** -30 dBm ≈ 1 (strong/close), -90 dBm ≈ 0 (weak/far). Matches format.rssiToStrength. */
export function strengthOf(rssi: number | null): number {
  if (rssi === null || rssi === undefined) return 0;
  return Math.max(0, Math.min(1, (rssi + 90) / 60));
}

/** Jitterless radius for a given signal strength — used to draw the funnel-cage
 *  rings exactly on the shells where nodes of that strength land. */
export function shellRadius(strength: number): number {
  return R_MAX * (0.15 + 0.85 * (1 - strength));
}

/** Jitterless height for a given signal strength — the cage-ring elevation. */
export function shellHeight(strength: number): number {
  return Y_FLOOR + strength * (Y_TOP - Y_FLOOR);
}

/** Cluster angle: a network (groupKey = SSID) gets one sector; each BSSID/MAC
 *  spreads a little within it. */
export function azimuthForGroup(groupKey: string, id: string): number {
  const base = hashUnit(groupKey) * Math.PI * 2;
  const within = (hashUnit(id) - 0.5) * GROUP_SPREAD;
  return base + within;
}

/** Distance from the central axis: strong → near center, weak → out. Small
 *  deterministic jitter avoids two nodes on the same shell z-fighting. */
export function radiusForRssi(id: string, rssi: number | null): number {
  const strength = strengthOf(rssi);
  const jitter = (hashUnit(id + "#r") - 0.5) * 0.1; // ±5%
  return R_MAX * (0.15 + 0.85 * (1 - strength)) * (1 + jitter);
}

/** Height under the sensor apex: strong signal rides high (close/above), weak
 *  sinks toward the floor. Small jitter so same-strength nodes don't stack flat. */
export function heightForRssi(id: string, rssi: number | null): number {
  const strength = strengthOf(rssi);
  const jitter = (hashUnit(id + "#h") - 0.5) * (H_MAX * 0.06);
  return Y_FLOOR + strength * (Y_TOP - Y_FLOOR) + jitter;
}

export function polarToVec3(azimuth: number, radius: number, height: number): Vec3 {
  return [radius * Math.cos(azimuth), height, radius * Math.sin(azimuth)];
}

/** Full position for a node given its cluster group and signal. */
export function positionFor(
  groupKey: string,
  id: string,
  rssi: number | null,
): Vec3 {
  return polarToVec3(
    azimuthForGroup(groupKey, id),
    radiusForRssi(id, rssi),
    heightForRssi(id, rssi),
  );
}
