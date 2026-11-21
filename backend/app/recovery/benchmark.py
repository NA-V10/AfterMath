"""Optimality-gap benchmark for the heuristic scheduler (ADR-0004).

For small instances, every ordering of the repair actions is placed with the same serial
schedule-generation rules (earliest feasible start, same resources and access precedence) and
scored with the policy's own loss. The best ordering is the optimum *within serial SGS*; the gap
is how far the bundle-valuation heuristic falls short of it. Temporary-power actions are
excluded from both sides to keep enumeration tractable.
"""

from __future__ import annotations

import itertools
from collections.abc import Sequence

from pydantic import BaseModel

from app.graph.model import TwinSnapshot
from app.recovery.catalogue import incident_damage, repair_actions
from app.recovery.evaluate import policy_loss, policy_weights, run
from app.recovery.model import PLANNING_HORIZON_MINUTES, Inventory, Policy
from app.recovery.scheduler import _commit, _place, _State, plan
from app.simulation.model import InitiatingEvent

MAX_ACTIONS = 7


class BenchmarkRow(BaseModel):
    policy: str
    actions: int
    orderings_evaluated: int
    feasible_orderings: int
    heuristic_loss: float
    optimal_loss: float
    gap_percent: float


def brute_force(
    snapshot: TwinSnapshot,
    events: Sequence[InitiatingEvent],
    inventory: Inventory,
    policy: Policy,
    horizon: int = PLANNING_HORIZON_MINUTES,
) -> BenchmarkRow:
    damage = incident_damage(snapshot, events)
    specs = repair_actions(snapshot, damage)
    if len(specs) > MAX_ACTIONS:
        raise ValueError(f"brute force limited to {MAX_ACTIONS} actions (got {len(specs)})")
    weights = policy_weights(snapshot, policy)
    best = float("inf")
    evaluated = feasible = 0
    for order in itertools.permutations(specs):
        evaluated += 1
        state = _State(stock=dict(inventory.consumables))
        ok = True
        for s in order:
            if any(state.stock.get(k, 0) < v for k, v in s.consumables.items()):
                continue  # unaffordable: skipped, as the heuristic would
            start = _place(state, s, damage, inventory.renewables, horizon)
            if start is None:
                ok = False
                break
            _commit(state, s, start, "", ())
        if not ok:
            continue
        feasible += 1
        best = min(
            best, policy_loss(run(snapshot, events, state.actions, horizon), weights, horizon)
        )
    heuristic = plan(
        snapshot, events, inventory, policy, horizon=horizon, include_temporary_power=False
    ).metrics.policy_loss
    gap = 0.0 if best == 0 else (heuristic - best) / best * 100
    return BenchmarkRow(
        policy=policy.value,
        actions=len(specs),
        orderings_evaluated=evaluated,
        feasible_orderings=feasible,
        heuristic_loss=heuristic,
        optimal_loss=round(best, 4),
        gap_percent=round(gap, 2),
    )
