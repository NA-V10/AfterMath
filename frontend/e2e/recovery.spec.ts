import { expect, test } from "@playwright/test";

import { analysedIncident, restock, signInAs } from "./auth";

/** E2E journey (Phase 4): agents plan recovery for a multi-site storm; the operator compares. */

const consoleErrors: string[] = [];
test.beforeEach(async ({ page }) => {
  consoleErrors.length = 0;
  page.on("console", (m) => m.type() === "error" && consoleErrors.push(m.text()));
  page.on("pageerror", (e) => consoleErrors.push(e.message));
});
test.afterEach(() => expect(consoleErrors, consoleErrors.join("\n")).toEqual([]));

test("compare three validated strategies for a contended storm", async ({ page, request }) => {
  await restock(request);
  const incident = await analysedIncident(request, "E2E severe storm");
  await signInAs(page, "approver");
  await page.goto("/recovery");
  await page.getByRole("button", { name: new RegExp(incident.reference) }).click();
  const round = page.getByTestId("strategy-round");
  for (const policy of ["CRITICAL_FIRST", "MAX_RESTORATION", "BALANCED"]) {
    await expect(round.getByTestId(`strategy-card-${policy}`)).toContainText("valid");
  }
  await expect(round.getByText("recommended").first()).toBeVisible();

  await round.getByTestId("strategy-card-BALANCED").click();
  const detail = page.getByTestId("strategy-detail");
  await expect(detail).toContainText("Balanced");
  await expect(detail.getByTestId("strategy-gantt")).toContainText("PDN-01");
  await expect(detail.getByTestId("validation-rules").locator("li")).toHaveCount(9);
  await expect(detail.getByTestId("governance-panel")).toContainText("Human decision required");
});
