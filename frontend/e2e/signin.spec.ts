import { expect, test } from "@playwright/test";

import { demoPassword, signInAs } from "./auth";

/** Sign-in gate (Phase 5): nothing but the sign-in form is reachable without a session. */

const consoleErrors: string[] = [];
test.beforeEach(async ({ page }) => {
  consoleErrors.length = 0;
  page.on("console", (m) => m.type() === "error" && consoleErrors.push(m.text()));
  page.on("pageerror", (e) => consoleErrors.push(e.message));
});

test("sign in through the form, see your role, sign out", async ({ page }) => {
  await page.goto("/recovery");
  await expect(page.getByTestId("simulation-banner")).toBeVisible();
  const form = page.getByRole("form", { name: "Sign in" });
  await expect(form).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Primary" })).toHaveCount(0);

  await form.getByLabel("Username").fill("viewer");
  await form.getByLabel("Password").fill("definitely-wrong-password");
  await form.getByRole("button", { name: "Sign in" }).click();
  await expect(form.getByRole("alert")).toHaveText("Unknown user or wrong password.");

  await form.getByLabel("Password").fill(demoPassword());
  await form.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByTestId("user-role")).toHaveText("viewer");
  await expect(page.getByRole("heading", { name: "Recovery Command" })).toBeVisible();

  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page.getByRole("form", { name: "Sign in" })).toBeVisible();
  // The only console error allowed is the browser logging the deliberate 401 above.
  expect(consoleErrors.filter((e) => !e.includes("401"))).toEqual([]);
});

test("viewers cannot reach write actions", async ({ page }) => {
  await signInAs(page, "viewer");
  await page.goto("/command");
  await expect(page.getByTestId("user-role")).toHaveText("viewer");
  await page.goto("/agents");
  await expect(page.getByText("Only operators can report incidents")).toBeVisible();
  expect(consoleErrors).toEqual([]);
});
