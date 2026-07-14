/**
 * Boot / offline splash while the gate probes the sensor API.
 * Author: gurvinny
 */
"use client";

import { SpectreMark } from "@/components/SpectreMark";

export function BootScreen({
  offline = false,
  onRetry,
}: {
  offline?: boolean;
  onRetry?: () => void;
}) {
  return (
    <div className="min-h-screen relative z-10 grid place-items-center px-6">
      <div className="flex flex-col items-center gap-6 text-center">
        <SpectreMark size="lg" />
        <div className="font-mono text-xs text-ink-dim tracking-widest">
          {offline ? (
            <span className="text-alert">SENSOR LINK DOWN</span>
          ) : (
            <span className="armed-dot">ESTABLISHING SENSOR LINK…</span>
          )}
        </div>
        {offline && (
          <div className="flex flex-col items-center gap-3">
            <p className="text-ink-mute text-xs max-w-xs">
              The sensor API is unreachable. Check that the SPECTRE sensor
              container is running and reachable at its configured address.
            </p>
            <button
              onClick={onRetry}
              className="font-mono text-xs px-4 py-2 border border-phosphor-dim text-phosphor hover:bg-phosphor/10 rounded-sm"
            >
              RETRY LINK
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
