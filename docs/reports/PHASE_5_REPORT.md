# Phase 5 Report: Governance & Execution

**Date:** 2026-11-22 · **Status:** complete. Recovery strategies can now be approved or rejected by a human, executed in simulation, and verified.

Every API call requires sign-in. "Execution" replays the approved plan through the simulation engine. Nothing leaves the simulator.

## Decisions taken with the owner

- **Login for everything:** every API call needs a token, not only actions that change state.
- **Demo passwords from `.env`:** the demo accounts take their password from `DEMO_PASSWORD` in the git-ignored `.env`.

## Delivered

### Authentication ([ADR-0014](../decisions/ADR-0014-authentication-and-sessions.md))
- **Tokens and passwords:** HS256 tokens issued with PyJWT, the only new dependency, which is pure Python. Passwords are hashed with standard-library scrypt.
- **Roles:** cumulative roles (viewer < operator < approver < admin), re-read from the database on every request.
- **Endpoints:** `POST /auth/token` and `GET /auth/me`.
- **Audit:** failed logins are audited.
- **Production safety:** the API refuses to start in production with placeholder secrets.

### Pure governance rules (`app.governance.rules`)
- **`state_machine`:** the strategy lifecycle and its final states.
- **`policies`:** authorisation decisions, including separation of duties.
- **Validator:** `validate_execution` adds rules **V-010…V-012**.
- **`verification`:** distinguishes repaired from functionally restored assets, gives the binding cause in plain words, and compares before and after by count, criticality and population.

### Governance service (`services/governance.py`)
- **Approve and reject** are bound to `content_hash` and `expected_version`. Separation of duties applies, a rejection needs a comment, and only one strategy per incident can be approved.
- **Execute**:
  - requires an `Idempotency-Key`;
  - locks the incident and strategy rows;
  - checks the approval record's hash;
  - runs a full 12-rule GUARDIAN revalidation;
  - replays the plan as an immutable `RECOVERY` simulation run and applies it to the operational picture;
  - deducts consumables as a new inventory version;
  - supersedes sibling strategies and has GUARDIAN verify the result.

  All of this happens in one transaction, with audit records.
- **Close incident** supersedes open strategies.

### Records
- **Migration 0005** adds `app_user`, `approval_record`, `recovery_execution`, `recovery_verification` and `recovery_strategy.requested_by`.
- The three governance record tables are append-only, enforced by a trigger.

### Reports and audit
- `GET /reports/incidents/{id}` returns JSON or Markdown, built only from stored records. The simulation notice appears in the header and footer.
- `GET /audit/verify-chain` checks the audit chain, and `/audit` gains filters.

### Agents
STRATEGIST now plans on behalf of the person who started the analysis. That makes separation of duties hold for agent-made plans too.

### CLI
- `seed-users` creates the four demo accounts.
- `create-user` creates or resets one user; the password is prompted.

### Frontend
- **Sign-in screen and user menu.** A role badge and sign-out sit in the menu. The session is kept in `sessionStorage`.
- **Token on every call.** The API client attaches the token and sends nothing while signed out.
- **Workflow stream.** The progress stream moved from `EventSource` to `fetch`, so it can carry the token.
- **Recovery Command.** Each strategy shows its decision history. Approvers get approve and reject controls with a comment, and a notice when separation of duties applies. Operators get execution with a confirmation step and an idempotency key. GUARDIAN's verification panel shows before → after, repaired-but-not-functional and unresolved assets. The incident header has a Markdown report download and an incident close action. Strategy cards show their lifecycle status.
- **Role-aware controls.** Reset needs admin, apply needs operator, and incident intake needs operator.
- **Audit screen.** Gains a "Verify chain" button.

## Tests (actual results, final run)

| Suite | Result |
|---|---|
| Backend pytest | **206 passed**, 0 warnings, in 2 min 58 s (150 at the end of Phase 4) |
| ruff, ruff format, mypy (strict, `app`) | clean |
| import contracts | import-linter itself is **blocked by Application Control** (native DLL). The 3 contracts were checked with an equivalent AST-based script: all kept (90 modules). |
| `alembic check` | no drift. 0005 also upgrades → downgrades → upgrades cleanly. |
| Frontend tsc / ESLint / Vitest / `next build` | clean / clean / **16 passed** / success |
| Playwright E2E (Edge) | **16 passed** (4 new: two governance journeys and two sign-in journeys; all existing specs now sign in) |

### New coverage

**Unit (30 new)**
- Lifecycle: final states, and the only path to execution goes through APPROVED.
- Role ranking, plus all approval and execution policy denials.
- V-010 (twin changed; inventory changed but still fits; inventory changed and no longer fits), V-011 and V-012.
- Verification of a full plan.
- A *repaired-but-not-functional* case: PDN-03 repaired while SUB-02 is still down, with the reason naming SUB-02.
- Passwords: salting, malformed hashes.
- Tokens: expired, wrong secret, wrong audience or issuer, `alg=none`, malformed roles.
- Production refusing placeholder secrets.

**Integration**
- Every operation in the OpenAPI document returns 401 without a token.
- Login works, and login failures are audited without revealing which usernames exist.
- Forged tokens are rejected. A deactivated or demoted account loses access immediately, even with a valid token.
- Role matrix.
- Full flow: approve → execute → verify → report → chain check. This covers **P13**: the executed run replays to the identical hash.
- Separation of duties.
- Stale reviews: hash or version mismatch.
- Rejection is final and needs a comment.
- An unapproved strategy cannot execute, and the denial is audited.
- Only one approval per incident.
- **P12:** tampering after approval blocks execution.
- **V-010:** an inventory shortage after approval blocks execution.
- **Concurrency:** three parallel executes give exactly one execution.
- An idempotency key cannot be reused for another strategy.
- Re-planning voids an approval.
- Close incident.
- **P14:** governance records are append-only and the chain verifies.

**Stateful (P11 / P12)**
A Hypothesis state machine over the real API: random approve, reject, execute, tamper and re-plan calls by six users, each checked against a model.
- **Checked by mutation:** with revalidation disabled, it fails with the minimal sequence tamper → approve → execute.
- **Defence in depth:** with a weakened execution policy, the approval-record check and the state machine still block execution.

**E2E**
- Approver approves with a comment; the operator executes; GUARDIAN verifies ("matches the approved plan's expectation exactly"); the incident becomes recovered; the audit chain is intact.
- A rejected strategy shows "can never be executed" with no execute button, and a direct API execute returns 409.
- Sign in through the form (including a wrong password), see the role, sign out.
- A viewer cannot report incidents.

## Defects found and fixed during the phase

- **Plans that could never be approved.** A structured incident planned directly through the API stayed `REPORTED`, so its plan could never be approved. Recommendation now moves the incident to `AWAITING_APPROVAL` when at least one strategy is valid, as the agent workflow already did.
- **Next.js dev validation errors.** Gating the whole shell on the client-side session dropped the page segment from the server render, which Next 16's instant-navigation validation reports as an error. The shell now always renders the page during server render and hydration. Instead, the API client refuses to send requests while signed out.
- **Report endpoint returned 500.** A deprecated SQLAlchemy call (`Result.tuples()`) raised, because warnings are errors in tests.
- **OpenAPI name collision.** Two schemas were both named `ExecutionOut`; the new one was renamed `RecoveryExecutionOut`.
- **Weak placeholder secret.** `.env.example` had a 24-character `JWT_SECRET` placeholder, which triggered PyJWT's short-key warning. The template now leaves it empty, and an empty value falls back to a development placeholder that production refuses. The local `.env` was given a random secret and demo password; values were never printed.

## Open items / known gaps

- **Single process.** Execution and verification run in-process and synchronously (milliseconds). A multi-process deployment would rely on the database row locks, which are already in place, but has not been tested.
- **Tokens.**
  - There is no refresh token or server-side revocation list. Deactivating the account is the revocation mechanism, and it is immediate.
  - The token lives in `sessionStorage`, so an XSS flaw could steal it. There is no `dangerouslySetInnerHTML` in the app.
- **No user-management UI or API.** Users are managed with the CLI only.
- **Separation of duties at the role level.** An account with both operator and approver rights, such as admin, can approve plans that someone else requested. That follows the rule as designed.
- **Verification is deterministic.** It runs in the governance service as GUARDIAN (`agent:GUARDIAN`) and is not yet a LangGraph node. It never uses an LLM, so nothing is lost, but the Agent Activity screen does not yet show a "GUARDIAN · verify" execution.
- **Phase 7 tooling.** import-linter cannot run on this host. The equivalent check script needs to live in the repo, or the check needs to run in CI.
- **Live LLM still not exercised.** There is no API key, and paid calls need your approval.
