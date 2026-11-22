# API Design — `/api/v1`

**Style:** REST + JSON, with SSE for progress streams · **Spec:** FastAPI-generated OpenAPI 3.1 at `/api/v1/openapi.json`; TypeScript types are generated from it ([ADR-0011](decisions/ADR-0011-openapi-generated-types.md)).

## Cross-cutting conventions

| Concern | Convention |
|---|---|
| Errors | RFC 9457 `application/problem+json`: `{type, title, status, detail, instance, request_id, errors?[]}`. Internal exception text is never returned. |
| Request IDs | The `X-Request-ID` header is accepted (if it is a valid UUID) or generated, echoed in responses, and bound to logs and audit records. |
| Pagination | `?limit=` (≤ 200, default 50) + `?cursor=` (opaque). Responses are `{items, next_cursor}`. |
| Filtering | Explicit query params per resource; unknown params give 422. |
| Concurrency | State-changing calls on versioned resources take `expected_version` (body) or `If-Match`. A mismatch gives **409**. |
| Idempotency | `Idempotency-Key` is **required** on `execute`, and optional on other POSTs. A replay returns the original response. |
| Auth | `Authorization: Bearer <JWT>` (Phase 5). Before Phase 5 a fixed local dev identity is used, and only when `AFTERMATH_ENV=development`. |
| Synthetic marker | Every response carries the header `X-Aftermath-Environment: SIMULATION` and the body field `synthetic: true` on domain objects. |
| Status codes | 200 read/ok · 201 created · 202 accepted (async workflow) · 400 malformed · 401/403 auth · 404 · 409 state/version conflict · 422 validation · 423 locked (execution in progress) · 503 dependency unavailable (DB) |

## Endpoints

Phase = the phase that implements the endpoint. **No endpoint is registered before its functionality exists.**

### System
| Method & path | Purpose | Phase |
|---|---|---|
| GET `/health` | Liveness (process up) | 1 |
| GET `/health/ready` | Readiness: DB reachable, migrations at head, dataset seeded | 1 |
| GET `/system/status` | Versions (app, engine, scoring, dataset), LLM mode/provider availability, current operational picture summary | 1 (partial) → 3 |

### Infrastructure
| Method & path | Purpose | Phase |
|---|---|---|
| GET `/infrastructure/assets` | List; filters `category`, `status`, `min_criticality`, `bbox`, `q` | 1 |
| GET `/infrastructure/assets/{code}` | Asset detail, including direct providers/dependents | 1 |
| GET `/infrastructure/assets/{code}/dependencies?direction=upstream\|downstream&depth=&service_type=` | Transitive traversal with paths and redundancy groups | 1 |
| GET `/infrastructure/graph` | Nodes and edges for React Flow (with status overlay from the current picture) | 1 |
| GET `/infrastructure/health` | Counts by status/category, service availability for the current picture | 1 (baseline) → 2 |
| GET `/infrastructure/criticality` | Static + structural criticality, single points of failure | 2 |
| GET `/infrastructure/basemap` | Synthetic basemap GeoJSON (district boundary, river, roads, zones) | 1 |

> **Adjustment:** assets live under `/infrastructure/assets/{code}` instead of `/infrastructure/{asset_id}`. Otherwise `graph`/`health` would collide with the asset-ID path parameter, and human-readable codes are more useful in URLs and logs. UUIDs are still returned.

### Scenarios (added)
| GET `/scenarios` · GET `/scenarios/{key}` | Predefined scenarios for the Simulation Lab | 2 |
|---|---|---|

### Incidents
| Method & path | Purpose | Phase |
|---|---|---|
| POST `/incidents` | Create from `{source: STRUCTURED, initiating_events…}` (deterministically validated, 201) or `{source: FREE_TEXT, raw_report}` (stored as REPORTED) | 2 |
| GET `/incidents` · GET `/incidents/{id}` | List/detail, including evidence and the latest assessment | 2 |
| POST `/incidents/{id}/analyze` | Starts the agent workflow → **202** `{workflow_run_id}`. 409 if already analysing | 3 |
| POST `/incidents/{id}/close` | Close with reason | 5 |

### Workflows & agents
| Method & path | Purpose | Phase |
|---|---|---|
| GET `/workflows/{id}` | Run status, current node, agent execution summaries | 3 |
| GET `/workflows/{id}/events` | **SSE** stream: `node_started`, `node_completed`, `agent_retry`, `awaiting_approval`, `failed` | 3 |
| GET `/agents` | The five agents: role, inputs/outputs, tools, current status | 3 |
| GET `/agents/activity?workflow_run_id=&agent=` | Paginated agent executions | 3 |
| GET `/agents/executions/{id}` | Execution detail: structured output, tool calls, evidence, errors | 3 |

### Simulations
| Method & path | Purpose | Phase |
|---|---|---|
| POST `/simulations` | Run synchronously (≤ ~100 ms): `{scenario_key}` or `{initiating_events, horizon_minutes, incident_id?}` → 201 with metrics | 2 |
| GET `/simulations` · GET `/simulations/{id}` | List/detail (`final_state`, metrics, hash) | 2 |
| GET `/simulations/{id}/events?from_t=&to_t=` | Timeline | 2 |
| GET `/simulations/compare?ids=a,b` | Server-side comparison (no duplicated logic in the UI) | 2 |
| POST `/simulations/{id}/replay` | Re-runs with identical inputs and returns `{hash_matches}` | 2 |
| POST `/operational-picture/reset` | Restores the current picture to baseline (audited; replaces the brief's `/simulations/{id}/reset`, because runs are immutable records) | 2 |

### Recovery
| Method & path | Purpose | Phase |
|---|---|---|
| POST `/recovery/strategies` | `{incident_id}` → generates the 3 strategies (new planning round), 201. Normally invoked through the workflow | 4 |
| GET `/recovery/strategies?incident_id=&status=` · GET `/recovery/strategies/{id}` | Includes actions, metrics, validation report | 4 |
| GET `/recovery/strategies/compare?incident_id=` | Side-by-side metrics and curves | 4 |
| POST `/recovery/strategies/{id}/validate` | Runs GUARDIAN rules → 200 with report (strategy becomes VALIDATED/VALIDATION_FAILED) | 4 |
| POST `/recovery/strategies/{id}/approve` | `{content_hash, comment?, expected_version}`; role `approver` | 5 |
| POST `/recovery/strategies/{id}/reject` | `{comment (required), expected_version}`; role `approver` | 5 |
| POST `/recovery/strategies/{id}/execute` | `Idempotency-Key`; role `operator`; revalidates → 202 `{execution_id}` | 5 |
| GET `/recovery/executions/{id}` | Execution status + event timeline ref | 5 |
| GET `/recovery/executions/{id}/verification` | Verification result (the brief's `/recovery/{recovery_id}/verification`) | 5 |
| GET `/inventory` · POST `/inventory` (admin) | Current resource inventory; new version | 4 |

### Audit & reports
| Method & path | Purpose | Phase |
|---|---|---|
| GET `/audit?entity_type=&entity_id=&actor=&action=&from=&to=` | Paginated audit log | 1 (basic) → 5 |
| GET `/audit/{id}` | Record with chain verification status | 1 |
| GET `/audit/verify-chain` | Recomputes the hash chain, returns the first broken link if any | 5 |
| GET `/reports/incidents/{id}?format=json\|markdown` | Full recovery report | 5 |

### Auth (Phase 5)
POST `/auth/token` (username/password → JWT) · GET `/auth/me`.

## Representative payloads

**POST /incidents (structured)**
```json
{
  "source": "STRUCTURED",
  "incident_type": "POWER_FAILURE",
  "severity": "HIGH",
  "occurred_at": "2026-11-15T06:40:00Z",
  "initiating_events": [
    {"kind": "ASSET_FAILURE", "asset_code": "SUB-02", "condition": "DAMAGED", "t_minutes": 0}
  ]
}
```

**POST /incidents (free text)**
```json
{ "source": "FREE_TEXT", "raw_report": "Explosion reported at the Riverside substation around 06:40, east bank lights out, hospital on generator." }
```

**POST /recovery/strategies/{id}/approve**
```json
{ "content_hash": "9f2c…e1", "comment": "Prioritise hospital; approved.", "expected_version": 3 }
```

**409 problem response**
```json
{
  "type": "https://aftermath.local/problems/invalid-state-transition",
  "title": "Strategy cannot be executed",
  "status": 409,
  "detail": "Strategy is REJECTED; only APPROVED strategies can be executed.",
  "instance": "/api/v1/recovery/strategies/7b1…/execute",
  "request_id": "0b9e…"
}
```

## As implemented (Phase 2)

| Method & path | Notes |
|---|---|
| GET `/scenarios`, `/scenarios/{key}` | Synced from `data/scenarios/*.json` by the seed command. Content-hashed, versioned on change. |
| POST `/simulations` | Body: exactly one of `scenario_key`, `incident_id`, `initiating_events`, plus `horizon_minutes`, `label` and `apply_to_picture`. Synchronous → **201** with full detail. Unknown asset or event beyond the horizon → 422. Free-text incident without analysis → 409. An engine exception is persisted as a FAILED run, then returns a 500 `simulation-failed` problem response carrying `simulation_id`. |
| GET `/simulations`, `/simulations/{id}`, `/simulations/{id}/events?from_t&to_t` | Cursor pagination on the list |
| GET `/simulations/compare?ids=a,b` | Server-side diff |
| POST `/simulations/{id}/replay` | `{hash_matches, snapshot_matches}` |
| GET `/operational-picture`; POST `/operational-picture/apply/{simulation_id}`; POST `/operational-picture/reset` | **Apply endpoint added** so the Lab can promote any completed run |
| POST/GET `/incidents`, GET `/incidents/{id}` | STRUCTURED (validated against the twin) or FREE_TEXT (stored verbatim; analysis in Phase 3) |
| GET `/infrastructure/criticality` | Exact N-1 report, cached per snapshot |

**Identity before Phase 5:** state-changing calls are attributed to `local:operator` and are refused with 401 when `AFTERMATH_ENV=production`. These endpoints are not yet protected by authentication. This is a known, documented gap until Phase 5.

## As implemented (Phase 4)

### Inventory

**GET `/inventory`**
- Returns the current inventory version.

**POST `/inventory`**
- Body: `{renewables, consumables, reason}`. Creates a new version, which becomes current.
- Not yet restricted to the admin role (Phase 5).

### Strategies

**POST `/recovery/strategies`** `{incident_id}` (the horizon is fixed at 7 days)
- Starts a new planning round for the incident: plans all three policies, validates each one, marks the recommended strategy, and supersedes the previous round.
- Returns **201** with a `StrategyRound`: strategies, comparison and the no-action `baseline_timeline` / `baseline_impact_hours`.
- Errors:
  - 404: unknown incident.
  - 409: the incident has no validated initiating events (not yet analysed).
  - 409: the incident is already in recovery.

**GET `/recovery/strategies?incident_id=&status=`**
- Lists strategy summaries.

**GET `/recovery/strategies/compare?incident_id=`**
- Returns the latest round.
- 404 if the incident has never been planned.

**GET `/recovery/strategies/{id}`**
- Returns `StrategyDetail`: actions, metrics, risk components, benefits, limitations, unschedulable actions, validation report, and `identical_to`, which lists the policies that produced the same plan.

**POST `/recovery/strategies/{id}/validate`**
- Re-runs GUARDIAN on the stored content and returns the report.
- Errors:
  - 409 for a `SUPERSEDED` strategy.
  - 409 for a `VALIDATION_FAILED` strategy (terminal).

### Through the workflow

The agent workflow normally calls the same services: STRATEGIST generates, GUARDIAN validates and recommends. When at least one strategy is valid, the incident moves to `AWAITING_APPROVAL`.

Approval, rejection, execution and verification are Phase 5. Phase 4 exposes no endpoint that changes infrastructure state.

## As implemented (Phase 5)

**Authentication.** Every route except `/health`, `/health/ready` and `/auth/token` returns **401** without a valid `Authorization: Bearer` token. The 401 response includes `WWW-Authenticate: Bearer`. A missing role gives **403** `forbidden`. The `local:operator` development identity has been removed.

### Auth

**POST `/auth/token`**
- Body: `{username, password}`.
- Returns `{access_token, token_type: "bearer", expires_at, user}`.
- Wrong password and unknown user give the same 401. Both are audited.

**GET `/auth/me`**
- Returns the user, their roles and `governance.separation_of_duties`.

### Decisions

**POST `/recovery/strategies/{id}/approve`**
- Body: `{content_hash, expected_version, comment?}`. Role: approver.
- Returns **201** with the `ApprovalOut` record.
- Errors:

  | Status | Problem type | When |
  |---|---|---|
  | 409 | `content-hash-mismatch` | The strategy's content changed |
  | 409 | `version-conflict` | The strategy's version changed |
  | 409 | `invalid-state-transition` | The strategy is not VALIDATED |
  | 409 | `conflict` | Another strategy for the incident is already approved or executed |
  | 403 | `forbidden` | Missing role, or separation of duties |

**POST `/recovery/strategies/{id}/reject`**
- Same as approve, except `comment` is required (at least 3 characters).
- After rejecting, if nothing in the round is left to decide, the incident returns to `ANALYZED`.

### Execution

**POST `/recovery/strategies/{id}/execute`**
- The `Idempotency-Key` header is required (otherwise 422). Role: operator.
- Execution is simulated and synchronous, taking milliseconds. It returns **201** with `RecoveryExecutionOut`: status, the full 12-rule revalidation report and the embedded verification. This deliberately differs from the 202 in the design.
- A repeated key returns the same execution with `replayed: true`.
- Errors:

  | Status | Problem type | When |
  |---|---|---|
  | 409 | `revalidation-failed` | Revalidation failed; the response includes `failed_rules` |
  | 409 | `invalid-state-transition` | The strategy is not APPROVED |
  | 409 | `conflict` | The key was already used for another strategy |

**GET `/recovery/executions/{id}`** and **GET `/recovery/executions/{id}/verification`**
- Return the stored execution and its verification.

### Other endpoints

**POST `/incidents/{id}/close`**
- Body: `{reason}`. Role: operator.
- Open strategies are superseded.

**GET `/audit/verify-chain`**
- Returns `{ok, records_checked, first_broken_id}`.
- `/audit` also accepts the `actor`, `from` and `to` filters.

**GET `/reports/incidents/{id}?format=json|markdown`**
- Built only from stored records. The simulation notice appears in the header and footer.
- Markdown is returned as `text/markdown` with a download filename.

### Changed in Phase 5
- **Strategies:** `StrategySummary` and `StrategyDetail` gain `version`. `StrategyDetail` also gains `requested_by`, `decisions` and `execution_id`.
- **Roles on existing routes:**
  - `POST /inventory` and `POST /operational-picture/reset` need **admin**.
  - `POST /operational-picture/apply/{id}` and `POST /simulations` with `apply_to_picture: true` need **operator**.
  - Plain what-if simulations are open to viewers.
- **Incident status:** when strategy generation produces at least one valid strategy, the incident moves to `AWAITING_APPROVAL`. Directly planned structured incidents can therefore be approved too.
