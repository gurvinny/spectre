/**
 * Browser QA — every route mounts against a live sensor.
 * Author: gurvinny
 *
 * The sensor runs in simulator mode, so this exercises the real ingest,
 * detection and API path rather than fixtures.
 */
import { test, expect } from "@playwright/test";
import { watchForFaults, isMeaningfulError } from "./helpers";

const PASSWORD = "ci-browser-qa-password";

/** First run shows the setup wizard; complete it once per worker. */
test.beforeEach(async ({ page, context }) => {
  const api = process.env.NEXT_PUBLIC_API_BASE || "http://127.0.0.1:8100";
  // Drive setup through the API so each spec starts authenticated. 409 means
  // a previous test already completed it, in which case log in instead.
  const res = await context.request.post(`${api}/api/setup`, {
    data: { password: PASSWORD },
    failOnStatusCode: false,
  });
  if (res.status() === 409) {
    await context.request.post(`${api}/api/login`, { data: { password: PASSWORD } });
  }
  await page.goto("/", { waitUntil: "domcontentloaded" });
});

const ROUTES = ["/", "/spectrum", "/inventory", "/threats", "/settings", "/battlespace"];

for (const route of ROUTES) {
  test(`route ${route} mounts without errors`, async ({ page }) => {
    const faults = watchForFaults(page);

    await page.goto(route, { waitUntil: "networkidle" });
    await expect(page.locator("body")).toBeVisible();

    // The auth gate must have resolved to the app shell, not the boot,
    // offline, setup or login screens.
    await expect(page.locator("main, [role='main'], canvas").first()).toBeVisible();

    expect(faults.pageErrors, `uncaught exceptions on ${route}`).toEqual([]);
    expect(
      faults.consoleErrors.filter(isMeaningfulError),
      `console errors on ${route}`,
    ).toEqual([]);
  });
}
