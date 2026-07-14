/**
 * Live Feed — the full-screen raw frame stream with pause + band/type filters.
 * Fills the content area and scrolls internally so the app chrome stays pinned.
 * Author: gurvinny
 */
"use client";

import { useState, useMemo } from "react";
import { Pause, Play } from "lucide-react";
import { useLive } from "@/components/LiveProvider";
import { FrameFeed } from "@/components/FrameFeed";
import { Panel, Pill, SectionHeader } from "@/components/ui";
import { cn } from "@/lib/utils";

const TYPES = ["ALL", "BEACON", "PROBE_REQ", "PROBE_RESP", "DATA", "DEAUTH", "DISASSOC", "AUTH"];
const BANDS = ["ALL", "2.4GHz", "5GHz"];

export default function LivePage() {
  const { frames, fps, setPaused } = useLive();
  const [paused, setLocalPaused] = useState(false);
  const [type, setType] = useState("ALL");
  const [band, setBand] = useState("ALL");

  const filtered = useMemo(
    () =>
      frames.filter(
        (f) =>
          (type === "ALL" || f.type === type) &&
          (band === "ALL" || f.band === band),
      ),
    [frames, type, band],
  );

  function togglePause() {
    const next = !paused;
    setLocalPaused(next);
    setPaused(next);
  }

  return (
    <div className="flex flex-col gap-3 h-full min-h-0 max-w-[1500px] w-full mx-auto">
      <div className="flex items-center gap-3 flex-wrap">
        <SectionHeader index="≋ RAW" title="Live Feed" sub="frame stream" />
        <Pill color="var(--color-phosphor)" filled>
          {fps.toFixed(0)} fps
        </Pill>
        <div className="ml-auto flex items-center gap-2">
          <Filter label="band" options={BANDS} value={band} onChange={setBand} />
          <Filter label="type" options={TYPES} value={type} onChange={setType} />
          <button
            onClick={togglePause}
            className={cn(
              "flex items-center gap-1.5 font-mono text-xs px-3 py-1.5 rounded-sm border",
              paused
                ? "border-rf-amber text-rf-amber"
                : "border-phosphor-dim text-phosphor",
            )}
          >
            {paused ? <Play size={13} /> : <Pause size={13} />}
            {paused ? "PAUSED" : "LIVE"}
          </button>
        </div>
      </div>

      <Panel
        className="flex-1 min-h-0"
        bodyClassName="p-2 overflow-y-auto"
        right={
          <span className="font-mono text-[0.62rem] text-ink-mute">
            {filtered.length} shown · {frames.length} buffered
          </span>
        }
        title="Stream"
      >
        <FrameFeed frames={filtered} />
      </Panel>
    </div>
  );
}

function Filter({
  label,
  options,
  value,
  onChange,
}: {
  label: string;
  options: string[];
  value: string;
  onChange: (v: string) => void;
}) {
  return (
    <label className="flex items-center gap-1.5 font-mono text-[0.62rem] text-ink-mute">
      {label}
      <select
        value={value}
        onChange={(e) => onChange(e.target.value)}
        className="bg-scope-panel border border-scope-line rounded-sm px-2 py-1 text-ink text-xs focus:border-phosphor"
      >
        {options.map((o) => (
          <option key={o} value={o}>
            {o}
          </option>
        ))}
      </select>
    </label>
  );
}
