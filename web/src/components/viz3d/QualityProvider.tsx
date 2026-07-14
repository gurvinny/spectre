/**
 * Adaptive-quality runtime for the battlespace, mounted as the first child of the
 * scene (inside <Canvas>) because react-three-fiber v9 does not bridge React
 * context from outside the renderer. It owns the single continuous `useFrame`
 * that drives demand rendering (`MotionDriver`): while any animated layer is
 * registered it invalidates each frame and samples frame deltas into an FPS ring,
 * re-classifying the quality tier every 2s with hysteresis. Manual mode + OS
 * reduced-motion fold in via `effectiveTier`. Animated layers call
 * `useContinuousMotion(active)` so the driver knows when to run and when the scene
 * can return to its idle, demand-only state. Author: gurvinny
 */
"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { useFrame, useThree } from "@react-three/fiber";
import {
  classifyFps,
  effectiveTier,
  motionForTier,
  nextTier,
  type MotionFlags,
  type PerfMode,
  type Tier,
} from "@/lib/viz3d/quality";

interface QualityValue {
  tier: Tier;
  flags: MotionFlags;
  /** Register a live continuous animation; returns an unregister fn. */
  registerMotion: () => () => void;
}

const QualityContext = createContext<QualityValue | null>(null);

/** Ring-buffer + probe refs shared with the MotionDriver. */
interface DriverRefs {
  count: React.MutableRefObject<number>;
  ring: React.MutableRefObject<number[]>;
  probing: React.MutableRefObject<boolean>;
}

const RING_MAX = 48;
const MIN_SAMPLES = 8; // a 2s window needs this many frames to be trusted
const PROBE_IDLE_WINDOWS = 30; // ~60s idle at low tier → re-probe
const PROBE_MS = 2500;

function MotionDriver({ refs }: { refs: DriverRefs }) {
  const invalidate = useThree((s) => s.invalidate);
  useFrame((_, delta) => {
    if (refs.count.current > 0 || refs.probing.current) {
      if (delta > 0 && delta < 0.25) {
        const r = refs.ring.current;
        r.push(delta);
        if (r.length > RING_MAX) r.shift();
      }
      invalidate(); // sustain the demand loop while motion is live
    }
  });
  return null;
}

export function QualityProvider({
  mode,
  reducedMotion,
  onTierChange,
  children,
}: {
  mode: PerfMode;
  reducedMotion: boolean;
  onTierChange?: (tier: Tier) => void;
  children: React.ReactNode;
}) {
  const invalidate = useThree((s) => s.invalidate);

  const [auto, setAuto] = useState<{ tier: Tier; streak: number }>({
    tier: "med",
    streak: 0,
  });
  const autoRef = useRef(auto);
  autoRef.current = auto;

  const count = useRef(0);
  const ring = useRef<number[]>([]);
  const probing = useRef(false);
  const refs = useMemo<DriverRefs>(() => ({ count, ring, probing }), []);

  const tier = effectiveTier(auto.tier, mode, reducedMotion);
  const flags = useMemo(() => motionForTier(tier), [tier]);

  useEffect(() => {
    onTierChange?.(tier);
  }, [tier, onTierChange]);

  const registerMotion = useCallback(() => {
    count.current += 1;
    invalidate(); // kickstart the demand loop
    return () => {
      count.current = Math.max(0, count.current - 1);
    };
  }, [invalidate]);

  // FPS sampler — only meaningful in balanced mode (perf/beauty hard-pin tier).
  useEffect(() => {
    if (mode !== "balanced") return;
    let idle = 0;
    const id = setInterval(() => {
      const samples = ring.current;
      ring.current = [];
      if (samples.length >= MIN_SAMPLES) {
        const avg = samples.reduce((a, b) => a + b, 0) / samples.length;
        const fps = 1 / avg;
        idle = 0;
        setAuto((prev) => nextTier(prev.tier, classifyFps(fps), prev.streak));
      } else {
        // Idle window: nothing animated, so nothing sampled. If we've been stuck
        // at low for a while, fire a brief probe so the client can be re-measured.
        idle += 1;
        if (autoRef.current.tier === "low" && idle >= PROBE_IDLE_WINDOWS) {
          idle = 0;
          probing.current = true;
          invalidate();
          setTimeout(() => {
            probing.current = false;
          }, PROBE_MS);
        }
      }
    }, 2000);
    return () => clearInterval(id);
  }, [mode, invalidate]);

  const value = useMemo<QualityValue>(
    () => ({ tier, flags, registerMotion }),
    [tier, flags, registerMotion],
  );

  return (
    <QualityContext.Provider value={value}>
      <MotionDriver refs={refs} />
      {children}
    </QualityContext.Provider>
  );
}

/** Read the active tier + motion flags inside the scene. */
export function useQuality(): QualityValue {
  const v = useContext(QualityContext);
  if (!v) throw new Error("useQuality must be used within a QualityProvider");
  return v;
}

/**
 * Declare that this component is running a continuous animation while `active`.
 * The driver keeps the demand loop alive as long as at least one is registered.
 */
export function useContinuousMotion(active: boolean): void {
  const { registerMotion } = useQuality();
  useEffect(() => {
    if (!active) return;
    return registerMotion();
  }, [active, registerMotion]);
}
