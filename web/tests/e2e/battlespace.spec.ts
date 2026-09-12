/**
 * Browser QA — the 3D battlespace has to render on software WebGL.
 * Author: gurvinny
 *
 * This is the check a typecheck and a bundle cannot provide. The web test
 * suite covers layout, model and quality logic as pure functions, so it stays
 * green even if nothing draws. The scene has already turned white and crashed
 * once from GPU context loss on a software renderer, which is exactly what a
 * three.js version bump can reintroduce.
 */
import { test, expect } from "@playwright/test";
import {
  watchForFaults,
  readContextLost,
  isMeaningfulError,
  measureCanvas,
} from "./helpers";

const PASSWORD = "ci-browser-qa-password";

test.beforeEach(async ({ context }) => {
  const api = process.env.NEXT_PUBLIC_API_BASE || "http://127.0.0.1:8100";
  const res = await context.request.post(`${api}/api/setup`, {
    data: { password: PASSWORD },
    failOnStatusCode: false,
  });
  if (res.status() === 409) {
    await context.request.post(`${api}/api/login`, { data: { password: PASSWORD } });
  }
});

test("battlespace draws a real frame and keeps its WebGL context", async ({ page }) => {
  const faults = watchForFaults(page);

  await page.goto("/battlespace", { waitUntil: "networkidle" });

  const canvas = page.locator("canvas").first();
  await expect(canvas, "the r3f canvas should mount").toBeVisible();

  const glOk = await page.evaluate(() => {
    const c = document.querySelector("canvas");
    if (!c) return false;
    return Boolean(c.getContext("webgl2") || c.getContext("webgl"));
  });
  expect(glOk, "canvas should have a WebGL context").toBe(true);

  // The error boundary renders a readable message instead of a white canvas
  // when the scene throws. Its presence is a hard failure.
  await expect(
    page.getByText(/could not be displayed|webgl|context lost/i),
    "the canvas error boundary should not be showing",
  ).toHaveCount(0);

  // Let the scene settle. frameloop is "demand", so give the adaptive quality
  // engine time to classify and draw.
  await page.waitForTimeout(6000);

  const stats = await measureCanvas(canvas);
  expect(stats.distinctColors, `canvas colour variety (${JSON.stringify(stats)})`)
    .toBeGreaterThan(12);
  expect(stats.nonBlankRatio, `share of lit pixels (${JSON.stringify(stats)})`)
    .toBeGreaterThan(0.005);

  expect(await readContextLost(page), "WebGL context was lost").toBe(false);
  expect(faults.pageErrors, "uncaught exceptions").toEqual([]);
  expect(faults.consoleErrors.filter(isMeaningfulError), "console errors").toEqual([]);
});

test("battlespace survives the performance-mode switches", async ({ page }) => {
  const faults = watchForFaults(page);
  await page.goto("/battlespace", { waitUntil: "networkidle" });
  await expect(page.locator("canvas").first()).toBeVisible();
  await page.waitForTimeout(3000);

  // PERF / BAL / BEAUTY gate whole render layers on and off. Beauty is the
  // heaviest path and the one most likely to blow a software GPU budget.
  for (const label of [/beauty/i, /perf/i, /bal/i]) {
    const button = page.getByRole("button", { name: label });
    if (await button.count()) {
      await button.first().click();
      await page.waitForTimeout(2500);
      expect(
        await readContextLost(page),
        `context lost after switching to ${label}`,
      ).toBe(false);
    }
  }

  expect(faults.pageErrors, "uncaught exceptions during mode switching").toEqual([]);
});
