"""Action catalogue: which recovery actions exist for an incident, and what each costs.

Repair/replacement figures come from each asset's `recovery_profile` in the synthetic dataset.
Temporary-power figures below are documented assumptions of the synthetic model.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from app.graph.model import AssetCategory, PhysicalCondition, ServiceType, TwinSnapshot
from app.recovery.model import (
    MOBILIZATION_MINUTES,
    AccessGroup,
    ActionSpec,
    ActionType,
    ResourceUse,
)
from app.simulation.engine import flooded_assets
from app.simulation.model import (
    AreaFloodEvent,
    AssetFailureEvent,
    EventKind,
    InitiatingEvent,
    SimulationResult,
)

REPLACE_COST_FACTOR = 3
GENERATOR_DEPLOY_MINUTES = 60
GENERATOR_SUPPLY_MINUTES = 72 * 60
REFUEL_MINUTES = 90
REFUEL_SUPPLY_MINUTES = 12 * 60
TEMP_POWER_MIN_CRITICALITY = 80
FUEL_L_PER_HOUR: dict[AssetCategory, int] = {
    AssetCategory.HOSPITAL: 150,
    AssetCategory.DATA_CENTER: 120,
    AssetCategory.WATER_TREATMENT: 200,
    AssetCategory.WATER_PUMPING: 100,
}
DEFAULT_FUEL_L_PER_HOUR = 60


@dataclass(frozen=True, slots=True)
class Damage:
    code: str
    condition: PhysicalCondition
    t_minutes: int


def incident_damage(snapshot: TwinSnapshot, events: Sequence[InitiatingEvent]) -> dict[str, Damage]:
    """What the incident physically damages, and when (first damage wins)."""
    damage: dict[str, Damage] = {}
    for e in sorted(events, key=lambda e: e.t_minutes):
        if isinstance(e, AssetFailureEvent):
            hits = [(e.asset_code, PhysicalCondition(e.condition))]
        elif isinstance(e, AreaFloodEvent):
            hits = [(c, PhysicalCondition.DAMAGED) for c in flooded_assets(snapshot, e)]
        else:
            continue
        for code, condition in hits:
            if code not in damage:
                damage[code] = Damage(code, condition, e.t_minutes)
    return damage


def _access(snapshot: TwinSnapshot, code: str) -> tuple[AccessGroup, ...]:
    groups: dict[str, list[str]] = {}
    ks: dict[str, int] = {}
    for d in snapshot.dependencies:
        if d.dependent == code and d.service_type is ServiceType.ACCESS:
            groups.setdefault(d.redundancy_group, []).append(d.provider)
            ks[d.redundancy_group] = d.min_required
    return tuple(
        AccessGroup(k=ks[g], providers=tuple(sorted(p))) for g, p in sorted(groups.items())
    )


def repair_actions(snapshot: TwinSnapshot, damage: dict[str, Damage]) -> list[ActionSpec]:
    out = []
    for code in sorted(damage):
        d = damage[code]
        asset = snapshot.asset(code)
        profile = asset.recovery_profile
        if profile is None:
            continue
        replace = d.condition is PhysicalCondition.DESTROYED
        duration = profile.replace_minutes if replace else profile.repair_minutes
        out.append(
            ActionSpec(
                key=f"{'REPLACE' if replace else 'REPAIR'}:{code}",
                type=ActionType.REPLACE if replace else ActionType.REPAIR,
                asset_code=code,
                duration_minutes=duration,
                resources=(
                    ResourceUse(resource=f"crew:{profile.trade.value}", units=1, minutes=duration),
                ),
                consumables=dict(profile.replace_parts if replace else profile.parts),
                cost=profile.cost * (REPLACE_COST_FACTOR if replace else 1),
                earliest_minutes=d.t_minutes + MOBILIZATION_MINUTES,
                access=_access(snapshot, code),
                trade=profile.trade.value,
                crew_size=profile.crew_size,
            )
        )
    return out


def _power_affected(no_action: SimulationResult) -> dict[str, int]:
    """Assets that lose POWER at some point without intervention -> first time they do."""
    first: dict[str, int] = {}
    for e in no_action.events:
        if e.kind is not EventKind.STATUS_CHANGED or not e.asset_code:
            continue
        causes = e.details.get("causes", [])
        if any(
            c.get("service_type") == "POWER" and c.get("kind") in ("BACKUP", "DEPENDENCY")
            for c in causes
        ):
            first.setdefault(e.asset_code, e.t_minutes)
    return first


def temporary_power_actions(
    snapshot: TwinSnapshot, damage: dict[str, Damage], no_action: SimulationResult
) -> list[ActionSpec]:
    """Mobile generators for critical intact assets that lose power, and refuelling for those
    whose own backup runs out. Whether they are worth it is decided by the scheduler."""
    exhausted = {
        e.asset_code
        for e in no_action.events
        if e.kind is EventKind.BACKUP_EXHAUSTED and e.asset_code
    }
    out: list[ActionSpec] = []
    for code, t_lost in sorted(_power_affected(no_action).items()):
        asset = snapshot.asset(code)
        if (
            code in damage
            or asset.category is AssetCategory.DEMAND_ZONE
            or asset.criticality < TEMP_POWER_MIN_CRITICALITY
        ):
            continue
        rate = FUEL_L_PER_HOUR.get(asset.category, DEFAULT_FUEL_L_PER_HOUR)
        out.append(
            ActionSpec(
                key=f"DEPLOY_MOBILE_GENERATOR:{code}",
                type=ActionType.DEPLOY_MOBILE_GENERATOR,
                asset_code=code,
                duration_minutes=GENERATOR_DEPLOY_MINUTES,
                resources=(
                    ResourceUse(
                        resource="crew:ELECTRICAL", units=1, minutes=GENERATOR_DEPLOY_MINUTES
                    ),
                    ResourceUse(
                        resource="mobile_generator",
                        units=1,
                        minutes=GENERATOR_DEPLOY_MINUTES + GENERATOR_SUPPLY_MINUTES,
                    ),
                ),
                consumables={"fuel_l": rate * GENERATOR_SUPPLY_MINUTES // 60},
                cost=5_000,
                earliest_minutes=t_lost + MOBILIZATION_MINUTES if t_lost else MOBILIZATION_MINUTES,
                access=_access(snapshot, code),
                supplies_minutes=GENERATOR_SUPPLY_MINUTES,
                trade="ELECTRICAL",
                crew_size=2,
            )
        )
        if code in exhausted and asset.backup_power_hours:
            out.append(
                ActionSpec(
                    key=f"REFUEL_BACKUP:{code}",
                    type=ActionType.REFUEL_BACKUP,
                    asset_code=code,
                    duration_minutes=REFUEL_MINUTES,
                    resources=(
                        ResourceUse(resource="fuel_truck", units=1, minutes=REFUEL_MINUTES),
                    ),
                    consumables={"fuel_l": rate * REFUEL_SUPPLY_MINUTES // 60},
                    cost=1_000,
                    earliest_minutes=t_lost + MOBILIZATION_MINUTES
                    if t_lost
                    else MOBILIZATION_MINUTES,
                    access=_access(snapshot, code),
                    supplies_minutes=REFUEL_SUPPLY_MINUTES,
                )
            )
    return out
