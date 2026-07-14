/**
 * Settings — detection tuning, retention, Wazuh forwarding, the evil-twin
 * allowlist, and console access key. Author: gurvinny
 */
"use client";

import { useEffect, useState } from "react";
import { Trash2, Plus, Save, Check } from "lucide-react";
import { api } from "@/lib/api";
import { usePoll } from "@/hooks/usePoll";
import { Panel, Pill } from "@/components/ui";
import { useTheme } from "@/components/ThemeProvider";
import { THEMES } from "@/lib/theme";
import type { KnownNetwork } from "@/lib/types";

type Settings = Record<string, string | number | boolean>;

const NUM = (v: unknown) => (typeof v === "number" ? v : Number(v));

export default function SettingsPage() {
  const { data, refresh } = usePoll<{ settings: Settings }>("/api/settings", 30000);
  const [draft, setDraft] = useState<Settings | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (data?.settings && !draft) setDraft(data.settings);
  }, [data, draft]);

  function set(key: string, value: string | number | boolean) {
    setDraft((d) => (d ? { ...d, [key]: value } : d));
    setSaved(false);
  }

  async function save() {
    if (!draft) return;
    await api.put("/api/settings", draft);
    setSaved(true);
    refresh();
  }

  if (!draft) {
    return <p className="font-mono text-xs text-ink-mute">loading settings…</p>;
  }

  return (
    <div className="flex flex-col gap-4 max-w-[900px] mx-auto pb-10">
      <div className="flex items-center gap-3 sticky top-0 z-10 py-1">
        <h1 className="font-display text-lg tracking-wide text-ink">Settings</h1>
        <button
          onClick={save}
          className="ml-auto flex items-center gap-1.5 font-mono text-xs px-3 py-1.5 rounded-sm border border-phosphor-dim text-phosphor bg-phosphor/10 hover:bg-phosphor/20"
        >
          <Save size={13} /> {saved ? "SAVED ✓" : "SAVE CHANGES"}
        </button>
      </div>

      <Appearance />

      <Panel title="Detection thresholds">
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <Num label="Deauth flood — frames" hint="per BSSID within the window" k="deauth_threshold" v={NUM(draft.deauth_threshold)} set={set} />
          <Num label="Deauth flood — window (s)" k="deauth_window_seconds" v={NUM(draft.deauth_window_seconds)} set={set} />
          <Num label="Beacon flood — distinct BSSIDs" k="beacon_flood_distinct_bssids" v={NUM(draft.beacon_flood_distinct_bssids)} set={set} />
          <Num label="Probe flood — requests" k="probe_flood_threshold" v={NUM(draft.probe_flood_threshold)} set={set} />
          <Num label="Flood window (s)" k="flood_window_seconds" v={NUM(draft.flood_window_seconds)} set={set} />
          <Num label="RSSI jump (dB)" k="rssi_jump_db" v={NUM(draft.rssi_jump_db)} set={set} />
          <Num label="Threat cooldown (s)" hint="mutes a repeating alert" k="threat_cooldown_seconds" v={NUM(draft.threat_cooldown_seconds)} set={set} />
        </div>
        <div className="hairline my-4" />
        <div className="flex flex-col gap-3">
          <Toggle label="Alert on new devices" k="new_device_alerts" v={!!draft.new_device_alerts} set={set} />
          <Toggle label="Alert on randomized-MAC devices" hint="noisy — off by default" k="alert_randomized_devices" v={!!draft.alert_randomized_devices} set={set} />
          <Toggle label="Evil-twin learn mode" hint="baseline first BSSID per SSID when no allowlist entry" k="evil_twin_learn" v={!!draft.evil_twin_learn} set={set} />
        </div>
      </Panel>

      <Panel title="Retention & disk guard">
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <Num label="Raw frame retention (hours)" k="raw_retention_hours" v={NUM(draft.raw_retention_hours)} set={set} />
          <Num label="Disk guard (% used)" hint="prune early above this" k="disk_guard_percent" v={NUM(draft.disk_guard_percent)} set={set} />
        </div>
      </Panel>

      <Panel title="Inventory lifecycle">
        <p className="font-mono text-[0.66rem] text-ink-mute mb-3">
          Devices/APs seen within the active window show in Inventory; older-but-retained
          entries are archived (still searchable); past retention they’re purged. Trusted
          APs and muted devices never expire.
        </p>
        <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
          <Num label="Device — active window (s)" hint="in the Active list this long" k="device_active_seconds" v={NUM(draft.device_active_seconds)} set={set} />
          <Num label="Device — retention (hours)" hint="purge stale clients after" k="device_retention_hours" v={NUM(draft.device_retention_hours)} set={set} />
          <Num label="AP — active window (s)" k="ap_active_seconds" v={NUM(draft.ap_active_seconds)} set={set} />
          <Num label="AP — retention (hours)" k="ap_retention_hours" v={NUM(draft.ap_retention_hours)} set={set} />
        </div>
      </Panel>

      <Panel title="Wazuh forwarding (RFC 5424)">
        <div className="flex flex-col gap-4">
          <Toggle label="Forward to Wazuh" k="wazuh_enabled" v={!!draft.wazuh_enabled} set={set} />
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <Text label="Host" k="wazuh_host" v={String(draft.wazuh_host)} set={set} />
            <Num label="Port" k="wazuh_port" v={NUM(draft.wazuh_port)} set={set} />
            <Select label="Protocol" k="wazuh_proto" v={String(draft.wazuh_proto)} options={["udp", "tcp"]} set={set} />
            <Text label="App name" k="wazuh_app_name" v={String(draft.wazuh_app_name)} set={set} />
            <Num label="Summary interval (s)" k="summary_interval_seconds" v={NUM(draft.summary_interval_seconds)} set={set} />
          </div>
        </div>
      </Panel>

      <KnownNetworks />
      <PasswordCard />
    </div>
  );
}

/* ── appearance / theme ── */
function Appearance() {
  const { theme, setTheme } = useTheme();
  return (
    <Panel title="Appearance">
      <p className="font-mono text-[0.66rem] text-ink-mute mb-3">
        Console skin — recolors the whole interface. Saved to this browser.
      </p>
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
        {THEMES.map((t) => {
          const active = t.id === theme;
          return (
            <button
              key={t.id}
              onClick={() => setTheme(t.id)}
              aria-pressed={active}
              className={`flex items-center gap-2.5 px-3 py-2.5 rounded-sm border text-left transition-colors ${
                active
                  ? "border-phosphor-dim bg-phosphor/10"
                  : "border-scope-line hover:border-ink-mute"
              }`}
            >
              <span
                className="w-4 h-4 rounded-full shrink-0"
                style={{ background: t.accent, boxShadow: active ? `0 0 8px ${t.accent}` : "none" }}
              />
              <span className="flex-1 font-mono text-xs text-ink">{t.label}</span>
              {active && <Check size={13} className="text-phosphor" />}
            </button>
          );
        })}
      </div>
      <p className="font-mono text-[0.6rem] text-ink-mute mt-3">
        Motion (starfield, sweeps, radar) follows your system “reduce motion” setting.
      </p>
    </Panel>
  );
}

/* ── field controls ── */
function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <label className="flex flex-col gap-1.5">
      <span className="eyebrow">{label}</span>
      {children}
      {hint && <span className="font-mono text-[0.6rem] text-ink-mute">{hint}</span>}
    </label>
  );
}
const inputCls =
  "font-mono text-sm bg-scope-bg border border-scope-line rounded-sm px-3 py-2 text-ink focus:border-phosphor";

function Num({ label, hint, k, v, set }: { label: string; hint?: string; k: string; v: number; set: (k: string, v: number) => void }) {
  return (
    <Field label={label} hint={hint}>
      <input type="number" value={Number.isFinite(v) ? v : 0} onChange={(e) => set(k, Number(e.target.value))} className={inputCls} />
    </Field>
  );
}
function Text({ label, hint, k, v, set }: { label: string; hint?: string; k: string; v: string; set: (k: string, v: string) => void }) {
  return (
    <Field label={label} hint={hint}>
      <input value={v} onChange={(e) => set(k, e.target.value)} className={inputCls} />
    </Field>
  );
}
function Select({ label, k, v, options, set }: { label: string; k: string; v: string; options: string[]; set: (k: string, v: string) => void }) {
  return (
    <Field label={label}>
      <select value={v} onChange={(e) => set(k, e.target.value)} className={inputCls}>
        {options.map((o) => <option key={o} value={o}>{o.toUpperCase()}</option>)}
      </select>
    </Field>
  );
}
function Toggle({ label, hint, k, v, set }: { label: string; hint?: string; k: string; v: boolean; set: (k: string, v: boolean) => void }) {
  return (
    <button onClick={() => set(k, !v)} className="flex items-center gap-3 text-left">
      <span className={`w-9 h-5 rounded-full border transition-colors relative shrink-0 ${v ? "bg-phosphor/20 border-phosphor-dim" : "bg-scope-bg border-scope-line"}`}>
        <span className={`absolute top-0.5 w-3.5 h-3.5 rounded-full transition-all ${v ? "left-4 bg-phosphor" : "left-0.5 bg-ink-mute"}`} />
      </span>
      <span className="flex flex-col">
        <span className="text-sm text-ink">{label}</span>
        {hint && <span className="font-mono text-[0.6rem] text-ink-mute">{hint}</span>}
      </span>
    </button>
  );
}

/* ── known networks (evil-twin allowlist) ── */
function KnownNetworks() {
  const { data, refresh } = usePoll<{ known_networks: KnownNetwork[] }>("/api/known-networks", 30000);
  const [ssid, setSsid] = useState("");
  const [bssid, setBssid] = useState("");
  const [band, setBand] = useState("2.4GHz");

  async function add() {
    if (!ssid) return;
    await api.post("/api/known-networks", { ssid, bssid: bssid || null, band });
    setSsid(""); setBssid("");
    refresh();
  }
  async function remove(id: number) {
    await api.del(`/api/known-networks/${id}`);
    refresh();
  }

  return (
    <Panel title="Known networks — evil-twin allowlist" right={<Pill>{data?.known_networks.length ?? 0}</Pill>}>
      <p className="font-mono text-[0.66rem] text-ink-mute mb-3">
        A trusted SSID seen from a BSSID that is not on this list raises an evil-twin alert.
      </p>
      <div className="grid grid-cols-[1fr_1fr_auto_auto] gap-2 mb-3">
        <input value={ssid} onChange={(e) => setSsid(e.target.value)} placeholder="SSID" className={inputCls} />
        <input value={bssid} onChange={(e) => setBssid(e.target.value)} placeholder="BSSID (optional)" className={inputCls} />
        <select value={band} onChange={(e) => setBand(e.target.value)} className={inputCls}>
          <option>2.4GHz</option><option>5GHz</option>
        </select>
        <button onClick={add} className="flex items-center gap-1 font-mono text-xs px-3 border border-phosphor-dim text-phosphor rounded-sm hover:bg-phosphor/10">
          <Plus size={13} /> Add
        </button>
      </div>
      <div className="flex flex-col divide-y divide-scope-line/60">
        {data?.known_networks.map((n) => (
          <div key={n.id} className="flex items-center gap-3 py-2 font-mono text-xs">
            <span className="text-ink flex-1">{n.ssid}</span>
            <span className="text-ink-dim">{n.bssid ?? "any BSSID"}</span>
            <span className="text-ink-mute">{n.band ?? "any"}</span>
            <button onClick={() => remove(n.id)} className="text-ink-mute hover:text-alert">
              <Trash2 size={13} />
            </button>
          </div>
        ))}
        {(data?.known_networks.length ?? 0) === 0 && (
          <p className="font-mono text-xs text-ink-mute py-2">No trusted networks yet.</p>
        )}
      </div>
    </Panel>
  );
}

/* ── change password ── */
function PasswordCard() {
  const [cur, setCur] = useState("");
  const [nw, setNw] = useState("");
  const [msg, setMsg] = useState<string | null>(null);

  async function change() {
    setMsg(null);
    try {
      await api.post("/api/password", { current: cur, new: nw });
      setMsg("Access key updated.");
      setCur(""); setNw("");
    } catch {
      setMsg("Could not update — check current key.");
    }
  }

  return (
    <Panel title="Console access key">
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 items-end">
        <Field label="Current key"><input type="password" value={cur} onChange={(e) => setCur(e.target.value)} className={inputCls} /></Field>
        <Field label="New key"><input type="password" value={nw} onChange={(e) => setNw(e.target.value)} className={inputCls} /></Field>
        <button onClick={change} disabled={!cur || nw.length < 6} className="font-mono text-xs py-2 border border-scope-line text-ink rounded-sm hover:border-phosphor-dim disabled:opacity-40">
          Update key
        </button>
      </div>
      {msg && <p className="font-mono text-[0.66rem] text-phosphor-dim mt-2">{msg}</p>}
    </Panel>
  );
}
