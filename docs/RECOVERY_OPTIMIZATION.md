# Recovery Strategy Engine & Optimisation Approach

**Package:** `app.recovery` (pure) · Validation: `app.governance.rules` · Decision: [ADR-0004](decisions/ADR-0004-recovery-scheduling-heuristic.md)

## 1. Problem formulation

Given the post-incident state (damaged assets, blocked roads, assets on backup) and a **resource inventory**, choose and schedule recovery actions to restore service as fast as possible, under a strategy-specific notion of "value".

This is a **resource-constrained project scheduling problem (RCPSP)** with non-renewable resources. RCPSP is NP-hard in general. Our instances are small: about 3–20 actions and 4–6 resource types.

### Actions (initial catalogue)

| Action | Target | Effect | Typical resources |
|---|---|---|---|
| `REPAIR` | DAMAGED/DEGRADED asset | Condition → INTACT at completion | crew of a matching trade (renewable), spare parts, budget |
| `REPLACE` | DESTROYED asset | Condition → INTACT | crew, major equipment (e.g. transformer), budget |
| `CLEAR_ROAD` | blocked road segment | Road open | civil crew, budget |
| `DEPLOY_MOBILE_GENERATOR` | asset with a POWER requirement | Adds a temporary POWER provider | generator unit (renewable while deployed), fuel/hour |
| `REFUEL_BACKUP` | asset ON_BACKUP | Extends `backup_remaining` | fuel, fuel truck (renewable), access |

### Resources

- **Renewable** (capacity per unit of time): crews by trade (`ELECTRICAL`, `TELECOM`, `WATER`, `CIVIL`), mobile generators, fuel trucks.
- **Non-renewable** (consumed): spare-part kinds, transformer units, fuel (litres), budget.

### Precedence

- An `ACCESS` dependency must be open when the action starts: a blocked road means `CLEAR_ROAD` comes first, or the action is unschedulable within the horizon.
- Repair has no functional precedence: you can repair a hospital's electrical room while the grid is down. **Benefit**, however, is only realised when upstream supply exists. The scheduler accounts for this through bundle valuation (below), not hard precedence.

## 2. Algorithm: priority-rule serial schedule generation with bundle valuation

We use the standard RCPSP heuristic: a **serial schedule generation scheme (SGS)** driven by **dynamic, strategy-specific priority rules**.

```
scheduled ← []; t_free ← resource calendars; stock ← non-renewable inventory
candidates ← all feasible actions (catalogue × incident state)
while candidates:
    for each candidate x (sorted by code for determinism):
        B(x)      ← minimal bundle = x ∪ its unscheduled prerequisite actions
                     (road clearing + damaged upstream providers needed for x's asset to function)
        if bundle not affordable from stock → mark x UNSCHEDULABLE(reason); continue
        ΔV(B)     ← V(state after scheduled+B) − V(state after scheduled)   # engine fixed-point evaluation
        cost(B)   ← Σ crew-hours, normalised consumables, duration to completion
        prio(x)   ← policy(ΔV, cost, urgency, …)                            # see §3
    pick the bundle with the highest priority (ties broken by min duration, then asset code)
    schedule each action in the bundle at its earliest start satisfying precedence and renewable
      capacity (resource-profile sweep); decrement stock
return Schedule(actions, unschedulable, expected curves)
```

- **Bundle valuation** fixes the main weakness of greedy restoration. A hospital whose feeder substation is also damaged has zero marginal value on its own. As a bundle, its true value is visible.
- **Urgency**: assets ON_BACKUP whose endurance runs out before their restoration get a deadline. Policies may weight minutes-to-exhaustion, which is where `REFUEL_BACKUP` and generator deployment earn their place.
- **Complexity**: about O(A² · E) engine evaluations at our scale, where A is the number of actions. For A=20 that is a few hundred fixed-point evaluations, well under 1 s.
- **Feasibility is guaranteed by construction.** An action is placed only where the resource profile has capacity and stock covers it. GUARDIAN then checks this **independently** (§5).

## 3. The three strategies (policies)

All three share the scheduler. They differ only in how they value restoration. The difference is fully documented, so the trade-offs are explainable.

| Strategy | Value function V | Priority rule |
|---|---|---|
| **S1 Critical Services First** | Σ restored capacity of *life-critical* categories (hospital, EOC, emergency services, water treatment) × criticality | Lexicographic: (life-critical ΔV, urgency of backup exhaustion, −duration) |
| **S2 Maximum Infrastructure Restoration** | Number of assets restored to OPERATIONAL (unweighted) | ΔV / crew-hours (assets per crew-hour), then −duration |
| **S3 Balanced** | Criticality-weighted restoration + population served | Weighted score: `0.4·ΔV_crit + 0.25·ΔV_pop + 0.2·urgency − 0.15·normalised_cost` (configurable, stored on the strategy) |

### Per-strategy outputs

- `objective`, ordered actions with `start/end` minutes, trade, crew, consumables
- `resource_profile` (usage over time per renewable), `consumption` (per non-renewable, with remaining headroom)
- `expected_curves`: asset restoration % and critical-service availability over time, produced by **running the simulation engine over the schedule** rather than by a separate estimate
- `time_to_critical_services`, `time_to_90pct`, `makespan`, `weighted_unserved_service_hours` (the area above the curve: the common yardstick for comparing strategies)
- `risk_score` (0–100, below), `benefits`, `limitations` (generated deterministically from metrics, e.g. "leaves 2 water nodes unrestored for 14 h"), and `rationale` (written by STRATEGIST, limited to explaining these facts)
- `unschedulable`: actions that could not fit, with reasons (`INSUFFICIENT_FUEL`, `NO_ACCESS`, `NO_SPARE_TRANSFORMER`, `BEYOND_HORIZON`)

## 4. Risk score (deterministic)

```
R1 backup-exhaustion risk  = criticality-weighted share of ON_BACKUP assets whose backup expires
                             before their scheduled restoration
R2 resource headroom risk  = 1 − min over non-renewables of (remaining / initial)
R3 concentration risk      = share of critical-path crew-hours carried by the single most-loaded crew
R4 access risk             = share of actions depending on roads inside an active flood polygon
risk = round(100 · (0.4·R1 + 0.2·R2 + 0.2·R3 + 0.2·R4), 1)
```

## 5. Validation (GUARDIAN rules, `app.governance.rules.validator`)

| Rule | Check |
|---|---|
| V-001 | Every referenced asset/road exists in the snapshot and is synthetic |
| V-002 | The action type is allowed for the asset category and condition |
| V-003 | Target asset is actually damaged/blocked/on backup in the incident state |
| V-004 | Access precedence: road open (or cleared earlier in the plan) at each action start |
| V-005 | Renewable capacity never exceeded at any minute (sweep over start/end points) |
| V-006 | Total consumption ≤ inventory snapshot, per resource |
| V-007 | Schedule integrity: `end = start + duration`, non-negative, within horizon, no duplicate actions |
| V-008 | Claimed expected outcomes equal a **fresh re-simulation** of the schedule (hash compare) |
| V-009 | `content_hash` matches the canonical hash of the stored strategy |
| V-010 | At execute time: inventory version and operational picture are unchanged since validation, or revalidation passes |
| V-011 | Strategy belongs to the incident and the incident is in a recoverable state |
| V-012 | No other strategy for this incident is executing or executed |

Validation produces a `ValidationReport` with a pass/fail entry per rule and evidence. Any failure makes the strategy `VALIDATION_FAILED`, which is terminal for that content hash.

## 6. Why not an exact solver (yet)

- At this scale, SGS with bundle valuation is fast, transparent ("this was scheduled first because…") and easy to test.
- Exact MILP/CP-SAT adds a native dependency (OR-Tools, ~30 MB) and produces solutions that are harder to explain.
- **We will measure the gap.** The test suite contains small instances (≤ 7 actions) solved by brute-force enumeration of orderings. We record the heuristic's gap on `weighted_unserved_service_hours`. If the median gap exceeds 10% on realistic instances, we revisit CP-SAT. That would be a dependency change and needs owner approval.

## 7. Verification after execution

Execution replays the approved schedule through the event engine. Verification then computes:

- `repaired_assets` (condition INTACT) vs `functionally_restored` (level 2) vs `repaired_but_not_functional` (with the binding unmet dependency as the reason)
- before/after per asset, per service and per population zone; restoration % by count, criticality-weighted and population
- `unresolved_failures` with causes; `matches_expectation` = the actual curve equals the strategy's expected curve (it must, under deterministic simulation; a mismatch indicates a defect and is flagged loudly)
