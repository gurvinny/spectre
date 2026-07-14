/**
 * Procedural canvas textures for the 3D battlespace's additive glow layers.
 * Module-cached so every halo instance shares one GPU texture — cheap enough
 * for software WebGL. Author: gurvinny
 */
import { CanvasTexture } from "three";

let haloTexture: CanvasTexture | null = null;

/** Soft radial white gradient used as the billboard "bloom" sprite. Created
 *  lazily on first call (client-only — needs `document`) and cached. */
export function getHaloTexture(): CanvasTexture {
  if (haloTexture) return haloTexture;
  if (typeof document === "undefined") {
    // SSR guard: this module only runs behind the ssr:false boundary, but a
    // blank texture beats a crash if `document` is briefly unavailable.
    haloTexture = new CanvasTexture(
      { width: 1, height: 1 } as unknown as HTMLCanvasElement,
    );
    return haloTexture;
  }
  const size = 64;
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext("2d")!;
  const half = size / 2;
  const grad = ctx.createRadialGradient(half, half, 0, half, half, half);
  // Quadratic-ish falloff: bright core, fast soft fade to nothing.
  grad.addColorStop(0, "rgba(255,255,255,1)");
  grad.addColorStop(0.4, "rgba(255,255,255,0.35)");
  grad.addColorStop(1, "rgba(255,255,255,0)");
  ctx.fillStyle = grad;
  ctx.fillRect(0, 0, size, size);
  haloTexture = new CanvasTexture(canvas);
  haloTexture.needsUpdate = true;
  return haloTexture;
}
