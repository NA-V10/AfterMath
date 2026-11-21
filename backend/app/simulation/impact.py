"""Impact metrics for one evaluated instant (pure). Formulae: docs/SIMULATION_ENGINE.md §5."""

from __future__ import annotations

from collections import Counter

from app.graph.model import AssetCategory, ServiceType, TwinSnapshot
from app.simulation.evaluator import DependencyIndex, Evaluation, group_level
from app.simulation.model import (
    STATUS_LEVEL,
    FunctionalStatus,
    ImpactMetrics,
    ScoringWeights,
    ServiceAvailability,
)

SERVICE_CATEGORIES: dict[str, frozenset[AssetCategory]] = {
    "healthcare": frozenset({AssetCategory.HOSPITAL}),
    "emergency_response": frozenset(
        {AssetCategory.EMERGENCY_OPS_CENTER, AssetCategory.FIRE_STATION}
    ),
    "water": frozenset(
        {AssetCategory.WATER_INTAKE, AssetCategory.WATER_TREATMENT, AssetCategory.WATER_PUMPING}
    ),
    "telecom": frozenset({AssetCategory.TELECOM_HUB, AssetCategory.TELECOM_TOWER}),
    "power": frozenset(
        {
            AssetCategory.GRID_SUPPLY,
            AssetCategory.POWER_GENERATION,
            AssetCategory.SUBSTATION,
            AssetCategory.POWER_DISTRIBUTION,
        }
    ),
    "data": frozenset({AssetCategory.DATA_CENTER}),
    "fuel": frozenset({AssetCategory.FUEL_DEPOT}),
    "transport": frozenset({AssetCategory.ROAD_SEGMENT, AssetCategory.BRIDGE}),
}


def _r(x: float) -> float:
    return round(x, 4)


def compute_metrics(
    snapshot: TwinSnapshot,
    index: DependencyIndex,
    ev: Evaluation,
    isolated: frozenset[str],
    t_minutes: int,
    weights: ScoringWeights,
) -> ImpactMetrics:
    infra = [a for a in snapshot.assets if a.category is not AssetCategory.DEMAND_ZONE]
    zones = [a for a in snapshot.assets if a.category is AssetCategory.DEMAND_ZONE]
    level = {c: STATUS_LEVEL[s] for c, s in ev.status.items()}

    total_crit = sum(a.criticality for a in infra) or 1
    crit_loss = sum(a.criticality * (2 - level[a.code]) / 2 for a in infra) / total_crit
    total_pop = sum(z.population_served or 0 for z in zones) or 1
    affected = sum(z.population_served or 0 for z in zones if level[z.code] < 2)
    pop_loss = affected / total_pop
    count_loss = sum(1 for a in infra if level[a.code] < 2) / (len(infra) or 1)
    impact = 100 * (
        weights.criticality_loss * crit_loss
        + weights.population_loss * pop_loss
        + weights.asset_count_loss * count_loss
    )

    by_service: Counter[ServiceType] = Counter()
    for z in zones:
        for g in index.groups[z.code]:
            if group_level(g, ev.supply) == 0:
                by_service[g.service_type] += z.population_served or 0

    availability = []
    for service, categories in SERVICE_CATEGORIES.items():
        members = [a for a in infra if a.category in categories]
        if not members:
            continue
        weight = sum(a.criticality for a in members) or 1
        availability.append(
            ServiceAvailability(
                service=service,
                availability=_r(sum(a.criticality * level[a.code] / 2 for a in members) / weight),
                assets_total=len(members),
                assets_impaired=sum(1 for a in members if level[a.code] < 2),
            )
        )

    counts = Counter(ev.status.values())
    return ImpactMetrics(
        t_minutes=t_minutes,
        impact_score=round(impact, 2),
        criticality_loss=_r(crit_loss),
        population_loss=_r(pop_loss),
        asset_count_loss=_r(count_loss),
        status_counts={s: counts.get(s, 0) for s in FunctionalStatus},
        affected_population=affected,
        population_by_service=dict(sorted(by_service.items())),
        service_availability=tuple(availability),
        isolated_assets=tuple(sorted(isolated)),
    )
