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
