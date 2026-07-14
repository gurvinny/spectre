/**
 * React wrapper around the pure buildBattlespaceModel transform. Recompute is
 * naturally throttled to the WebSocket batch cadence (useLiveFeed only sets state
 * ~4×/sec), with a slow tick so opacity fades and threat-flash expiry advance
 * even when the live feed is idle. Author: gurvinny
 */
"use client";

import { useEffect, useMemo, useState } from "react";
import { buildBattlespaceModel, type ModelInputs } from "@/lib/viz3d/model";
import type { BattlespaceModel } from "@/lib/viz3d/types";

export function useBattlespaceModel(inputs: ModelInputs): BattlespaceModel {
  const { aps, devices, frames, threats } = inputs;

  const [nowTick, setNowTick] = useState(() => Date.now() / 1000);
  useEffect(() => {
    const id = setInterval(() => setNowTick(Date.now() / 1000), 3000);
    return () => clearInterval(id);
  }, []);

  return useMemo(
    () =>
      buildBattlespaceModel(
        { aps, devices, frames, threats },
        Math.max(nowTick, Date.now() / 1000),
      ),
    [aps, devices, frames, threats, nowTick],
  );
}
