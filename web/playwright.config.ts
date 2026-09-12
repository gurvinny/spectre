/**
 * Playwright config — browser QA.
 * Author: gurvinny
 *
 * CI runners have no GPU, so Chromium falls back to SwiftShader. That is the
 * point: the battlespace was hardened specifically for software WebGL after it
 * turned white and crashed from GPU context loss, and this is the only place
 * that regression can be caught automatically.
 */
import { defineConfig, devices } from "@playwright/test";

const PORT = 4310;

export default defineConfig({
  testDir: "./tests/e2e",
  // The 3D scene needs real time to reach a first frame under SwiftShader.
  timeout: 90_000,
  expect: { timeout: 20_000 },
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : [["list"]],
  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
    launchOptions: {
      args: [
        "--use-gl=angle",
        "--use-angle=swiftshader",
        "--enable-unsafe-swiftshader",
        "--disable-dev-shm-usage",
      ],
    },
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    // The sensor is started separately by the workflow, in sim mode.
    command: `npx next start -p ${PORT}`,
    url: `http://127.0.0.1:${PORT}`,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
