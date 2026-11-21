"""Priority-rule serial schedule generation with bundle valuation (ADR-0004).

    plan(snapshot, incident_events, inventory, policy) -> Plan

Repeatedly: for every unscheduled candidate, form its *bundle* (the candidate plus unscheduled
road clearances needed to reach it and unscheduled repairs of damaged assets it depends on),
place the bundle at its earliest resource-feasible times, simulate, and score the reduction in
the policy's loss. Commit the best bundle. Feasibility is by construction (renewable capacity is
checked at every minute boundary; consumables are reserved) and is re-checked independently by
the validator. Deterministic: candidates are iterated in key order and ties broken by key.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from app.graph.model import TwinSnapshot
from app.recovery.catalogue import (
    Damage,
    incident_damage,
    repair_actions,
    temporary_power_actions,
)
from app.recovery.evaluate import compute_metrics, policy_loss, policy_weights, risk_score, run
from app.recovery.model import (
    PLANNING_HORIZON_MINUTES,
    ActionSpec,
    ActionType,
    Inventory,
    Plan,
    Policy,
    ScheduledAction,
    Unschedulable,
)
from app.simulation.evaluator import DependencyIndex
from app.simulation.model import InitiatingEvent

INF = 10**9


@dataclass
class _State:
    actions: list[ScheduledAction] = field(default_factory=list)
    stock: dict[str, int] = field(default_factory=dict)
    usage: dict[str, list[tuple[int, int, int]]] = field(
        default_factory=dict
    )  # res -> (start,end,units)

    def copy(self) -> _State:
        return _State(
            list(self.actions), dict(self.stock), {k: list(v) for k, v in self.usage.items()}
        )

    def open_time(self, code: str, damage: dict[str, Damage]) -> int:
        """When an asset is usable as access: now if undamaged, else when its repair ends."""
        if code not in damage:
            return 0
        for a in self.actions:
            if a.asset_code == code and a.type in (ActionType.REPAIR, ActionType.REPLACE):
                return a.end_minutes
        return INF


def _fits(state: _State, spec: ActionSpec, start: int, capacity: dict[str, int]) -> bool:
    for r in spec.resources:
        cap = capacity.get(r.resource, 0)
        if r.units > cap:
            return False
        end = start + r.minutes
        intervals = state.usage.get(r.resource, [])
        # usage only changes at interval starts; check the window start and every start inside it
        points = {start} | {s for s, _, _ in intervals if start <= s < end}
        for p in points:
            used = sum(u for s, e, u in intervals if s <= p < e)
            if used + r.units > cap:
                return False
    return True


def _access_ready(state: _State, spec: ActionSpec, damage: dict[str, Damage]) -> int:
    ready = 0
    for g in spec.access:
        opens = sorted(state.open_time(p, damage) for p in g.providers)
        ready = max(ready, opens[g.k - 1] if len(opens) >= g.k else INF)
    return ready


def _place(
    state: _State,
    spec: ActionSpec,
    damage: dict[str, Damage],
    capacity: dict[str, int],
    horizon: int,
) -> int | None:
    earliest = max(spec.earliest_minutes, _access_ready(state, spec, damage))
    if earliest >= INF:
        return None
    candidates = sorted(
        {earliest}
        | {e for r in spec.resources for _, e, _ in state.usage.get(r.resource, []) if e > earliest}
    )
    for t in candidates:
        if t + spec.duration_minutes > horizon:
            return None
        if _fits(state, spec, t, capacity):
            return t
    return None


def _commit(
    state: _State, spec: ActionSpec, start: int, rationale: str, prereqs: tuple[int, ...]
) -> ScheduledAction:
    action = ScheduledAction(
        seq=len(state.actions) + 1,
        key=spec.key,
        type=spec.type,
        asset_code=spec.asset_code,
        start_minutes=start,
        end_minutes=start + spec.duration_minutes,
        resources=spec.resources,
        consumables=dict(spec.consumables),
        cost=spec.cost,
        supplies_minutes=spec.supplies_minutes,
        trade=spec.trade,
        crew_size=spec.crew_size,
        prerequisites=prereqs,
        rationale=rationale,
    )
    state.actions.append(action)
    for r in spec.resources:
        state.usage.setdefault(r.resource, []).append((start, start + r.minutes, r.units))
    for k, v in spec.consumables.items():
        state.stock[k] = state.stock.get(k, 0) - v
    return action


def _access_prereqs(state: _State, spec: ActionSpec) -> tuple[int, ...]:
    """True scheduling precedence: road/bridge repairs this action's access relies on."""
    roads = {p for g in spec.access for p in g.providers}
    return tuple(
        a.seq
        for a in state.actions
        if a.asset_code in roads and a.type in (ActionType.REPAIR, ActionType.REPLACE)
    )


class _Planner:
    def __init__(
        self,
        snapshot: TwinSnapshot,
        events: Sequence[InitiatingEvent],
        inventory: Inventory,
        policy: Policy,
        horizon: int,
        include_temporary_power: bool,
    ) -> None:
        self.snapshot, self.events, self.inventory = snapshot, list(events), inventory
        self.policy, self.horizon = policy, horizon
        self.damage = incident_damage(snapshot, events)
        self.weights = policy_weights(snapshot, policy)
        self.index = DependencyIndex(snapshot)
        self.repairs = {s.key: s for s in repair_actions(snapshot, self.damage)}
        self.repair_of = {s.asset_code: s for s in self.repairs.values()}
        self.temporary: dict[str, ActionSpec] = {}
        if include_temporary_power:
            no_action = run(snapshot, events, [], horizon)
            self.temporary = {
                s.key: s for s in temporary_power_actions(snapshot, self.damage, no_action)
            }
        self.specs = {**self.repairs, **self.temporary}

    # -------------------------------------------------------------- bundles
    def _upstream_damaged(self, code: str, seen: set[str]) -> list[str]:
        out: list[str] = []
        for g in self.index.hard[code]:
            for p in g.providers:
                if p in seen:
                    continue
                seen.add(p)
                out += self._upstream_damaged(p, seen)
                if p in self.damage:
                    out.append(p)
        return out

    def bundle(self, state: _State, spec: ActionSpec) -> list[ActionSpec]:
        """Prerequisites first (roads, then upstream repairs in dependency order), spec last."""
        scheduled = {a.key for a in state.actions}
        chain: list[ActionSpec] = []
        targets = [spec]
        if spec.type in (ActionType.REPAIR, ActionType.REPLACE):
            targets = [
                self.repair_of[c]
                for c in self._upstream_damaged(spec.asset_code, {spec.asset_code})
                if c in self.repair_of
            ] + [spec]
        for t in targets:
            for g in t.access:
                opens = sorted((state.open_time(p, self.damage), p) for p in g.providers)
                if len(opens) >= g.k and opens[g.k - 1][0] < INF:
                    continue
                # clear the fastest closed roads needed to reach k open providers
                closed = sorted(
                    (
                        self.repair_of[p]
                        for _, p in opens
                        if p in self.repair_of and state.open_time(p, self.damage) >= INF
                    ),
                    key=lambda s: (s.duration_minutes, s.key),
                )
                need = g.k - sum(1 for o, _ in opens if o < INF)
                chain += closed[:need]
            chain.append(t)
        unique: list[ActionSpec] = []
        for s in chain:
            if s.key not in scheduled and s.key not in {u.key for u in unique}:
                unique.append(s)
        return unique

    def try_bundle(
        self, state: _State, bundle: list[ActionSpec]
    ) -> tuple[_State, list[ScheduledAction]] | str:
        need: dict[str, int] = {}
        for s in bundle:
            for k, v in s.consumables.items():
                need[k] = need.get(k, 0) + v
        short = [k for k, v in need.items() if state.stock.get(k, 0) < v]
        if short:
            return f"INSUFFICIENT_RESOURCES:{','.join(sorted(short))}"
        trial = state.copy()
        placed = []
        for s in bundle:
            start = _place(trial, s, self.damage, self.inventory.renewables, self.horizon)
            if start is None:
                missing = [
                    r.resource
                    for r in s.resources
                    if self.inventory.renewables.get(r.resource, 0) < r.units
                ]
                if missing:
                    return f"INSUFFICIENT_RESOURCES:{','.join(missing)}"
                return (
                    "NO_ACCESS" if _access_ready(trial, s, self.damage) >= INF else "BEYOND_HORIZON"
                )
            placed.append(_commit(trial, s, start, "", _access_prereqs(trial, s)))
        return trial, placed

    def loss(self, state: _State) -> float:
        return policy_loss(
            run(self.snapshot, self.events, state.actions, self.horizon), self.weights, self.horizon
        )

    def score(self, gain: float, bundle: list[ActionSpec], finish: int) -> tuple[float, ...]:
        crew_minutes = sum(
            r.units * r.minutes
            for s in bundle
            for r in s.resources
            if r.resource.startswith("crew:")
        )
        scarcity = sum(
            v / max(1, self.inventory.consumables.get(k, 1))
            for s in bundle
            for k, v in s.consumables.items()
        )
        if self.policy is Policy.CRITICAL_FIRST:
            return (gain, -finish)
        if self.policy is Policy.MAX_RESTORATION:
            return (gain / max(1.0, crew_minutes / 60), -finish)
        cost = crew_minutes / 60 + sum(s.cost for s in bundle) / 50_000 + scarcity
        return (gain / max(0.5, cost), -finish)

    # -------------------------------------------------------------- main loop
    def plan(self) -> tuple[list[ScheduledAction], list[Unschedulable]]:
        state = _State(stock=dict(self.inventory.consumables))
        remaining = dict(self.specs)
        rejected: dict[str, Unschedulable] = {}
        base = self.loss(state)
        while remaining:
            best = None
            for key in sorted(remaining):
                spec = remaining[key]
                bundle = self.bundle(state, spec)
                outcome = self.try_bundle(state, bundle)
                if isinstance(outcome, str):
                    reason, _, detail = outcome.partition(":")
                    rejected[key] = Unschedulable(
                        key=key, asset_code=spec.asset_code, reason=reason, detail=detail or reason
                    )
                    continue
                trial, placed = outcome
                gain = round(base - self.loss(trial), 6)
                finish = max(a.end_minutes for a in placed)
                rank = (*self.score(gain, bundle, finish), -len(bundle), _neg(key))
                if best is None or rank > best[0]:
                    best = (rank, key, bundle, gain, trial)
            if best is None:
                break
            _, key, bundle, gain, _trial = best
            if gain <= 0 and all(
                s.type not in (ActionType.REPAIR, ActionType.REPLACE) for s in bundle
            ):
                # Remaining candidates are temporary power with no benefit: record and stop.
                for k in sorted(remaining):
                    if remaining[k].type not in (ActionType.REPAIR, ActionType.REPLACE):
                        rejected[k] = Unschedulable(
                            key=k,
                            asset_code=remaining[k].asset_code,
                            reason="NO_BENEFIT",
                            detail="no reduction in policy loss",
                        )
                remaining = {
                    k: v
                    for k, v in remaining.items()
                    if v.type in (ActionType.REPAIR, ActionType.REPLACE)
                }
                continue
            # Re-commit on the real state with rationale (same placement as the trial).
            for s in bundle:
                start = _place(state, s, self.damage, self.inventory.renewables, self.horizon)
                assert start is not None
                why = self._rationale(s, key, gain)
                _commit(state, s, start, why, _access_prereqs(state, s))
                remaining.pop(s.key, None)
                rejected.pop(s.key, None)
            base = self.loss(state)
        for key in remaining:
            rejected.setdefault(
                key,
                Unschedulable(
                    key=key,
                    asset_code=remaining[key].asset_code,
                    reason="INSUFFICIENT_RESOURCES",
                    detail="not placeable",
                ),
            )
        return state.actions, sorted(rejected.values(), key=lambda u: u.key)

    def _rationale(self, spec: ActionSpec, driver: str, gain: float) -> str:
        if spec.key == driver:
            return (
                f"Highest {self.policy.value.lower().replace('_', ' ')} priority (gain {gain:.1f})."
            )
        return f"Prerequisite of {driver}."


def _neg(key: str) -> tuple[int, ...]:
    """Ascending-key tie-break inside a max(): invert the ordinal of every character."""
    return tuple(-ord(c) for c in key)


def plan(
    snapshot: TwinSnapshot,
    incident_events: Sequence[InitiatingEvent],
    inventory: Inventory,
    policy: Policy,
    *,
    horizon: int = PLANNING_HORIZON_MINUTES,
    include_temporary_power: bool = True,
) -> Plan:
    planner = _Planner(
        snapshot, incident_events, inventory, policy, horizon, include_temporary_power
    )
    actions, unschedulable = planner.plan()
    result = run(snapshot, incident_events, actions, horizon)
    metrics = compute_metrics(
        snapshot, result, actions, planner.damage, inventory, planner.weights, horizon
    )
    risk, parts = risk_score(snapshot, result, actions, inventory, planner.damage)
    return Plan(
        policy=policy,
        horizon_minutes=horizon,
        inventory_version=inventory.version,
        actions=actions,
        unschedulable=unschedulable,
        metrics=metrics,
        risk_score=risk,
        risk_components=parts,
        expected_result_hash=result.result_hash,
    )
