import { readFileSync } from "node:fs";
import { join } from "node:path";

import { expect, type APIRequestContext, type Page } from "@playwright/test";

export const API = "http://localhost:8000/api/v1";
export type DemoUser = "viewer" | "operator" | "approver" | "admin";

/** DEMO_PASSWORD from the environment, else from the repo's git-ignored .env. */
export function demoPassword(): string {
  if (process.env.DEMO_PASSWORD) return process.env.DEMO_PASSWORD;
  try {
    const env = readFileSync(join(__dirname, "..", "..", ".env"), "utf-8");
    const line = env.split(/\r?\n/).find((l) => l.startsWith("DEMO_PASSWORD="));
    const value = line?.slice("DEMO_PASSWORD=".length).trim();
    if (value) return value;
  } catch {
    /* fall through */
  }
  throw new Error("Set DEMO_PASSWORD (and run `python -m app.cli seed-users`) to run the E2E suite.");
}

interface TokenOut {
  access_token: string;
  expires_at: string;
  user: { username: string; display_name: string; roles: string[]; role: string };
}

const tokens = new Map<DemoUser, TokenOut>();

export async function tokenFor(request: APIRequestContext, user: DemoUser): Promise<TokenOut> {
  const cached = tokens.get(user);
  if (cached && new Date(cached.expires_at).getTime() > Date.now() + 60_000) return cached;
  const res = await request.post(`${API}/auth/token`, { data: { username: user, password: demoPassword() } });
  if (!res.ok()) throw new Error(`Sign-in as ${user} failed: ${res.status()} ${await res.text()}`);
  const out = (await res.json()) as TokenOut;
  tokens.set(user, out);
  return out;
}

/** Authorization header for direct API calls in a test. */
export async function asUser(request: APIRequestContext, user: DemoUser): Promise<Record<string, string>> {
  return { Authorization: `Bearer ${(await tokenFor(request, user)).access_token}` };
}

export const STORM = ["SUB-02", "SUB-04", "PDN-01", "TEL-05", "WPS-02", "RD-04"];

/** Put the seeded inventory back (executions consume parts), so plans do not depend on test order. */
export async function restock(request: APIRequestContext): Promise<void> {
  const seed = JSON.parse(
    readFileSync(join(__dirname, "..", "..", "data", "synthetic", "meridian-valley", "inventory.json"), "utf-8"),
  ) as { renewables: Record<string, number>; consumables: Record<string, number> };
  const res = await request.post(`${API}/inventory`, {
    headers: await asUser(request, "admin"),
    data: { renewables: seed.renewables, consumables: seed.consumables, reason: "E2E restock" },
  });
  if (!res.ok()) throw new Error(`restock: ${res.status()} ${await res.text()}`);
}

/** Create a structured incident and run the five-agent analysis through the API, as `user`. */
export async function analysedIncident(
  request: APIRequestContext,
  title: string,
  codes: string[] = STORM,
  user: DemoUser = "operator",
): Promise<{ id: string; reference: string }> {
  const headers = await asUser(request, user);
  const created = await request.post(`${API}/incidents`, {
    headers,
    data: {
      source: "STRUCTURED",
      title,
      incident_type: "COMBINED",
      severity: "CRITICAL",
      initiating_events: codes.map((c) => ({ kind: "ASSET_FAILURE", asset_code: c })),
    },
  });
  if (!created.ok()) throw new Error(`create incident: ${created.status()} ${await created.text()}`);
  const incident = (await created.json()) as { id: string; reference: string };
  const run = await (await request.post(`${API}/incidents/${incident.id}/analyze`, { headers })).json();
  await expect
    .poll(
      async () =>
        (await (await request.get(`${API}/workflows/${run.workflow_run_id}`, { headers })).json()).status,
      { timeout: 60_000 },
    )
    .toBe("COMPLETED");
  return incident;
}

/** Start the page signed in as `user` (the session the UI stores after a real sign-in). */
export async function signInAs(page: Page, user: DemoUser): Promise<void> {
  const t = await tokenFor(page.request, user);
  const session = JSON.stringify({ token: t.access_token, expiresAt: t.expires_at, user: t.user });
  await page.addInitScript((value) => window.sessionStorage.setItem("aftermath.session", value), session);
}
