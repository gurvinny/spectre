/**
 * Shared browser-QA helpers.
 * Author: gurvinny
 */
import { PNG } from "pngjs";
import type { Page, Locator } from "@playwright/test";

export type PageFaults = {
  consoleErrors: string[];
  pageErrors: string[];
  contextLost: boolean;
};

/**
 * Attach listeners for the failure modes that matter here: console errors,
 * uncaught exceptions, and WebGL context loss. Context loss is the signature
 * of the GPU budget being blown -- the canvas goes white and stays white.
 */
export function watchForFaults(page: Page): PageFaults {
  const faults: PageFaults = { consoleErrors: [], pageErrors: [], contextLost: false };

  page.on("console", (msg) => {
    if (msg.type() === "error") faults.consoleErrors.push(msg.text());
  });
  page.on("pageerror", (err) => faults.pageErrors.push(String(err)));

  // Set before any app script runs, so a loss during first paint is caught.
  page.addInitScript(() => {
    (window as unknown as Record<string, unknown>).__contextLost = false;
    window.addEventListener(
      "webglcontextlost",
      () => {
        (window as unknown as Record<string, unknown>).__contextLost = true;
      },
      true,
    );
  });

  return faults;
}

export async function readContextLost(page: Page): Promise<boolean> {
  return page.evaluate(
    () => (window as unknown as Record<string, unknown>).__contextLost === true,
  );
}

/**
 * Ignore noise that says nothing about whether rendering works: a missing
 * favicon, or the API being absent in a static preview.
 */
export function isMeaningfulError(text: string): boolean {
  const benign = [
    /favicon/i,
    /Failed to load resource.*404/i,
    /ERR_CONNECTION_REFUSED/i,
    /net::ERR_/i,
    /Download the React DevTools/i,
  ];
  return !benign.some((re) => re.test(text));
}

/**
 * Index of the first canvas that owns a WebGL context.
 *
 * Do NOT reach for `canvas` first-match: these apps mount decorative 2D
 * canvases (a starfield background, waveform strips) ahead of the 3D one in
 * the DOM, so the first canvas is usually the wrong one. Measuring it would
 * report a confident pass against something that is not the scene under test.
 *
 * Probing with getContext is safe here because every canvas on the page has
 * already been initialised; a 2D canvas simply answers null.
 */
export async function webglCanvasIndex(page: Page): Promise<number> {
  return page.evaluate(() => {
    const all = Array.from(document.querySelectorAll("canvas"));
    for (let i = 0; i < all.length; i++) {
      try {
        if (all[i].getContext("webgl2") || all[i].getContext("webgl")) return i;
      } catch {
        /* a 2D canvas can throw rather than return null */
      }
    }
    return -1;
  });
}

export type CanvasStats = { width: number; height: number; distinctColors: number; nonBlankRatio: number };

/**
 * Screenshot the canvas and measure how much of it is actually drawn.
 *
 * Reading pixels back through WebGL is unreliable without
 * preserveDrawingBuffer, so this goes through the compositor instead: what
 * Playwright captures is what a user would see.
 */
export async function measureCanvas(canvas: Locator): Promise<CanvasStats> {
  const buf = await canvas.screenshot();
  const png = PNG.sync.read(buf);
  const seen = new Set<number>();
  let nonBlank = 0;
  const total = png.width * png.height;

  for (let i = 0; i < png.data.length; i += 4) {
    const r = png.data[i], g = png.data[i + 1], b = png.data[i + 2], a = png.data[i + 3];
    // Quantise to 5 bits per channel so gradient dithering does not inflate
    // the distinct-colour count into looking like real content.
    seen.add(((r >> 3) << 10) | ((g >> 3) << 5) | (b >> 3));
    if (a > 8 && r + g + b > 24) nonBlank++;
  }

  return {
    width: png.width,
    height: png.height,
    distinctColors: seen.size,
    nonBlankRatio: total ? nonBlank / total : 0,
  };
}
