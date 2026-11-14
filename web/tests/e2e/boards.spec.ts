/**
 * Browser QA — board health panel and board control, against the simulator's
 * two boards. The workflow starts the sensor with SPECTRE_BOARD_CONTROL=true.
 * Author: gurvinny
 */
import { test, expect, type Page } from "@playwright/test";
import { watchForFaults, isMeaningfulError } from "./helpers";

const PASSWORD = "ci-browser-qa-password";
const API = process.env.NEXT_PUBLIC_API_BASE || "http://127.0.0.1:8100";

test.beforeEach(async ({ context }) => {
  const res = await context.request.post(`${API}/api/setup`, {
    data: { password: PASSWORD },
    failOnStatusCode: false,
  });
  if (res.status() === 409) {
    await context.request.post(`${API}/api/login`, { data: { password: PASSWORD } });
  }
});

const card = (page: Page, id: string) => page.locator(`[data-testid="board-card"][data-board="${id}"]`);

test("both simulated boards report firmware, plan and health", async ({ page }) => {
  const faults = watchForFaults(page);
  await page.goto("/boards", { waitUntil: "networkidle" });

  for (const [id, band] of [["sim-2.4GHz", "2.4GHz"], ["sim-5GHz", "5GHz"]]) {
    const c = card(page, id);
    await expect(c).toBeVisible();
    await expect(c).toContainText(band);
    await expect(c).toContainText("460800 baud");
    await expect(c).toContainText("live");
    // Telemetry arrives every 10 s; a loss figure replaces the dash once it has.
    await expect(c.getByTestId("board-loss")).toHaveText(/%$/, { timeout: 30_000 });
    // Simulated boards send only well-formed lines.
    await expect(c.getByTestId("board-malformed")).toHaveText("0");
  }
  await expect(page.getByText("control on")).toBeVisible();

  expect(faults.pageErrors).toEqual([]);
  expect(faults.consoleErrors.filter(isMeaningfulError)).toEqual([]);
});

test("a set command round-trips to the board and back", async ({ page, context }) => {
  await page.goto("/boards", { waitUntil: "networkidle" });
  const c = card(page, "sim-5GHz");

  await c.getByTestId("board-set-dwell").fill("400");
  await c.getByTestId("board-apply").click();
  await expect(c.getByTestId("board-result")).toHaveText("set ok");
  await expect(c).toContainText("400 ms dwell");

  // The audit row and the ack are both in the store.
  const boards = await (await context.request.get(`${API}/api/boards`)).json();
  const b = boards.boards.find((x: { sensor_id: string }) => x.sensor_id === "sim-5GHz");
  expect(b.plan.dwell_ms).toBe(400);
  expect(b.last_cmd.command.dwell_ms).toBe(400);
  expect(b.last_cmd.user).toBe("admin");
  expect(b.last_ack.id).toBe(b.last_cmd.id);

  // Leave the simulator as the other specs expect it.
  await c.getByRole("button", { name: "Defaults" }).click();
  await expect(c.getByTestId("board-result")).toHaveText("reset_config ok");
  await expect(c).toContainText("200 ms dwell");
});

test("an invalid form is refused before anything is sent", async ({ page }) => {
  await page.goto("/boards", { waitUntil: "networkidle" });
  const c = card(page, "sim-2.4GHz");
  let posted = false;
  page.on("request", (r) => {
    if (r.method() === "POST" && r.url().includes("/api/boards/")) posted = true;
  });

  await c.getByTestId("board-set-dwell").fill("10");
  await c.getByTestId("board-apply").click();
  await expect(c.getByTestId("board-result")).toHaveText("dwell must be 50-5000");
  expect(posted).toBe(false);
});

test("the firmware's refusal is shown as a refusal", async ({ page }) => {
  await page.goto("/boards", { waitUntil: "networkidle" });
  const c = card(page, "sim-2.4GHz");
  // Channel 36 passes the console's checks but is not a 2.4 GHz channel.
  await c.getByTestId("board-set-channels").fill("36");
  await c.getByTestId("board-apply").click();
  await expect(c.getByTestId("board-result")).toHaveText("set refused: bad channel");
  await expect(c).toContainText("1-13");
});
