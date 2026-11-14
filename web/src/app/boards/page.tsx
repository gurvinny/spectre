/**
 * Boards — per-board firmware, radio plan and health, plus board commands
 * when the sensor runs with SPECTRE_BOARD_CONTROL=true. Author: gurvinny
 */
"use client";

import { useEffect, useState } from "react";
import { RotateCcw, RefreshCw, Power, Send } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import { usePoll } from "@/hooks/usePoll";
import { Empty, Panel, Pill, SectionHeader } from "@/components/ui";
import { bandColor, compact, fmtUptime, timeAgo } from "@/lib/format";
import {
  ackText, buildSetCommand, fmtFrac, fmtPct, levelColor, liveness, loadLevel, lossLevel,
  malformedLevel, type SetForm,
} from "@/lib/boards";
import type { Board, BoardAck, BoardsResponse } from "@/lib/types";

export default function BoardsPage() {
  const { data, error, refresh } = usePoll<BoardsResponse>("/api/boards", 5000);
  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => clearInterval(id);
  }, []);

  const boards = data?.boards ?? [];
  const control = data?.control_enabled ?? false;

  return (
    <div className="flex flex-col gap-3 max-w-[1200px] mx-auto pb-10">
      <SectionHeader
        index="◈ HW"
        title="Boards"
        sub="sniffer health"
        right={
          <Pill color={control ? "var(--color-rf-amber)" : "var(--color-ink-mute)"}>
            control {control ? "on" : "off"}
          </Pill>
        }
      />
      {!control && data && (
        <p className="font-mono text-[0.66rem] text-ink-mute">
          Read only. Board commands need SPECTRE_BOARD_CONTROL=true on the sensor.
        </p>
      )}
      {error && (
        <p className="font-mono text-xs text-alert">could not load boards: {error.message}</p>
      )}
      {data && boards.length === 0 && (
        <Panel><Empty>No board has reported yet.</Empty></Panel>
      )}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        {boards.map((b) => (
          <BoardCard key={b.sensor_id} board={b} now={now}
            control={control && b.controllable} onChange={refresh} />
        ))}
      </div>
    </div>
  );
}

function BoardCard({ board, now, control, onChange }: {
  board: Board; now: number; control: boolean; onChange: () => void;
}) {
  const live = liveness(board.last_seen, now);
  const h = board.health;
  const fw = board.firmware;
  const loss = lossLevel(h.loss_pct);
  const load = loadLevel(h.uart_load);

  return (
    <div data-testid="board-card" data-board={board.sensor_id}>
      <Panel
        title={board.sensor_id}
        right={
          <span className="flex items-center gap-1.5">
            {board.band && <Pill color={bandColor(board.band)}>{board.band}</Pill>}
            <Pill color={levelColor(live)} filled>
              {live}{board.last_seen != null && ` · ${timeAgo(board.last_seen)}`}
            </Pill>
          </span>
        }
      >
        <dl className="grid grid-cols-2 sm:grid-cols-4 gap-x-4 gap-y-3">
          <Stat label="Firmware"
            value={fw?.ver ? `${fw.ver}` : fw ? "original" : "—"}
            color={fw?.boot_missed ? levelColor("warn") : undefined}
            sub={fw?.elf_sha ? `${fw.elf_sha.slice(0, 8)} · ${fw.baud ? `${fw.baud} baud` : "baud ?"}`
              : fw?.baud ? `${fw.baud} baud` : fw ? "no telemetry" : undefined} />
          <Stat label="Channels" value={board.plan.channels ?? "—"}
            sub={board.plan.dwell_ms != null ? `${board.plan.dwell_ms} ms dwell` : undefined} />
          <Stat label="Pinned" value={board.plan.pin ? `ch ${board.plan.pin}` : "no"} />
          <Stat label="Uptime"
            value={h.uptime_ms != null ? fmtUptime(h.uptime_ms / 1000) : "—"}
            sub={fw?.reset ? `reset: ${fw.reset}` : undefined} />
          <Stat label="Received" value={h.rx_total != null ? compact(h.rx_total) : "—"} />
          <Stat label="Emitted" value={h.emitted != null ? compact(h.emitted) : "—"} />
          <Stat label="Lost" value={fmtPct(h.loss_pct, 2)} color={levelColor(loss)}
            testId="board-loss"
            sub={h.lost != null ? `${compact(h.lost)} frames` : undefined} />
          <Stat label="UART load" value={fmtFrac(h.uart_load)} color={levelColor(load)}
            sub={h.queue_fill != null ? `queue peak ${fmtFrac(h.queue_fill)}` : undefined} />
          <Stat label="Heap min" value={h.heap_min != null ? `${compact(h.heap_min)}B` : "—"} />
          <Stat label="Temp" value={h.temp_c != null ? `${h.temp_c.toFixed(1)}°C` : "—"} />
          <Stat label="Bad lines" testId="board-malformed"
            value={board.malformed_lines != null ? compact(board.malformed_lines) : "—"}
            color={levelColor(malformedLevel(board.malformed_lines ?? null))}
            sub="since sensor start" />
        </dl>
        {fw?.boot_missed && (
          <p data-testid="boot-missed" className="mt-3 text-xs" style={{ color: levelColor("warn") }}>
            Boot line missed: this board restarted while nothing was reading its port.
            Version is from telemetry; reset reason, baud and plan may be from an earlier boot.
            Reboot the board with the sensor running to refresh them.
          </p>
        )}
        {control && <BoardControls board={board} onChange={onChange} />}
      </Panel>
    </div>
  );
}

function Stat({ label, value, sub, color, testId }: {
  label: string; value: string; sub?: string; color?: string; testId?: string;
}) {
  return (
    <div className="flex flex-col gap-0.5 min-w-0">
      <dt className="eyebrow">{label}</dt>
      <dd className="font-mono text-sm tabular-nums break-words" data-testid={testId}
        style={{ color: color ?? "var(--color-ink)" }}>{value}</dd>
      {sub && <dd className="font-mono text-[0.6rem] text-ink-mute break-words">{sub}</dd>}
    </div>
  );
}

/** How long "Confirm reboot" stays armed before it reverts to "Reboot". */
const REBOOT_ARM_MS = 5000;

const inputCls =
  "font-mono text-xs bg-scope-bg border border-scope-line rounded-sm px-2 py-1.5 text-ink focus:border-phosphor min-w-0";
const btnCls =
  "flex items-center gap-1.5 font-mono text-[0.66rem] uppercase tracking-wider px-2.5 py-1.5 rounded-sm border disabled:opacity-50";

function BoardControls({ board, onChange }: { board: Board; onChange: () => void }) {
  const [form, setForm] = useState<SetForm>({ channels: "", dwell: "", pin: "" });
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<{ text: string; ok: boolean } | null>(null);
  const [armed, setArmed] = useState(false);
  useEffect(() => {
    if (!armed) return;
    const id = setTimeout(() => setArmed(false), REBOOT_ARM_MS);
    return () => clearTimeout(id);
  }, [armed]);

  async function send(cmd: Record<string, unknown>) {
    setBusy(true);
    setArmed(false);
    try {
      const res = await api.post<{ id: string; ack: BoardAck | null }>(
        `/api/boards/${encodeURIComponent(board.sensor_id)}/cmd`, cmd);
      setResult({ text: ackText(res.ack), ok: res.ack?.ok === true });
      onChange();
    } catch (e) {
      setResult({ text: e instanceof ApiError ? e.message : String(e), ok: false });
    } finally {
      setBusy(false);
    }
  }

  function apply() {
    const built = buildSetCommand(form);
    if (!built.ok) {
      setResult({ text: built.error, ok: false });
      return;
    }
    send(built.value);
  }

  const set = (k: keyof SetForm) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm((f) => ({ ...f, [k]: e.target.value }));

  return (
    <div className="mt-4 pt-3 border-t border-scope-line flex flex-col gap-3">
      <div className="flex flex-wrap gap-2">
        <button className={btnCls} disabled={busy} data-testid="board-get-config"
          style={{ color: "var(--color-phosphor)", borderColor: "var(--color-phosphor-dim)" }}
          onClick={() => send({ cmd: "get_config" })}>
          <RefreshCw size={12} /> Get config
        </button>
        <button className={btnCls} disabled={busy}
          style={{ color: "var(--color-ink-dim)", borderColor: "var(--color-scope-line)" }}
          onClick={() => send({ cmd: "reset_config" })}>
          <RotateCcw size={12} /> Defaults
        </button>
        <button className={btnCls} disabled={busy} data-testid="board-reboot"
          style={{ color: "var(--color-alert)", borderColor: "color-mix(in oklab, var(--color-alert) 50%, transparent)" }}
          onClick={() => (armed ? send({ cmd: "reboot" }) : setArmed(true))}>
          <Power size={12} /> {armed ? "Confirm reboot" : "Reboot"}
        </button>
      </div>
      <div className="grid grid-cols-2 sm:grid-cols-[2fr_1fr_1fr_auto] gap-2 items-end">
        <label className="flex flex-col gap-1 min-w-0 col-span-2 sm:col-span-1">
          <span className="eyebrow">Channels</span>
          <input className={inputCls} placeholder="36, 40, 44" value={form.channels}
            onChange={set("channels")} data-testid="board-set-channels" />
        </label>
        <label className="flex flex-col gap-1 min-w-0">
          <span className="eyebrow">Dwell</span>
          <input className={inputCls} inputMode="numeric" placeholder="ms"
            value={form.dwell} onChange={set("dwell")} data-testid="board-set-dwell" />
        </label>
        <label className="flex flex-col gap-1 min-w-0">
          <span className="eyebrow">Pin</span>
          <input className={inputCls} inputMode="numeric" placeholder="0=hop"
            value={form.pin} onChange={set("pin")} data-testid="board-set-pin" />
        </label>
        <button className={`${btnCls} col-span-2 sm:col-span-1 justify-center`} disabled={busy}
          onClick={apply} data-testid="board-apply"
          style={{ color: "var(--color-rf-amber)", borderColor: "color-mix(in oklab, var(--color-rf-amber) 50%, transparent)" }}>
          <Send size={12} /> Apply
        </button>
      </div>
      <p className="font-mono text-[0.66rem]" data-testid="board-result" role="status"
        style={{ color: result ? (result.ok ? "var(--color-phosphor)" : "var(--color-alert)") : "var(--color-ink-mute)" }}>
        {result ? result.text
          : board.last_ack ? `${ackText(board.last_ack)} · ${timeAgo(board.last_ack.received_at)} ago`
          : "no command sent yet"}
      </p>
    </div>
  );
}
