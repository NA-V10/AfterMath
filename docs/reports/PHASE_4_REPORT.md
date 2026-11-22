# Phase 4 Report: Recovery Optimisation

**Date:** 2026-11-22 · **Status:** complete. STRATEGIST and GUARDIAN are now part of the agent workflow.

Phase 4 plans and validates recovery strategies. It does not approve or execute them: approval, execution and verification are Phase 5, and nothing in this phase can execute a plan.

## Delivered

### Engine extension

- New `BACKUP_SUPPLIED` event, so mobile generators and refuelling are simulated by the engine itself.
- Engine version is now 1.1.0. The golden hashes for existing scenarios are unchanged.

### Recovery engine (`app.recovery`, pure)

- **Catalogue:**
  - Actions: REPAIR, REPLACE, mobile generator and refuel.
  - Roads are repaired by the civil crew.
  - Temporary power is offered only to critical assets that would lose power.
- **Scheduler:** serial SGS with bundle valuation, three policies, a 7-day horizon, and road access as the only hard precedence.
- **Scoring:** every candidate is scored by replaying the plan through the simulation engine.
- **Metrics:** policy loss, impact-hours, time to critical services and to 90% restored, consumption with headroom, and a risk score (R1–R4).

### Inventory

- `inventory.json`, versioned in `resource_inventory`.
- Deliberately scarce, so the policies have to trade off against each other.

### Validator (`app.governance.rules.validator`)

- GUARDIAN rules V-001…V-009, including a fresh re-simulation (V-008) and a content hash that binds each strategy (V-009).
- Malformed plans are reported, never allowed to crash the validator.

### Comparison

- Benefits and limitations are generated deterministically by comparing each strategy with the others. Identical plans are flagged (`identical_to`).
- The recommendation follows a stated rule: fewest impact-hours, then lowest risk, then policy name.

### Persistence (migration 0004)

- Tables: `resource_inventory`, `recovery_strategy`, `recovery_action`.
- Planning rounds supersede earlier ones. `VALIDATION_FAILED` is terminal.

### API

- `GET` and `POST /inventory`.
- `POST /recovery/strategies`.
- `GET /recovery/strategies`, `/recovery/strategies/compare` and `/recovery/strategies/{id}`.
- `POST /recovery/strategies/{id}/validate`.

### Agents

- **STRATEGIST** generates and compares strategies, then writes a grounded rationale for each one. The LLM explains the plan; it never chooses or computes it.
- **GUARDIAN** validates and recommends with **no LLM**.
- The workflow ends with the incident in `AWAITING_APPROVAL` when at least one strategy is valid.

### Frontend: Recovery Command

- Incident list and strategy cards with key metrics and a recommended badge.
- Impact-over-time chart with a dashed no-action baseline.
- Per-strategy view:
  - Gantt chart, with temporary power shown hatched.
  - Benefits and limitations.
  - Resources and consumables.
  - Unschedulable actions.
  - The GUARDIAN rule list.
- Agent Activity now shows all five agents.

### Benchmark

- `python -m app.cli benchmark-recovery` writes [RECOVERY_BENCHMARK.md](RECOVERY_BENCHMARK.md).

## Tests (actual results, final run)

| Suite | Result |
|---|---|
| Backend pytest | **150 passed** on the last complete run, before the backend was committed (129 at the end of Phase 3). The backend code has not changed since then. A final re-run at wrap-up was **skipped** because it was taking too long; the partial re-runs passed everything they reached (about 60 tests, including all 13 property tests in 18 s), with no failures. Some full runs stalled when output went through a PowerShell pipeline. This has not been diagnosed yet. |
| ruff, mypy (strict, now also covers `app.recovery` and `app.governance.rules`), import-linter (3 contracts; recovery and rules are pure) | ruff and mypy clean. **import-linter could not run on the final pass**: Application Control now blocks its native `_rustgrimp` DLL. Its three contracts were checked instead with an equivalent AST-based transitive import check (80 modules): all kept. |
| Frontend Vitest / tsc / ESLint / `next build` | 14 passed / clean / clean / success |
| Playwright E2E (Edge) | **12 passed**. New: compare three validated strategies for the severe storm. The agents journey now covers all five agents. |

### New coverage

- **Determinism:** identical inputs give identical plans and hashes.
- **Road access precedence.**
- **Scarce transformer:** a missing spare transformer is reported as unschedulable, not silently dropped.
- **All scenarios:** every scenario × policy plan passes the validator.
- **P9 (Hypothesis):** for random inventories, every plan the scheduler produces passes the independent validator.
- **P10 (tampering):** each of nine targeted tamperings is caught by the specific rule V-001…V-009 it targets.
- **Benchmark:** a regression test of the heuristic against brute force.
- **API:** integration tests for generate, compare, validate, supersede and the 404/409 paths.
- **Workflow:** five agents run, GUARDIAN makes no LLM calls, the provider-outage path still completes, and the incident ends in AWAITING_APPROVAL.

### Optimality

| Scenario | Policy | Gap to brute-force optimum |
|---|---|---|
| Three of the four scenarios | All three policies | 0% |
| `severe-storm` | MAX_RESTORATION | 0% |
| `severe-storm` | CRITICAL_FIRST | 0.46% |
| `severe-storm` | BALANCED | 5.6% |

The median gap is 0%, below the 10% threshold that would justify proposing CP-SAT (ADR-0004).

## Exit criterion: "3 distinct strategies per scenario", partly met

| Scenario | Distinct plans | Impact-hours (CF / MR / BAL) |
|---|---|---|
| substation-riverside | 1 (single repair) | 413.4 / 413.4 / 413.4 |
| power-telecom-combined | 1 (two repairs on different crews; no contention) | 440.9 / 440.9 / 440.9 |
| river-flood | 3 (different orderings, equal outcome) | 914.8 / 914.8 / 914.8 |
| severe-storm | 3 (genuinely different outcomes) | 727.6 / **662.5** / 733.3 |

When there is nothing to contend for, every sensible policy produces the same plan. Forcing differences would mean deliberately scheduling worse plans. Instead, the UI and API say plainly that the policies agree for that incident (`identical_to`). The severe-storm scenario was added so that the trade-off between policies is visible: CRITICAL_FIRST restores SUB-02 first (hospital feed), while BALANCED starts with PDN-01.

## Defects found and fixed during the phase

- **Migration dropping agent state:** autogenerated migration 0004 tried to drop the LangGraph checkpoint tables, which Alembic does not model. The drops were removed, and `env.py` now ignores `lg_*` tables. `alembic check` reports no drift.
- **Validator crash:** a plan referencing an unknown asset crashed the validator inside the V-008 re-simulation. Malformed plans are now reported.
- **Over-recorded prerequisites:** every earlier action in a bundle was recorded as a prerequisite. Only road access counts now.
- **Identical plans under slack inventory:** with spare resources, all policies produced the same plan. The inventory was tightened and the identity is now shown in the UI.
- **Simulation Lab click target:** the History panel overlapped the scenario list when the Run panel shrank (E2E timeouts). Fixed.
- **Chart colours:** the first strategy colours failed colour-vision-deficiency and lightness checks. They were replaced with the validated reference palette.

## Open items / known gaps

- **Approval, rejection, execution, verification and auth/roles are Phase 5**, along with the execution-time rules V-010…V-012. Strategy and inventory endpoints are unauthenticated until then (attributed to `local:operator`).
- **The scheduler is a heuristic.** Its gap to the brute-force optimum is measured only on instances with at most 7 actions.
- **The risk score weights are design choices, not calibrated.** They are documented in RECOVERY_OPTIMIZATION §4.
- **The live LLM is still not exercised.** STRATEGIST rationales were tested with the deterministic provider and with a scripted "hallucinating" provider. No live API was called: there is no key on this machine, and live calls cost money and need your approval.
