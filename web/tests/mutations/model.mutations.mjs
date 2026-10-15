// Scene model + attack beams. Threat fields here come from sniffed frames.
export const TARGET = "src/lib/viz3d/model.ts";
export const TESTS = "src/lib/viz3d/model.test.ts";
export const MUTATIONS = [
  ["broadcast-beam-drawn", "if (!from || !to || from === to || to === BROADCAST) return;", "if (!from || !to || from === to) return;", "deriveAttackBeams: skips broadcast target"],
  ["off-scene-beam-drawn", "    if (!nodeIds.has(from) || !nodeIds.has(to)) return;\n", "", "deriveAttackBeams: skips off-scene endpoints"],
  ["evil-twin-fanout-uncapped", "for (const kb of known.slice(0, EVIL_TWIN_FANOUT)) {", "for (const kb of known) {", "deriveAttackBeams: evil_twin fans out to legit BSSIDs, capped at 3"],
  ["stale-threats-beamed", "    if (now - t.ts > BEAM_WINDOW_S) continue;\n", "", "deriveAttackBeams: threats outside the window are ignored"],
  ["deauth-victim-dropped", "const to = up((t.detail?.target_dst as string) ?? null);", "const to = null;", "build: a deauth_flood threat becomes an attack beam AP→victim"],
];
export const SURVIVORS = {};
