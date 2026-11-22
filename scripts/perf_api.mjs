// Measures the API's main operations against a running stack (no dependencies; Node 22+).
//   DEMO_PASSWORD=... node scripts/perf_api.mjs [http://localhost:8000]
// Prints the median and the slowest of several runs for each operation. Creates a few incidents,
// simulations and strategies in the target database (they are ordinary, audited records).
const API = (process.argv[2] ?? "http://localhost:8000") + "/api/v1";
const password = process.env.DEMO_PASSWORD;
if (!password) throw new Error("Set DEMO_PASSWORD");

async function call(method, path, token, body) {
  const t = performance.now();
  const res = await fetch(API + path, {
    method,
    headers: { "content-type": "application/json", ...(token ? { authorization: `Bearer ${token}` } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
  const ms = performance.now() - t;
  if (!res.ok) throw new Error(`${method} ${path}: ${res.status} ${await res.text()}`);
  return { ms, json: res.headers.get("content-type")?.includes("json") ? await res.json() : null };
}
const login = async (u) => (await call("POST", "/auth/token", null, { username: u, password })).json.access_token;
const stats = (xs) => {
  const s = [...xs].sort((a, b) => a - b);
  return `median ${s[Math.floor(s.length / 2)].toFixed(0).padStart(5)} ms   max ${s.at(-1).toFixed(0).padStart(5)} ms   n=${s.length}`;
};

const op = await login("operator");
const ap = await login("approver");
const rows = [];
async function measure(name, n, fn) {
  const xs = [];
  for (let i = 0; i < n; i++) xs.push(await fn(i));
  rows.push(`${name.padEnd(44)} ${stats(xs)}`);
}

await measure("GET /infrastructure/graph", 10, async () => (await call("GET", "/infrastructure/graph", op)).ms);
await measure("GET /operational-picture", 10, async () => (await call("GET", "/operational-picture", op)).ms);
await measure("POST /simulations (storm, 72 h)", 5, async () =>
  (await call("POST", "/simulations", op, { scenario_key: "severe-storm" })).ms);
const STORM = ["SUB-02", "SUB-04", "PDN-01", "TEL-05", "WPS-02", "RD-04"];
// Each round runs the whole governed flow on its own incident, so every plan is made against the
// current stock (an execution consumes parts; a plan made before it would fail V-010, correctly).
const t = { create: [], plan: [], approve: [], execute: [] };
for (let i = 0; i < 3; i++) {
  const inc = await call("POST", "/incidents", op, {
    source: "STRUCTURED", title: "Perf storm", incident_type: "COMBINED", severity: "CRITICAL",
    initiating_events: STORM.map((c) => ({ kind: "ASSET_FAILURE", asset_code: c })),
  });
  t.create.push(inc.ms);
  const round = await call("POST", "/recovery/strategies", op, { incident_id: inc.json.id });
  t.plan.push(round.ms);
  const s = round.json.strategies.find((x) => x.recommended);
  t.approve.push((await call("POST", `/recovery/strategies/${s.id}/approve`, ap,
    { content_hash: s.content_hash, expected_version: s.version })).ms);
  const t0 = performance.now();
  const res = await fetch(`${API}/recovery/strategies/${s.id}/execute`, {
    method: "POST", headers: { authorization: `Bearer ${op}`, "Idempotency-Key": `perf-${Date.now()}-${i}` },
  });
  if (!res.ok) throw new Error(`execute ${res.status} ${await res.text()}`);
  t.execute.push(performance.now() - t0);
}
rows.push(`${"POST /incidents (structured)".padEnd(44)} ${stats(t.create)}`);
rows.push(`${"POST /recovery/strategies (3 plans + checks)".padEnd(44)} ${stats(t.plan)}`);
rows.push(`${"POST …/approve".padEnd(44)} ${stats(t.approve)}`);
rows.push(`${"POST …/execute (revalidate, run, verify)".padEnd(44)} ${stats(t.execute)}`);
await measure("GET /audit/verify-chain", 3, async () => (await call("GET", "/audit/verify-chain", op)).ms);
console.log(rows.join("\n"));
