import { expect, test } from "@playwright/test";

/** E2E journey (Phase 3): report an incident in free text and watch the agents analyse it. */

const consoleErrors: string[] = [];
test.beforeEach(async ({ page }) => {
  consoleErrors.length = 0;
  page.on("console", (m) => m.type() === "error" && consoleErrors.push(m.text()));
  page.on("pageerror", (e) => consoleErrors.push(e.message));
});
test.afterEach(() => expect(consoleErrors, consoleErrors.join("\n")).toEqual([]));

test("free-text report is analysed by SENTINEL, CARTOGRAPHER and ORACLE", async ({ page }) => {
  await page.goto("/agents");
  const intake = page.getByTestId("incident-intake");
  await intake
    .getByPlaceholder("Describe what happened, where, and what is affected…")
    .fill("Explosion reported at the Riverside substation. Riverside Community Hospital running on generator.");
  await intake.getByRole("button", { name: "Report & analyse" }).click();

  await expect(page.getByTestId("workflow-status")).toHaveText("completed", { timeout: 30_000 });
  for (const agent of ["SENTINEL", "CARTOGRAPHER", "ORACLE", "STRATEGIST", "GUARDIAN"]) {
    await expect(page.getByTestId(`agent-card-${agent}`)).toHaveAttribute("data-status", "SUCCEEDED");
  }

  await page.getByTestId("agent-card-SENTINEL").click();
  const sentinel = page.getByTestId("execution-SENTINEL");
  await expect(sentinel).toContainText("SUB-02");
  await expect(sentinel).toContainText("Mentioned as affected");

  await page.getByTestId("agent-card-ORACLE").click();
  await expect(page.getByTestId("execution-ORACLE")).toContainText("HOS-02");
  await expect(page.getByTestId("execution-ORACLE")).toContainText("grounded");

  // ORACLE applied the result to the operational picture.
  await page.goto("/");
  await expect(page.getByTestId("operational-picture")).toContainText("ORACLE");
  await page.getByRole("button", { name: "Reset to baseline" }).click();
  await expect(page.getByTestId("operational-picture")).toContainText("Baseline");
});

test("an unclear report pauses for operator clarification, then completes", async ({ page }) => {
  await page.goto("/agents");
  const intake = page.getByTestId("incident-intake");
  await intake
    .getByPlaceholder("Describe what happened, where, and what is affected…")
    .fill("Something happened downtown, lots of sirens and people gathering.");
  await intake.getByRole("button", { name: "Report & analyse" }).click();

  const clarification = page.getByTestId("clarification");
  await expect(clarification).toBeVisible({ timeout: 30_000 });
  await clarification.getByLabel("Damaged facilities").selectOption(["SUB-01"]);
  await clarification.getByRole("button", { name: "Confirm and continue" }).click();
  await expect(page.getByTestId("workflow-status")).toHaveText("completed", { timeout: 30_000 });

  await page.goto("/");
  await page.getByRole("button", { name: "Reset to baseline" }).click();
});
