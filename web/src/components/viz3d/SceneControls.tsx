/**
 * Camera controls for the battlespace, split out of the scene so they can read
 * the quality context: at the high tier OrbitControls gains a slow cinematic
 * idle auto-rotate. drei advances autoRotate in its own useFrame — it just
 * needs the demand loop kept alive, so we register with the MotionDriver via
 * useContinuousMotion while rotating. Author: gurvinny
 */
"use client";

import { OrbitControls, AdaptiveEvents } from "@react-three/drei";
import { useQuality, useContinuousMotion } from "./QualityProvider";

export function SceneControls() {
  const { flags } = useQuality();
  useContinuousMotion(flags.autoRotate);

  return (
    <>
      <OrbitControls
        makeDefault
        enableDamping={false}
        minDistance={8}
        maxDistance={44}
        maxPolarAngle={Math.PI * 0.52}
        target={[0, 0, 0]}
        autoRotate={flags.autoRotate}
        autoRotateSpeed={0.35}
      />
      <AdaptiveEvents />
    </>
  );
}
