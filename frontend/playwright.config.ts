import { defineConfig } from "@playwright/test";

/**
 * E2E against a running backend (seeded) and frontend.
 * Locally both are reused if already running; otherwise they are started.
 * PW_CHANNEL selects an installed browser (default: msedge, preinstalled on Windows),
 * avoiding a separate browser download. Use PW_CHANNEL=chromium after `playwright install`.
 */
const channel = process.env.PW_CHANNEL ?? "msedge";

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  reporter: [["list"]],
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    channel: channel === "chromium" ? undefined : channel,
    viewport: { width: 1440, height: 900 },
    trace: "retain-on-failure",
  },
  webServer: [
    {
      command: "uv run uvicorn app.main:app --port 8000",
      cwd: "../backend",
      url: "http://localhost:8000/api/v1/health/ready",
      reuseExistingServer: true,
      timeout: 120_000,
    },
    {
      command: "pnpm dev --port 3000",
      url: "http://localhost:3000",
      reuseExistingServer: true,
      timeout: 180_000,
    },
  ],
});
