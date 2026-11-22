import { expect, test } from "@playwright/test";

/** The public product page at "/" (Phase 6): static, before sign-in, and honest about being a simulator. */

test("the product page states it is a simulation and leads to the console", async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toHaveText("Recovery planning for infrastructure teams");
  await expect(page.locator(".hero__notice")).toHaveText(
    "SIMULATION ENVIRONMENT — NOT CONNECTED TO LIVE INFRASTRUCTURE",
  );
  await expect(page.locator("#safety h2")).toContainText("0 connections to real infrastructure");
  await expect(page.locator(".footer__legal")).toContainText("NOT CONNECTED TO LIVE INFRASTRUCTURE");

  // The main action opens the console, which asks for a sign-in first.
  await page.locator(".hero").getByRole("link", { name: "Open the console" }).click();
  await expect(page).toHaveURL(/\/command$/);
  await expect(page.getByRole("form", { name: "Sign in" })).toBeVisible();
  await expect(page.getByTestId("simulation-banner")).toBeVisible();
  expect(errors).toEqual([]);
});
