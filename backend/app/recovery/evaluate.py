"""Evaluate a recovery schedule by simulating it (pure, deterministic).

The incident's own events plus one ASSET_RESTORED per completed repair and one BACKUP_SUPPLIED
per temporary-power action are replayed through the simulation engine, so cascades, redundancy
and backup deadlines are accounted for by the same model that assessed the incident.
"""

from __future__ import annotations

from collections.abc import Sequence

from app.graph.model import AssetCategory, TwinSnapshot
from app.recovery.catalogue import Damage
from app.recovery.model import (
    ActionType,
    Inventory,
    Policy,
    ScheduledAction,
    StrategyMetrics,
)
from app.simulation.engine import simulate
from app.simulation.model import (
    STATUS_LEVEL,
    AssetRestoredEvent,
    BackupSuppliedEvent,
    EventKind,
    FunctionalStatus,
    InitiatingEvent,
    SimulationConfig,
    SimulationResult,
)

LIFE_CRITICAL = frozenset(
    {
        AssetCategory.HOSPITAL,
        AssetCategory.EMERGENCY_OPS_CENTER,
        AssetCategory.FIRE_STATION,
        AssetCategory.WATER_TREATMENT,
        AssetCategory.WATER_PUMPING,
    }
)
ZONE_POPULATION_DIVISOR = 500  # BALANCED: a zone weighs population/500 (180k residents ≈ 360)


def policy_weights(snapshot: TwinSnapshot, policy: Policy) -> dict[str, float]:
    """How much each asset's lost service matters to a policy (docs/RECOVERY_OPTIMIZATION.md §3)."""
    weights: dict[str, float] = {}
    for a in snapshot.assets:
        zone = a.category is AssetCategory.DEMAND_ZONE
        if policy is Policy.CRITICAL_FIRST:
            w = (
                0.0
                if zone
                else (100.0 * a.criticality if a.category in LIFE_CRITICAL else 0.1 * a.criticality)
            )
        elif policy is Policy.MAX_RESTORATION:
            w = 0.0 if zone else 1.0
        else:
            w = (
                (a.population_served or 0) / ZONE_POPULATION_DIVISOR
                if zone
                else float(a.criticality)
            )
        weights[a.code] = w
    return weights


def recovery_events(
    incident_events: Sequence[InitiatingEvent], actions: Sequence[ScheduledAction]
) -> list[InitiatingEvent]:
    events: list[InitiatingEvent] = list(incident_events)
    for a in sorted(actions, key=lambda a: (a.end_minutes, a.seq)):
        if a.type in (ActionType.REPAIR, ActionType.REPLACE):
            events.append(AssetRestoredEvent(t_minutes=a.end_minutes, asset_code=a.asset_code))
        else:
            assert a.supplies_minutes is not None
            events.append(
                BackupSuppliedEvent(
                    t_minutes=a.end_minutes, asset_code=a.asset_code, minutes=a.supplies_minutes
                )
            )
    return events


def run(
    snapshot: TwinSnapshot,
    incident_events: Sequence[InitiatingEvent],
    actions: Sequence[ScheduledAction],
    horizon: int,
) -> SimulationResult:
    return simulate(
        snapshot,
        recovery_events(incident_events, actions),
        SimulationConfig(horizon_minutes=horizon),
    )


def status_intervals(
    result: SimulationResult, codes: Sequence[str]
) -> dict[str, list[tuple[int, FunctionalStatus]]]:
    """Piecewise-constant status per asset: [(from_t, status), ...] starting at t=0."""
    first: dict[str, FunctionalStatus] = {}
    changes: dict[str, list[tuple[int, FunctionalStatus]]] = {c: [] for c in codes}
    for e in result.events:
        if e.kind is EventKind.STATUS_CHANGED and e.asset_code and e.to_status and e.from_status:
            first.setdefault(e.asset_code, e.from_status)
            changes[e.asset_code].append((e.t_minutes, e.to_status))
    final = {s.code: s.status for s in result.final_state}
    out = {}
    for c in codes:
        start = first.get(c, final[c])
        out[c] = [(0, start), *changes[c]]
    return out


def policy_loss(result: SimulationResult, weights: dict[str, float], horizon: int) -> float:
    """Σ_a w_a ∫ (2 - level_a(t))/2 dt, in weighted hours."""
    total = 0.0
    for code, segs in status_intervals(result, list(weights)).items():
        w = weights[code]
        if not w:
            continue
        for i, (t, status) in enumerate(segs):
            end = segs[i + 1][0] if i + 1 < len(segs) else horizon
            total += w * (2 - STATUS_LEVEL[status]) / 2 * max(0, end - t)
    return round(total / 60, 4)


def impact_hours(result: SimulationResult, horizon: int) -> float:
    pts = sorted({p.t_minutes: p for p in result.timeline}.values(), key=lambda p: p.t_minutes)
    total = 0.0
    for i, p in enumerate(pts):
        end = pts[i + 1].t_minutes if i + 1 < len(pts) else horizon
        total += p.impact_score * max(0, end - p.t_minutes)
    return round(total / 60, 2)


def _settled_ok_time(
    segs: list[tuple[int, FunctionalStatus]], ok: set[FunctionalStatus]
) -> int | None:
    """Time from which the asset stays in an ok status until the horizon (None if it doesn't)."""
    if segs[-1][1] not in ok:
        return None
    t = segs[-1][0]
    for i in range(len(segs) - 2, -1, -1):
        if segs[i][1] in ok:
            t = segs[i][0]
        else:
            break
    return t


def compute_metrics(
    snapshot: TwinSnapshot,
    result: SimulationResult,
    actions: Sequence[ScheduledAction],
    damage: dict[str, Damage],
    inventory: Inventory,
    weights: dict[str, float],
    horizon: int,
) -> StrategyMetrics:
    infra = [a for a in snapshot.assets if a.category is not AssetCategory.DEMAND_ZONE]
    segs = status_intervals(result, [a.code for a in snapshot.assets])
    serving = {FunctionalStatus.OPERATIONAL, FunctionalStatus.DEGRADED}

    critical = [a.code for a in infra if a.category in LIFE_CRITICAL]
    crit_times = [_settled_ok_time(segs[c], serving) for c in critical]
    t_crit = (
        None
        if any(t is None for t in crit_times)
        else max([0, *(t for t in crit_times if t is not None)])
    )

    # first time >= 90% of infrastructure is OPERATIONAL and stays so
    times = sorted({t for c in segs for t, _ in segs[c]})
    t90 = None
    for t in times:
        ok_from_t = all(
            sum(1 for a in infra if _status_at(segs[a.code], tt) is FunctionalStatus.OPERATIONAL)
            >= 0.9 * len(infra)
            for tt in times
            if tt >= t
        )
        if ok_from_t:
            t90 = t
            break

    final = {s.code: s.status for s in result.final_state}
    exhausted = {
        e.asset_code for e in result.events if e.kind is EventKind.BACKUP_EXHAUSTED and e.asset_code
    }
    restored_at = {
        a.asset_code: a.end_minutes
        for a in actions
        if a.type in (ActionType.REPAIR, ActionType.REPLACE)
    }
    exhausted_first = sorted(
        e.asset_code
        for e in result.events
        if e.kind is EventKind.BACKUP_EXHAUSTED
        and e.asset_code
        and e.t_minutes < max((a.end_minutes for a in actions), default=horizon)
    )

    consumption: dict[str, int] = {}
    crew: dict[str, int] = {}
    for a in actions:
        for k, v in a.consumables.items():
            consumption[k] = consumption.get(k, 0) + v
        for r in a.resources:
            if r.resource.startswith("crew:"):
                crew[r.resource[5:]] = crew.get(r.resource[5:], 0) + r.units * r.minutes
    return StrategyMetrics(
        impact_hours=impact_hours(result, horizon),
        policy_loss=policy_loss(result, weights, horizon),
        final_impact_score=result.final_metrics.impact_score,
        peak_impact_score=result.peak_metrics.impact_score,
        makespan_minutes=max((a.end_minutes for a in actions), default=0),
        time_to_critical_services_minutes=t_crit,
        time_to_90pct_operational_minutes=t90,
        assets_restored=sum(1 for c in damage if c in restored_at),
        unrestored_assets=sorted(
            a.code for a in infra if final[a.code] is not FunctionalStatus.OPERATIONAL
        ),
        affected_population_final=result.final_metrics.affected_population,
        total_cost=sum(a.cost for a in actions),
        crew_minutes=dict(sorted(crew.items())),
        consumption=dict(sorted(consumption.items())),
        remaining={k: inventory.consumables.get(k, 0) - v for k, v in sorted(consumption.items())},
        backup_exhausted_before_restoration=sorted(set(exhausted_first) & exhausted),
        timeline=list(result.timeline),
    )


def _status_at(segs: list[tuple[int, FunctionalStatus]], t: int) -> FunctionalStatus:
    current = segs[0][1]
    for start, status in segs:
        if start <= t:
            current = status
        else:
            break
    return current


def risk_score(
    snapshot: TwinSnapshot,
    result: SimulationResult,
    actions: Sequence[ScheduledAction],
    inventory: Inventory,
    damage: dict[str, Damage],
) -> tuple[float, dict[str, float]]:
    """docs/RECOVERY_OPTIMIZATION.md §4 (deterministic, 0-100)."""
    crit = {a.code: a.criticality for a in snapshot.assets}
    on_backup = {
        e.asset_code for e in result.events if e.kind is EventKind.BACKUP_ENGAGED and e.asset_code
    }
    exhausted = {
        e.asset_code for e in result.events if e.kind is EventKind.BACKUP_EXHAUSTED and e.asset_code
    }
    r1 = (
        (sum(crit[c] for c in exhausted & on_backup) / sum(crit[c] for c in on_backup))
        if on_backup
        else 0.0
    )

    used: dict[str, int] = {}
    for a in actions:
        for k, v in a.consumables.items():
            used[k] = used.get(k, 0) + v
    headroom = [
        (inventory.consumables.get(k, 0) - v) / inventory.consumables[k]
        for k, v in used.items()
        if inventory.consumables.get(k)
    ]
    r2 = 1 - min(headroom) if headroom else 0.0

    crew: dict[str, int] = {}
    for a in actions:
        for r in a.resources:
            if r.resource.startswith("crew:"):
                crew[r.resource] = crew.get(r.resource, 0) + r.minutes
    r3 = max(crew.values()) / sum(crew.values()) if crew else 0.0

    damaged_roads = {
        c
        for c in damage
        if snapshot.asset(c).category in (AssetCategory.ROAD_SEGMENT, AssetCategory.BRIDGE)
    }
    dependent = [
        a
        for a in actions
        if any(
            d.provider in damaged_roads
            for d in snapshot.dependencies
            if d.dependent == a.asset_code and d.service_type.value == "ACCESS"
        )
    ]
    r4 = len(dependent) / len(actions) if actions else 0.0
    parts = {
        "backup_exhaustion": round(r1, 4),
        "resource_headroom": round(r2, 4),
        "crew_concentration": round(r3, 4),
        "access": round(r4, 4),
    }
    return round(100 * (0.4 * r1 + 0.2 * r2 + 0.2 * r3 + 0.2 * r4), 1), parts
