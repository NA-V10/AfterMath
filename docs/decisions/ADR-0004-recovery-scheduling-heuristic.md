# ADR-0004: Priority-rule serial schedule generation with independent validation

- **Status:** Proposed (Phase 0, pending owner review)
- **Date:** 2026-11-15

## Context
Recovery planning is an RCPSP with renewable (crews, generators) and non-renewable (parts, fuel, budget) resources. Plans must be feasible, explainable and distinct across three policies.

## Decision
Use a serial SGS driven by dynamic, policy-specific priority rules with bundle valuation (action + prerequisites), with marginal value computed by the simulation engine. GUARDIAN independently re-validates every plan (rules V-001..V-012). Measure the optimality gap against brute force on small instances. Details: [RECOVERY_OPTIMIZATION.md](../RECOVERY_OPTIMIZATION.md).

## Consequences
- (+) Feasible by construction and re-checked; fast; every ordering decision has a stateable reason.
- (-) Not guaranteed optimal. Mitigated by benchmarking; escalation path to OR-Tools CP-SAT requires owner approval.

## Alternatives considered
MILP/CP-SAT now (heavier dependency, less explainable); pure greedy without bundles (misses value of upstream repairs); LLM-generated plans (not trustworthy, not reproducible).
