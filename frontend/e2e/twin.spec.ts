import { expect, test } from "@playwright/test";

import { signInAs } from "./auth";

/** docs/TESTING_STRATEGY.md — E2E journey 1 (Phase 1). Runs against the real backend. */

test.beforeEach(async ({ page }) => {
  await signInAs(page, "admin");
  const consoleErrors: string[] = [];
  page.on("console", (m) => m.type() === "error" && consoleErrors.push(m.text()));
  page.on("pageerror", (e) => consoleErrors.push(e.message));
  (page as unknown as { consoleErrors: string[] }).consoleErrors = consoleErrors;
});

test("simulation banner is shown on every screen", async ({ page }) => {
  for (const path of ["/", "/twin", "/lab", "/recovery", "/agents", "/audit"]) {
    await page.goto(path);
    await expect(page.getByTestId("simulation-banner")).toContainText(
      "SIMULATION ENVIRONMENT — NOT CONNECTED TO LIVE INFRASTRUCTURE",
    );
  }
});

test("twin: selecting SUB-02 shows its dependencies consistently in inspector, graph and list", async ({
  page,
}) => {
  await page.goto("/twin");
  await expect(page.getByTestId("twin-map").locator("canvas")).toBeVisible();
  await expect(page.getByTestId("graph-node-SUB-02")).toBeVisible();

  // Select via the accessible asset list (keyboard-reachable path).
  await page.getByTestId("filter-panel").getByPlaceholder("Search code or name").fill("SUB-02");
  await page.getByRole("button", { name: /SUB-02/ }).click();

  const inspector = page.getByTestId("asset-inspector");
  await expect(inspector.getByRole("heading", { name: "SUB-02" })).toBeVisible();
  await expect(inspector).toContainText("Riverside Substation");
  await expect(inspector).toContainText("Downstream reach · 19");

  // Graph roles come from the same API traversal as the inspector.
  await expect(page.getByTestId("graph-node-SUB-02")).toHaveAttribute("data-role", "selected");
  for (const code of ["PDN-03", "WTP-01", "HOS-02", "ZN-01"]) {
    await expect(page.getByTestId(`graph-node-${code}`)).toHaveAttribute("data-role", "downstream");
  }
  await expect(page.getByTestId("graph-node-GSP-01")).toHaveAttribute("data-role", "upstream");
  // The independent hillside system is unrelated: filtered out while the search is active,
  // merely dimmed once filters are cleared. The selection's chain stays visible throughout.
  await expect(page.getByTestId("graph-node-SOL-01")).toHaveAttribute("data-role", "hidden");
  await page.getByRole("button", { name: "Clear filters" }).click();
  await expect(page.getByTestId("graph-node-SOL-01")).toHaveAttribute("data-role", "dimmed");
  await expect(page.getByTestId("graph-node-PDN-03")).toHaveAttribute("data-role", "downstream");

  // Navigate through the inspector to a provider.
  await inspector.getByRole("button", { name: "GSP-01" }).first().click();
  await expect(inspector.getByRole("heading", { name: "GSP-01" })).toBeVisible();
  await expect(page.getByTestId("graph-node-GSP-01")).toHaveAttribute("data-role", "selected");
});

test("twin: clicking a graph node selects it; redundancy is shown for Meridian General", async ({
  page,
}) => {
  await page.goto("/twin");
  await page.getByTestId("graph-node-HOS-01").click();
  const inspector = page.getByTestId("asset-inspector");
  await expect(inspector.getByRole("heading", { name: "HOS-01" })).toBeVisible();
  await expect(inspector).toContainText("needs 1 of 2");
  await expect(inspector).toContainText("1 spare");
});

test("twin: category filter narrows the asset list", async ({ page }) => {
  await page.goto("/twin");
  await page.getByTestId("filter-panel").getByLabel("Hospital").check();
  const list = page.getByRole("list", { name: "Matching assets" });
  await expect(list.getByRole("button")).toHaveCount(3);
  await expect(page.getByTestId("graph-node-SUB-01")).toHaveAttribute("data-role", "hidden");
});

test("audit screen lists hash-chained records newest first and pages back", async ({ page }) => {
  await page.goto("/audit");
  const rows = page.locator("tbody tr");
  await expect(rows.first()).toBeVisible();
  const ids = await rows.locator("td:first-child").allTextContents();
  const numeric = ids.map(Number);
  expect(numeric).toEqual([...numeric].sort((a, b) => b - a)); // newest first
  await expect(rows.first().locator("td").last()).toHaveText(/^[0-9a-f]{12}…$/);
  const older = page.getByRole("button", { name: "Older" });
  if (await older.isEnabled()) {
    await older.click();
    await expect(rows.first().locator("td:first-child")).not.toHaveText(String(numeric[0]));
  }
});

test.afterEach(async ({ page }) => {
  const errors = (page as unknown as { consoleErrors: string[] }).consoleErrors;
  expect(errors, `console errors: ${errors.join("\n")}`).toEqual([]);
});
