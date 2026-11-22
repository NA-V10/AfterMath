import { expect, test } from "@playwright/test";

import { API, analysedIncident, asUser, signInAs } from "./auth";

/** E2E journeys (Phase 5): human approval, simulated execution, verification; and governance
 * negatives (a rejected strategy cannot execute, in the UI or by direct API call). */

const consoleErrors: string[] = [];
test.beforeEach(async ({ page }) => {
  consoleErrors.length = 0;
  page.on("console", (m) => m.type() === "error" && consoleErrors.push(m.text()));
  page.on("pageerror", (e) => consoleErrors.push(e.message));
});
test.afterEach(() => expect(consoleErrors, consoleErrors.join("\n")).toEqual([]));

test("approver approves, operator executes, GUARDIAN verifies", async ({ browser, request }) => {
  const incident = await analysedIncident(request, "E2E approve and execute", ["SUB-02"]);

  // The operator requested the plan: they see it but cannot decide on it.
  const opContext = await browser.newContext();
  const op = await opContext.newPage();
  await signInAs(op, "operator");
  await op.goto("/recovery");
  await op.getByRole("button", { name: new RegExp(incident.reference) }).click();
  await expect(op.getByTestId("governance-panel")).toContainText("Only an approver can approve");

  // The approver decides, with a comment.
  const apContext = await browser.newContext();
  const ap = await apContext.newPage();
  await signInAs(ap, "approver");
  await ap.goto("/recovery");
  await ap.getByRole("button", { name: new RegExp(incident.reference) }).click();
  const panel = ap.getByTestId("governance-panel");
  await panel.getByLabel("Decision comment").fill("Hospital feed first; approved for the drill.");
  await panel.getByRole("button", { name: "Approve" }).click();
  await expect(ap.getByTestId("strategy-status")).toHaveText("approved");
  await expect(panel.getByTestId("decisions")).toContainText("Approved by approver");
  await expect(panel).toContainText("ready for simulated execution"); // roles are cumulative

  // The operator executes (simulated) after confirming.
  await op.reload();
  await op.getByRole("button", { name: new RegExp(incident.reference) }).click();
  const opPanel = op.getByTestId("governance-panel");
  await opPanel.getByRole("button", { name: "Execute (simulated)" }).click();
  await opPanel.getByRole("button", { name: "Confirm execution" }).click();
  const verification = op.getByTestId("verification");
  await expect(verification).toBeVisible({ timeout: 30_000 });
  await expect(verification).toContainText("matches the approved plan's expectation exactly");
  await expect(op.getByTestId("strategy-status")).toHaveText("executed · verified");
  await expect(op.getByTestId("incident-status")).toHaveText("recovered");

  // The audit chain is intact after the whole journey.
  await op.goto("/audit");
  await op.getByRole("button", { name: "Verify chain" }).click();
  await expect(op.getByTestId("chain-result")).toContainText("intact");
  await opContext.close();
  await apContext.close();
});

test("a rejected strategy can never be executed", async ({ page, request }) => {
  const incident = await analysedIncident(request, "E2E rejection", ["SUB-02"]);
  await signInAs(page, "approver");
  await page.goto("/recovery");
  await page.getByRole("button", { name: new RegExp(incident.reference) }).click();
  const panel = page.getByTestId("governance-panel");
  const reject = panel.getByRole("button", { name: "Reject" });
  await expect(reject).toBeDisabled(); // a rejection needs a reason
  await panel.getByLabel("Decision comment").fill("Crew safety concerns on the east bank.");
  await reject.click();
  await expect(page.getByTestId("strategy-status")).toHaveText("rejected");
  await expect(panel.getByTestId("not-executable")).toContainText("can never be executed");
  await expect(panel.getByRole("button", { name: /Execute/ })).toHaveCount(0);

  // Direct API call by an operator: refused with 409, nothing runs.
  const rejected = page.getByTestId("strategy-card-CRITICAL_FIRST");
  await expect(rejected).toHaveAttribute("data-status", /REJECTED|VALIDATED/);
  const strategies = await (
    await request.get(`${API}/recovery/strategies`, {
      params: { incident_id: incident.id, status: "REJECTED" },
      headers: await asUser(request, "operator"),
    })
  ).json();
  expect(strategies).toHaveLength(1);
  const res = await request.post(`${API}/recovery/strategies/${strategies[0].id}/execute`, {
    headers: { ...(await asUser(request, "operator")), "Idempotency-Key": `e2e-${Date.now()}` },
  });
  expect(res.status()).toBe(409);
  expect((await res.json()).type).toContain("invalid-state-transition");
});
