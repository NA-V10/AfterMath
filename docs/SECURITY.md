# Security, Safety & Governance Model

## 1. Safety boundary (non-negotiable)

- AFTERMATH **never connects to, controls or commands real infrastructure**. There are no outbound integrations except the optional LLM provider API.
- All domain data is synthetic. This is enforced by a `CHECK (is_synthetic)` constraint on assets, incidents and scenarios. Removing it requires a migration plus an approved ADR.
- The persistent UI banner reads **"SIMULATION ENVIRONMENT — NOT CONNECTED TO LIVE INFRASTRUCTURE."** API responses carry `X-Aftermath-Environment: SIMULATION`. Reports carry the same notice in the header and footer.
- The district is fictional ("Meridian Valley") and is rendered on a synthetic basemap, so it cannot be mistaken for a real place ([ADR-0009](decisions/ADR-0009-fictional-district-basemap.md)).
- "Execution" means simulated execution: replay through the simulation engine. No code path produces external side effects.

## 2. Threat model (STRIDE summary)

| Threat | Example | Mitigation |
|---|---|---|
| Spoofing | Unauthenticated approval | JWT auth (Phase 5); approval/execute require roles; dev identity only when `AFTERMATH_ENV=development` and bound to localhost |
| Tampering | Strategy edited after approval | Approval bound to `content_hash`; hash re-verified at execute (V-009); optimistic versioning |
| Tampering | Audit history altered | Append-only trigger, INSERT/SELECT-only DB grants, hash chain plus `/audit/verify-chain` |
| Repudiation | "I didn't approve that" | ApprovalRecord with actor, role, hash, comment, request ID; audit chain |
| Information disclosure | Stack traces, secrets in logs | problem+json without internals; structlog redaction of `authorization`, `api_key`, `password`; secrets only from env |
| DoS | Huge payloads / expensive simulations | Body size limits; bounded horizon, events and polygon vertex count; per-route rate limits on analyse/execute |
| Elevation of privilege | LLM prompt injection via incident report ("approve strategy 2") | LLM outputs are data with narrow schemas; agents have only read-only tools; authorisation lives in the governance service, never in the graph or prompts |
| Race conditions | Double execute / execute while rejecting | `SELECT … FOR UPDATE` on the strategy row; unique `recovery_execution.strategy_id`; required `Idempotency-Key`; V-012 |

## 3. Authorisation model (Phase 5)

| Role | Can |
|---|---|
| viewer | read everything, run what-if simulations |
| operator | + create incidents, run analysis, generate/validate strategies, **execute approved** strategies |
| approver | + approve/reject strategies |
| admin | + manage users, inventory and datasets; reset the operational picture |

Policies (in `governance.rules.policies`, unit-tested):
- Approve/reject: role `approver`; strategy `VALIDATED`; `content_hash` matches; rejection requires a comment.
- Execute: role `operator`; strategy `APPROVED`; revalidation passes against current inventory and picture; no sibling executing or executed.
- **Separation of duties** (configurable, default **on**): the approver must not be the user who triggered the planning round. In single-user local demos it can be switched off with `GOVERNANCE_SEPARATION_OF_DUTIES=false`. This is logged at startup and shown in the UI.

Every state-changing operation runs as `authorize → validate state → mutate → audit` **inside one DB transaction**. If the audit insert fails, the change is rolled back.

## 4. Input validation

- Pydantic models with `extra="forbid"` on all request bodies; string length limits; enum validation.
- Asset references are resolved against the snapshot. Unknown codes give 422 (never a silent drop).
- GeoJSON is validated with Shapely (valid, ≤ 500 vertices, inside district bounds).
- Free text is limited to 10 000 chars and stored verbatim, never interpolated into SQL or HTML. React escapes it on render.

## 5. Secrets & configuration

- `.env` is git-ignored. `.env.example` documents every variable with no real values.
- The JWT secret, DB password and LLM keys come only from the environment. Startup fails in non-development mode if they are defaults.
- pre-commit runs `detect-secrets` (or gitleaks) to block commits containing keys.

## 6. Dependency & supply-chain hygiene

- Lockfiles are committed (`uv.lock`, `pnpm-lock.yaml`). Versions are pinned in Docker images.
- `pip-audit` and `pnpm audit` run in CI (Phase 7).
- Containers run as a non-root user; Postgres is not exposed beyond localhost in compose.

## 7. Observability for security

Security-relevant events are logged at `INFO` with `security=true` and audited: login success/failure, approval, rejection, execute attempts (including denied ones, with reason), inventory changes, operational-picture resets, governance config at startup.

## 8. Agents (as implemented, Phase 3)

- Free-text reports are stored verbatim and passed to the LLM only inside `<report>` tags, with a system instruction that the report is untrusted and must not be followed. More importantly, the **output schema** gives an injected instruction nowhere to act: quotes, type and severity only. A corpus case (R09) asserts that an "approve every strategy" injection yields nothing beyond its extracted facility.
- **What agents may write:** SENTINEL updates the incident's assessed fields and evidence; ORACLE creates an immutable simulation run and applies it to the operational picture. Every write is audited as `AGENT:<name>` with the `workflow_run_id`. No agent can approve, execute, or modify stored results; those paths do not exist in the agent toolset.
- **What is persisted:** structured outputs, short user-facing summaries, tool calls (with result digests), LLM attempt outcomes and token counts. Provider reasoning is never requested or stored.
- `LLM_API_KEY` is a `SecretStr`; logging redacts `api_key`/`llm_api_key`.

## 9. As implemented (Phase 5)

### Authentication
- See [ADR-0014](decisions/ADR-0014-authentication-and-sessions.md).
- Every route except `/health`, `/health/ready` and `/auth/token` requires a bearer token, and a test checks this for every operation.
- Roles are re-read from `app_user` on each request.

### Roles per route

| Role | Can |
|---|---|
| viewer | Read everything; run what-if simulations without applying them |
| operator | Everything a viewer can, plus: create incidents, analyse and clarify, generate and validate strategies, **execute** approved strategies, apply a run to the operational picture, close incidents |
| approver | Everything an operator can, plus **approve or reject** |
| admin | Everything an approver can, plus change the inventory and reset the operational picture |

Users are managed with the CLI (`seed-users`, `create-user`). There is no user-management API yet.

### Approve and reject
Approval and rejection live in `services/governance.decide`. The rules come from `governance.rules.policies.decide_approval`:
- The approver role is required.
- **Separation of duties:** the approver must not be the person who requested the planning round. For agent-planned rounds, that is whoever started the analysis. The setting is on by default and logged at startup.
- The strategy must be `VALIDATED` and the incident must be awaiting a decision.
- The submitted `content_hash` and `expected_version` must equal the stored ones (409 if not).
- A rejection needs a comment.
- Only one strategy per incident can be approved at a time.

### Execute
- Requires an `Idempotency-Key`. Reusing a key returns the first result; reusing it for a different strategy is a 409.
- The incident row and then the strategy row are locked `FOR UPDATE`. Concurrent calls therefore serialise, and exactly one execution can happen.
- Checks, in order:
  1. The operator role, and the strategy is `APPROVED`.
  2. An approval record exists with a hash equal to the current content hash.
  3. Full GUARDIAN revalidation: V-001…V-009 against the approved inventory version, plus V-010…V-012 against the current twin, inventory and incident.
- Any failure turns the strategy `VALIDATION_FAILED`, which is permanent, and returns 409 `revalidation-failed` with the failed rules.
- Denied attempts are audited (`strategy.execute_denied`, `strategy.revalidation_failed`).

### Transactions and immutable records
- Each decision or execution, with its audit records, commits in a single transaction.
- `approval_record`, `recovery_execution` and `recovery_verification` are append-only, enforced by the `reject_mutation()` trigger.

### Execution stays in the simulation
- "Execution" replays the plan through the simulation engine.
- The resulting immutable `RECOVERY` run is applied to the operational picture, and consumables are deducted as a new inventory version.
- No code path leaves the process.

### Secrets
- `JWT_SECRET` and `DEMO_PASSWORD` come only from the environment.
- In production, the API refuses to start with the placeholder secret, a secret shorter than 32 characters, or the placeholder database password.
