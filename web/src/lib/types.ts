/** Shared API/WebSocket types. Author: gurvinny */

export interface Frame {
  ts: number;
  sensor: string;
  band: string;
  type: string;
  ch: number | null;
  rssi: number | null;
  src: string | null;
  dst: string | null;
  bssid: string | null;
  ssid: string | null;
}

export interface Threat {
  ts: number;
  rule: string;
  severity: string;
  rank: number;
  title: string;
  band: string;
  bssid: string | null;
  ssid: string | null;
  src: string | null;
  detail: Record<string, unknown>;
  wazuh_sent?: boolean;
}

export interface Sensor {
  sensor: string;
  band: string;
  frames: number;
  fps: number;
  online: boolean;
  last_seen: number;
}

export interface WazuhStatus {
  enabled: boolean;
  host: string;
  port: number;
  proto: string;
  sent: number;
  failures: number;
  last_error: string | null;
}

export interface Overview {
  armed: boolean;
  uptime_seconds: number;
  fps: number;
  total_frames: number;
  devices: number;
  access_points: number;
  known_aps: number;
  threats_last_hour: number;
  sensors: Sensor[];
  band_breakdown: Record<string, number>;
  frame_types: Record<string, number>;
  channels: Record<string, number>;
  top_talkers: { mac: string; frames: number }[];
  wazuh: WazuhStatus;
}

export interface Device {
  mac: string;
  first_seen: number;
  last_seen: number;
  bands: string;
  last_rssi: number | null;
  min_rssi: number | null;
  max_rssi: number | null;
  frames: number;
  is_random: number;
  last_ssid: string | null;
}

export interface AccessPoint {
  bssid: string;
  ssid: string | null;
  band: string;
  channels: string;
  first_seen: number;
  last_seen: number;
  last_rssi: number | null;
  beacons: number;
  is_known: number;
}

export interface KnownNetwork {
  id: number;
  ssid: string;
  bssid: string | null;
  band: string | null;
  note: string;
  added_at: number;
}

export interface SearchResult {
  kind: "device" | "ap" | "threat" | "known";
  ref: string;
  label: string;
  sub: string;
  band: string;
}

export type WsMessage =
  | { type: "snapshot"; overview: Overview }
  | { type: "batch"; frames: Frame[]; threats: Threat[]; fps: number };
