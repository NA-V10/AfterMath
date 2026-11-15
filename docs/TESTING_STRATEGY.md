# Testing Strategy

## 1. Layers

| Layer | Tooling | Scope | Runs |
|---|---|---|---|
| Unit | pytest | Pure domain: graph, simulation, recovery, validator, state machines, scoring | every commit, < 10 s |
| Property-based | Hypothesis | Invariants over generated graphs, scenarios and plans | every commit (CI profile: 200 examples; nightly: 2 000) |
| Stateful | Hypothesis `RuleBasedStateMachine` | Strategy lifecycle and governance API under arbitrary call sequences | every commit |
| Golden / scenario | pytest + snapshot JSON | Predefined scenarios → expected cascades, metrics and hashes | every commit |
| Integration | pytest + HTTPX `AsyncClient` + real Postgres (compose `db-test`) | API, persistence, transactions, audit chain | every commit (needs Docker) |
| Agent | pytest + `DeterministicProvider` + `FaultyProvider` | Workflow paths, retries, fallbacks, grounding, interrupts | every commit |
| Frontend unit | Vitest + Testing Library | Formatting, status mapping, hooks | every commit |
| E2E | Playwright (Chromium) against full compose | User journeys incl. the end-to-end demo | pre-merge / nightly |
| Static | ruff, mypy (strict for domain), import-linter, tsc, ESLint | Types and layer contracts | every commit (pre-commit) |

Coverage target: ≥ 90% branch coverage on `graph`, `simulation`, `recovery` and `governance.rules`; ≥ 75% overall. Coverage is a guide, not a goal; the properties below are what count.

## 2. Required properties (each maps to a named test)

| # | Property | Technique |
|---|---|---|
| P1 | Identical inputs → identical outputs and `result_hash` | Run twice; also run in a subprocess with a different `PYTHONHASHSEED` |
| P2 | Order independence: permuting asset/edge insertion order does not change results | Hypothesis permutations |
| P3 | The final state is a fixed point of `F` (re-applying `F` changes nothing) | Hypothesis random graphs, including cycles |
| P4 | Monotonicity: adding failures never increases any asset's level | Hypothesis pairs `E ⊆ E'` |
| P5 | Disconnected components are unaffected by failures in other components | Generated multi-component graphs |
| P6 | Redundancy: with k-of-n groups, losing ≤ n−k providers keeps the dependent serving | Generated groups |
| P7 | Backup timing: an ON_BACKUP asset fails exactly at `t + backup_minutes` unless restored first | Unit + Hypothesis |
| P8 | Restored assets (level 2) satisfy all their HARD requirement groups | Post-recovery state check |
| P9 | Plans never exceed renewable capacity at any minute, nor consumable stock | Hypothesis random inventories × incidents |
| P10 | Every action in a plan targets a valid, damaged asset; invalid references are rejected | Unit + mutation of valid plans |
| P11 | Unapproved, rejected, validation-failed or superseded strategies can never execute | Stateful machine over the API |
| P12 | A content change after approval blocks execution | Stateful machine |
| P13 | Replaying an approved execution gives the same final state and hash | Replay test |
| P14 | Audit chain verifies after any sequence of operations; UPDATE/DELETE on audit_log fails | Integration |
| P15 | LLM text mentioning entities absent from tool output fails the grounding check | Agent tests |

## 3. Scenario golden tests (written with the dataset in Phase 1–2)

For each predefined scenario we hand-derive and assert:
- the set of FAILED assets at t=0 and at the horizon
- backup exhaustion times (e.g. HOS-02 at t=240)
- assets that must *not* be affected (e.g. the western grid when SUB-02 fails)
- the impact score within the scoring version (exact value)

## 4. Recovery quality benchmark

Instances with ≤ 7 actions are solved by brute force over all orderings with the same SGS placement. The benchmark records the heuristic's gap on `weighted_unserved_service_hours`. The suite asserts that the gap is 0 on the three predefined scenarios and reports (does not assert) the distribution on random instances. The report goes in `docs/reports/`.

## 5. E2E journeys (Playwright)

1. Twin: open the map, click SUB-02, the details panel shows downstream assets, and the graph highlights the same set.
2. Lab: run "Riverside substation failure", the timeline shows waves, and the map colours match the API state.
3. Full demo: free-text report → analyse → 3 strategies → approve one → execute → verification shows restored services → audit lists every step.
4. Governance negatives: the reject button disables execute; a direct API call returns 409.
5. Degraded mode: LLM provider misconfigured → the workflow completes with a visible "deterministic fallback" badge.

## 6. Honesty rules for reporting

Test results are reported exactly as the runner outputs them. Skipped tests (e.g. integration tests without Docker) are reported as skipped, not passed.
