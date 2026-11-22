import { expect, test } from "@playwright/test";

import { signInAs } from "./auth";

/** docs/TESTING_STRATEGY.md — E2E journey 2 (Phase 2): run a scenario, replay the cascade. */

const consoleErrors: string[] = [];
test.beforeEach(async ({ page }) => {
  await signInAs(page, "admin");
  consoleErrors.length = 0;
  page.on("console", (m) => m.type() === "error" && consoleErrors.push(m.text()));
  page.on("pageerror", (e) => consoleErrors.push(e.message));
});
test.afterEach(() => expect(consoleErrors, consoleErrors.join("\n")).toEqual([]));

test("lab: run the Riverside scenario and replay the cascade wave by wave", async ({ page }) => {
  await page.goto("/lab");
  const panel = page.getByTestId("run-panel");
  await panel.getByText("Major substation failure — Riverside").click();
  await panel.getByPlaceholder("e.g. Riverside drill #1").fill("e2e riverside");
  await panel.getByRole("button", { name: "Run simulation" }).click();

  const result = page.getByTestId("simulation-result");
  await expect(result).toBeVisible();
  // End state (horizon): 12 failed, 176,000 affected — as asserted in the backend golden tests.
  await expect(result.getByText("176,000")).toBeVisible();

  // Rewind to the beginning: nothing has changed yet.
  const slider = page.getByRole("slider", { name: "Cascade step" });
  await slider.fill("0");
  await expect(page.getByTestId("playback")).toContainText("before any change");

  // Step 1: SUB-02 fails at wave 0; the map/graph statuses follow.
  await page.getByRole("button", { name: "Next step" }).click();
  await expect(page.getByTestId("playback")).toContainText("T+0m · wave 0");

  // Explain an asset at this moment.
  await page.getByTestId("event-log").getByRole("button", { name: "SUB-02" }).first().click();
  await expect(page.getByTestId("asset-at-time")).toContainText("The asset itself is damaged.");

  // Reproducibility check against the backend.
  await page.getByRole("button", { name: "Replay & verify" }).click();
  await expect(page.getByTestId("replay-result")).toContainText("Identical result");
});

test("lab: compare two runs", async ({ page }) => {
  await page.goto("/lab");
  const panel = page.getByTestId("run-panel");
  const history = page.getByTestId("run-history");
  for (const [name, key] of [
    ["Major substation failure — Riverside", "substation-riverside"],
    ["River flooding — east bank lowlands", "river-flood"],
  ]) {
    await panel.getByText(name).click();
    await panel.getByRole("button", { name: "Run simulation" }).click();
    // Wait for this run to be the newest entry (a previous result may already be on screen).
    await expect(history.getByRole("listitem").first()).toContainText(key);
  }
  const boxes = history.getByRole("checkbox");
  await boxes.nth(0).check();
  await boxes.nth(1).check();
  await page.getByRole("button", { name: "Compare (2/2)" }).click();
  const cmp = page.getByTestId("comparison");
  await expect(cmp).toContainText("Failed only in A");
  await expect(cmp).toContainText("BR-01");
});

test("operational picture: apply a run, see it in Command Center and Twin, then reset", async ({ page }) => {
  await page.goto("/lab");
  const panel = page.getByTestId("run-panel");
  await panel.getByText("Combined power and telecom disruption").click();
  await panel.getByLabel("Apply result to the operational picture").check();
  await panel.getByRole("button", { name: "Run simulation" }).click();
  await expect(page.getByTestId("simulation-result")).toBeVisible();

  await page.goto("/command");
  const picture = page.getByTestId("operational-picture");
  await expect(picture).toContainText("Showing simulation");

  await page.goto("/twin");
  await expect(page.getByTestId("picture-overlay-toggle")).toBeVisible();
  await expect(page.getByTestId("graph-node-EOC-01")).toHaveAttribute("data-status", "FAILED");

  await page.goto("/command");
  await page.getByRole("button", { name: "Reset to baseline" }).click();
  await expect(page.getByTestId("operational-picture")).toContainText("Baseline");
});

test("twin inspector shows structural criticality", async ({ page }) => {
  await page.goto("/twin");
  await page.getByTestId("graph-node-SUB-02").click();
  const crit = page.getByTestId("structural-criticality");
  await expect(crit).toContainText("single point of failure");
  await expect(crit).toContainText("HOS-02");
});
