/**
 * Threat window shared by the live feed: stored threats loaded on connect and
 * threats pushed over the WebSocket, merged without duplicates, newest first.
 * Author: gurvinny
 */
import type { Threat } from "@/lib/types";

/** The fields a stored row and its pushed copy share; the store adds an id the push lacks. */
export function threatKey(t: Threat): string {
  return [t.ts, t.rule, t.band, t.src ?? "", t.bssid ?? ""].join("|");
}

/** Merge two threat lists, dropping repeats, newest first, at most `max`. */
export function mergeThreats(a: Threat[], b: Threat[], max: number): Threat[] {
  const seen = new Set<string>();
  const out: Threat[] = [];
  for (const t of [...a, ...b]) {
    const k = threatKey(t);
    if (seen.has(k)) continue;
    seen.add(k);
    out.push(t);
  }
  return out.sort((x, y) => y.ts - x.ts).slice(0, max);
}
