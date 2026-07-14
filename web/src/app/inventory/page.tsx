/**
 * Inventory — access points and client devices in one place. Access points carry
 * one-click evil-twin allowlisting (Trust); devices carry per-device anomaly muting
 * (Mute). A segmented control switches views; a scope control shows Active (recently
 * seen), Archived (aged out but retained) or All. Deep-linkable via ?tab/?scope/?q
 * so the global search can jump straight to a result. Author: gurvinny
 */
"use client";

import { Suspense, useEffect, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { Search, ShieldCheck, ShieldPlus, Bell, BellOff } from "lucide-react";
import { usePoll } from "@/hooks/usePoll";
import { api } from "@/lib/api";
import { Panel, Pill, Empty, SectionHeader } from "@/components/ui";
import { rssiColor, timeAgo, compact, bandColor } from "@/lib/format";
import type { AccessPoint, Device } from "@/lib/types";
import { cn } from "@/lib/utils";

type Tab = "aps" | "devices";
type Scope = "active" | "archived" | "all";

const SCOPES: { id: Scope; label: string }[] = [
  { id: "active", label: "Active" },
  { id: "archived", label: "Archived" },
  { id: "all", label: "All" },
];

export default function InventoryPage() {
  return (
    <Suspense fallback={null}>
      <Inventory />
    </Suspense>
  );
}

function Inventory() {
  const params = useSearchParams();
  const [tab, setTab] = useState<Tab>(params.get("tab") === "devices" ? "devices" : "aps");
  const [scope, setScope] = useState<Scope>((params.get("scope") as Scope) || "active");
  const initialQ = params.get("q") ?? "";

  const { data: apData, refresh: refreshAps } = usePoll<{ access_points: AccessPoint[] }>(
    `/api/access-points?scope=${scope}`,
    5000,
  );
  const { data: devData } = usePoll<{ devices: Device[] }>(`/api/devices?scope=${scope}`, 5000);
  const { data: mutedData, refresh: refreshMuted } = usePoll<{ muted_devices: string[] }>(
    "/api/muted-devices",
    15000,
  );

  const apCount = apData?.access_points.length ?? 0;
  const devCount = devData?.devices.length ?? 0;

  return (
    <div className="flex flex-col gap-3 max-w-[1500px] mx-auto">
      <SectionHeader index="▤ INV" title="Inventory" sub="airspace assets" />

      <div className="flex items-center gap-2 flex-wrap">
        <Seg active={tab === "aps"} onClick={() => setTab("aps")} label="Access points" count={apCount} />
        <Seg active={tab === "devices"} onClick={() => setTab("devices")} label="Devices" count={devCount} />
        <div className="ml-auto flex items-center gap-1">
          {SCOPES.map((s) => (
            <button
              key={s.id}
              onClick={() => setScope(s.id)}
              aria-pressed={scope === s.id}
              className={cn(
                "font-mono text-[0.62rem] uppercase tracking-wider px-2 py-1 rounded-sm border",
                scope === s.id
                  ? "border-phosphor-dim text-phosphor bg-phosphor/10"
                  : "border-scope-line text-ink-mute hover:text-ink hover:border-ink-mute",
              )}
            >
              {s.label}
            </button>
          ))}
        </div>
      </div>

      {tab === "aps" ? (
        <APTable data={apData?.access_points ?? []} refresh={refreshAps} initialQ={initialQ} />
      ) : (
        <DeviceTable
          data={devData?.devices ?? []}
          muted={mutedData?.muted_devices ?? []}
          refreshMuted={refreshMuted}
          initialQ={initialQ}
        />
      )}
    </div>
  );
}

function Seg({
  active,
  onClick,
  label,
  count,
}: {
  active: boolean;
  onClick: () => void;
  label: string;
  count: number;
}) {
  return (
    <button
      onClick={onClick}
      aria-pressed={active}
      className={cn(
        "flex items-center gap-2 font-mono text-xs px-3 py-1.5 rounded-sm border transition-colors",
        active
          ? "border-phosphor-dim text-phosphor bg-phosphor/10"
          : "border-scope-line text-ink-dim hover:text-ink hover:border-ink-mute",
      )}
    >
      {label}
      <span className={active ? "text-phosphor" : "text-ink-mute"}>{count}</span>
    </button>
  );
}

function SearchBox({ value, onChange, placeholder }: { value: string; onChange: (v: string) => void; placeholder: string }) {
  return (
    <label className="ml-auto flex items-center gap-2 bg-scope-panel border border-scope-line rounded-sm px-2.5 py-1.5">
      <Search size={13} className="text-ink-mute" />
      <input
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
        className="bg-transparent font-mono text-xs text-ink w-44 focus:outline-none"
      />
    </label>
  );
}

/* ── access points (evil-twin allowlist) ── */
function APTable({ data, refresh, initialQ }: { data: AccessPoint[]; refresh: () => void; initialQ: string }) {
  const [q, setQ] = useState(initialQ);
  const [override, setOverride] = useState<Record<string, boolean>>({});
  useEffect(() => setQ(initialQ), [initialQ]);

  const rows = useMemo(() => {
    if (!q) return data;
    const s = q.toLowerCase();
    return data.filter((a) => a.bssid.toLowerCase().includes(s) || (a.ssid ?? "").toLowerCase().includes(s));
  }, [data, q]);

  const isTrusted = (a: AccessPoint) => override[a.bssid] ?? Boolean(a.is_known);

  async function toggleTrust(a: AccessPoint) {
    const trusted = isTrusted(a);
    setOverride((o) => ({ ...o, [a.bssid]: !trusted }));
    try {
      if (trusted) await api.del(`/api/known-networks/by-bssid/${a.bssid}`);
      else await api.post("/api/known-networks", { ssid: a.ssid || a.bssid, bssid: a.bssid, band: a.band });
      refresh();
    } catch {
      setOverride((o) => ({ ...o, [a.bssid]: trusted }));
    }
  }

  const known = rows.filter(isTrusted).length;

  return (
    <>
      <div className="flex items-center gap-3">
        <Pill>{rows.length} APs</Pill>
        <Pill color="var(--color-phosphor)">{known} trusted</Pill>
        <SearchBox value={q} onChange={setQ} placeholder="filter bssid / ssid" />
      </div>
      <Panel bodyClassName="p-0 max-h-[calc(100vh-14rem)] overflow-auto">
        {rows.length === 0 ? (
          <Empty>No access points in this scope.</Empty>
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th>SSID</th><th>BSSID</th><th>Band</th><th>Channels</th>
                <th>RSSI</th><th>Beacons</th><th>Last</th><th>Trust</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((a) => {
                const trusted = isTrusted(a);
                return (
                  <tr key={a.bssid}>
                    <td className="text-ink">{a.ssid || <span className="text-ink-mute">‹hidden›</span>}</td>
                    <td className="text-ink-dim">{a.bssid}</td>
                    <td style={{ color: bandColor(a.band) }}>{a.band.replace("GHz", "G")}</td>
                    <td className="text-ink-mute">{a.channels || "—"}</td>
                    <td style={{ color: rssiColor(a.last_rssi) }}>{a.last_rssi ?? "—"}</td>
                    <td className="tabular-nums">{compact(a.beacons)}</td>
                    <td className="text-ink-mute">{timeAgo(a.last_seen)}</td>
                    <td>
                      <button
                        onClick={() => toggleTrust(a)}
                        title={trusted ? "Remove from evil-twin allowlist" : "Add to evil-twin allowlist"}
                        className={cn(
                          "inline-flex items-center gap-1 px-1.5 py-0.5 rounded-sm border text-[0.6rem] tracking-wide",
                          trusted
                            ? "border-phosphor-dim text-phosphor bg-phosphor/10"
                            : "border-scope-line text-ink-mute hover:text-ink hover:border-ink-mute",
                        )}
                      >
                        {trusted ? <ShieldCheck size={12} /> : <ShieldPlus size={12} />}
                        {trusted ? "TRUSTED" : "TRUST"}
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </Panel>
    </>
  );
}

/* ── devices (anomaly muting) ── */
function DeviceTable({
  data,
  muted,
  refreshMuted,
  initialQ,
}: {
  data: Device[];
  muted: string[];
  refreshMuted: () => void;
  initialQ: string;
}) {
  const [q, setQ] = useState(initialQ);
  const [override, setOverride] = useState<Record<string, boolean>>({});
  useEffect(() => setQ(initialQ), [initialQ]);

  const mutedSet = useMemo(() => new Set(muted.map((m) => m.toUpperCase())), [muted]);
  const isMuted = (mac: string) => override[mac] ?? mutedSet.has(mac.toUpperCase());

  async function toggleMute(mac: string) {
    const m = isMuted(mac);
    setOverride((o) => ({ ...o, [mac]: !m }));
    try {
      if (m) await api.del(`/api/muted-devices/${mac}`);
      else await api.post("/api/muted-devices", { mac });
      refreshMuted();
    } catch {
      setOverride((o) => ({ ...o, [mac]: m }));
    }
  }

  const rows = useMemo(() => {
    if (!q) return data;
    const s = q.toLowerCase();
    return data.filter((d) => d.mac.toLowerCase().includes(s) || (d.last_ssid ?? "").toLowerCase().includes(s));
  }, [data, q]);

  return (
    <>
      <div className="flex items-center gap-3">
        <Pill>{rows.length} stations</Pill>
        {mutedSet.size > 0 && <Pill color="var(--color-ink-mute)">{mutedSet.size} muted</Pill>}
        <SearchBox value={q} onChange={setQ} placeholder="filter mac / ssid" />
      </div>
      <Panel bodyClassName="p-0 max-h-[calc(100vh-14rem)] overflow-auto">
        {rows.length === 0 ? (
          <Empty>No client devices in this scope.</Empty>
        ) : (
          <table className="data-table">
            <thead>
              <tr>
                <th>MAC</th><th>Bands</th><th>Last SSID</th><th>RSSI</th>
                <th>Frames</th><th>First</th><th>Last</th><th>Alerts</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((d) => {
                const m = isMuted(d.mac);
                return (
                  <tr key={d.mac} className={m ? "opacity-60" : ""}>
                    <td className="text-ink">
                      {d.mac}
                      {d.is_random ? <span className="ml-2 text-[0.58rem] text-rf-amber">RND</span> : null}
                    </td>
                    <td>
                      {d.bands.split(",").filter(Boolean).map((b) => (
                        <span key={b} style={{ color: bandColor(b) }} className="mr-1.5">
                          {b.replace("GHz", "G")}
                        </span>
                      ))}
                    </td>
                    <td className="text-phosphor-dim">{d.last_ssid ?? "—"}</td>
                    <td>
                      <span style={{ color: rssiColor(d.last_rssi) }}>{d.last_rssi ?? "—"}</span>
                      <span className="text-ink-mute text-[0.6rem]"> ({d.min_rssi}/{d.max_rssi})</span>
                    </td>
                    <td className="tabular-nums">{compact(d.frames)}</td>
                    <td className="text-ink-mute">{timeAgo(d.first_seen)}</td>
                    <td className="text-ink-mute">{timeAgo(d.last_seen)}</td>
                    <td>
                      <button
                        onClick={() => toggleMute(d.mac)}
                        title={m ? "Un-mute anomaly alerts for this device" : "Mute anomaly alerts for this device"}
                        className={cn(
                          "inline-flex items-center gap-1 px-1.5 py-0.5 rounded-sm border text-[0.6rem] tracking-wide",
                          m
                            ? "border-rf-amber/50 text-rf-amber bg-rf-amber/10"
                            : "border-scope-line text-ink-mute hover:text-ink hover:border-ink-mute",
                        )}
                      >
                        {m ? <BellOff size={12} /> : <Bell size={12} />}
                        {m ? "MUTED" : "MUTE"}
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </Panel>
    </>
  );
}
