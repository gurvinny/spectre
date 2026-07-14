/**
 * Staleness fade for battlespace nodes. A device that stops transmitting should
 * visually fade and eventually disappear even while its DB row persists, so the
 * scene reflects what's live rather than what's ever been seen. Shared by AP and
 * client instancing loops. Author: gurvinny
 */

/** Fully visible for this many seconds of silence (normal beacon gaps). */
export const GRACE_S = 20;
/** Linear fade over this window after the grace period. */
export const FADE_S = 40;
/** Past this age a node is evicted from the model entirely. */
export const EVICT_S = GRACE_S + FADE_S;

/** 1 while fresh → 0 at eviction. `now`/`lastSeen` in epoch seconds. */
export function ageOpacity(lastSeen: number, now: number): number {
  const age = now - lastSeen;
  if (age <= GRACE_S) return 1;
  if (age >= EVICT_S) return 0;
  return 1 - (age - GRACE_S) / FADE_S;
}

export function isEvicted(lastSeen: number, now: number): boolean {
  return now - lastSeen >= EVICT_S;
}
