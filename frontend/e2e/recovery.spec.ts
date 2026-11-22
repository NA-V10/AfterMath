import { expect, test } from "@playwright/test";

/** E2E journey (Phase 4): agents plan recovery for a multi-site storm; the operator compares. */

const API = "http://localhost:8000/api/v1";
const consoleErrors: string[] = [];
test.beforeEach(async ({ page }) => {
  consoleErrors.length = 0;
  page.on("console", (m) => m.type() === "error" && consoleErrors.push(m.text()));
  page.on("pageerror", (e) => consoleErrors.push(e.message));
});
test.afterEach(() => expect(consoleErrors, consoleErrors.join("\n")).toEqual([]));

test("compare three validated strategies for a contended storm", async ({ page, request }) => {
  const incident = await (
    await request.post(`${API}/incidents`, {
      data: {
        source: "STRUCTURED",
        title: "E2E severe storm",
        incident_type: "COMBINED",
        severity: "CRITICAL",
        initiating_events: ["SUB-02", "SUB-04", "PDN-01", "TEL-05", "WPS-02", "RD-04"].map((c) => ({
          kind: "ASSET_FAILURE",
          asset_code: c,
        })),
      },
    })
  ).json();
  const run = await (await request.post(`${API}/incidents/${incident.id}/analyze`)).json();
  await expect
    .poll(async () => (await (await request.get(`${API}/workflows/${run.workflow_run_id}`)).json()).status, {
      timeout: 60_000,
    })
    .toBe("COMPLETED");

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
  await expect(detail).toContainText("Nothing here can execute");
});
