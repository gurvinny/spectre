/** Unit checks for the pure scene-model builder + attack-beam derivation.
 *  Author: gurvinny */
import { test } from "node:test";
import assert from "node:assert/strict";
import { buildBattlespaceModel, deriveAttackBeams } from "@/lib/viz3d/model";
import type { AccessPoint, Device, Frame, Threat } from "@/lib/types";

const NOW = 1_000_000;
const AP = "AA:AA:AA:AA:AA:AA";
const DEV = "11:22:33:44:55:66";

function baseInputs() {
  const aps: AccessPoint[] = [
    {
      bssid: AP,
      ssid: "ExampleNet",
      band: "2.4",
      channels: "6",
      first_seen: NOW - 30,
      last_seen: NOW,
      last_rssi: -40,
      beacons: 100,
      is_known: 1,
    },
  ];
  const devices: Device[] = [
    {
      mac: DEV,
      first_seen: NOW - 30,
      last_seen: NOW,
      bands: "2.4",
      last_rssi: -50,
      min_rssi: -70,
      max_rssi: -40,
      frames: 20,
      is_random: 0,
      last_ssid: "ExampleNet",
    },
  ];
  const frames: Frame[] = Array.from({ length: 6 }, (_, i) => ({
    ts: NOW - i,
    sensor: "s24",
    band: "2.4",
    type: "DATA",
    ch: 6,
    rssi: -50,
    src: DEV,
    dst: AP,
    bssid: AP,
    ssid: null,
  }));
  return { aps, devices, frames, threats: [] as Threat[] };
}

test("build: nodes carry azimuth and client carries rssiSpread", () => {
  const m = buildBattlespaceModel(baseInputs(), NOW);
  assert.equal(m.apNodes.length, 1);
  assert.ok(Number.isFinite(m.apNodes[0].azimuth));
  const client = m.clientNodes.find((c) => c.id === DEV);
  assert.ok(client);
  assert.equal(client.rssiSpread, 30); // -40 − (-70)
  assert.ok(Number.isFinite(client.azimuth));
});

test("build: association edge exists with positive activity", () => {
  const m = buildBattlespaceModel(baseInputs(), NOW);
  const e = m.edges.find((x) => x.from === DEV && x.to === AP);
  assert.ok(e, "assoc edge present");
  assert.ok(e.activity > 0 && e.activity <= 1);
});

test("build: a deauth_flood threat becomes an attack beam AP→victim", () => {
  const inp = baseInputs();
  inp.threats = [
    {
      ts: NOW,
      rule: "deauth_flood",
      severity: "high",
      rank: 2,
      title: "Deauth flood",
      band: "2.4",
      bssid: AP,
      ssid: "ExampleNet",
      src: AP,
      detail: { target_dst: DEV, rate_per_sec: 40 },
    },
  ];
  const m = buildBattlespaceModel(inp, NOW);
  assert.equal(m.attackBeams.length, 1);
  assert.equal(m.attackBeams[0].fromId, AP);
  assert.equal(m.attackBeams[0].toId, DEV);
  assert.equal(m.attackBeams[0].rule, "deauth_flood");
});

// --- deriveAttackBeams in isolation ---

const nodes = (...ids: string[]) => new Set(ids.map((s) => s.toUpperCase()));

test("deriveAttackBeams: skips broadcast target", () => {
  const t: Threat = {
    ts: NOW,
    rule: "deauth_flood",
    severity: "high",
    rank: 2,
    title: "",
    band: "2.4",
    bssid: AP,
    ssid: "ExampleNet",
    src: AP,
    detail: { target_dst: "FF:FF:FF:FF:FF:FF" },
  };
  assert.equal(deriveAttackBeams([t], nodes(AP), NOW).length, 0);
});

test("deriveAttackBeams: skips off-scene endpoints", () => {
  const t: Threat = {
    ts: NOW,
    rule: "deauth_flood",
    severity: "high",
    rank: 2,
    title: "",
    band: "2.4",
    bssid: AP,
    ssid: "ExampleNet",
    src: AP,
    detail: { target_dst: DEV },
  };
  // DEV not in the visible node set → no beam
  assert.equal(deriveAttackBeams([t], nodes(AP), NOW).length, 0);
  assert.equal(deriveAttackBeams([t], nodes(AP, DEV), NOW).length, 1);
});

test("deriveAttackBeams: evil_twin fans out to legit BSSIDs, capped at 3", () => {
  const rogue = "BB:BB:BB:BB:BB:BB";
  const legit = ["C1:C1:C1:C1:C1:C1", "C2:C2:C2:C2:C2:C2", "C3:C3:C3:C3:C3:C3", "C4:C4:C4:C4:C4:C4"];
  const t: Threat = {
    ts: NOW,
    rule: "evil_twin",
    severity: "critical",
    rank: 1,
    title: "",
    band: "2.4",
    bssid: rogue,
    ssid: "ExampleNet",
    src: null,
    detail: { rogue_bssid: rogue, known_bssids: legit },
  };
  const beams = deriveAttackBeams([t], nodes(rogue, ...legit), NOW);
  assert.equal(beams.length, 3); // fan-out capped
  assert.ok(beams.every((b) => b.fromId === rogue));
});

test("deriveAttackBeams: threats outside the window are ignored", () => {
  const t: Threat = {
    ts: NOW - 999,
    rule: "deauth_flood",
    severity: "high",
    rank: 2,
    title: "",
    band: "2.4",
    bssid: AP,
    ssid: "ExampleNet",
    src: AP,
    detail: { target_dst: DEV },
  };
  assert.equal(deriveAttackBeams([t], nodes(AP, DEV), NOW).length, 0);
});
