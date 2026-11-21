"""Structural criticality by exact N-1 analysis (docs/SIMULATION_ENGINE.md §6).

Each infrastructure asset is damaged on its own and the twin is simulated to the horizon. This is
exact under k-of-n redundancy and backup timing, which dominator-tree approximations are not.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from app.graph.model import AssetCategory, TwinSnapshot
from app.simulation.engine import simulate
from app.simulation.model import AssetFailureEvent, FunctionalStatus, SimulationConfig

SPOF_CRITICALITY_THRESHOLD = 80


class CriticalityEntry(BaseModel):
    model_config = ConfigDict(frozen=True)
    code: str
    static_criticality: int
    impact_score: float
    failed_assets: tuple[str, ...]  # other assets FAILED at the horizon
    critical_failed: tuple[str, ...]  # of which static criticality >= threshold
    affected_population: int
    single_point_of_failure: bool


def structural_criticality(
    snapshot: TwinSnapshot, horizon_minutes: int = 72 * 60
) -> list[CriticalityEntry]:
    config = SimulationConfig(horizon_minutes=horizon_minutes)
    crit = {a.code: a.criticality for a in snapshot.assets}
    entries = []
    for a in snapshot.assets:
        if a.category is AssetCategory.DEMAND_ZONE:
            continue
        result = simulate(snapshot, [AssetFailureEvent(asset_code=a.code)], config)
        failed = tuple(
            s.code
            for s in result.final_state
            if s.status is FunctionalStatus.FAILED and s.code != a.code
        )
        critical = tuple(
            c for c in failed
            if crit[c] >= SPOF_CRITICALITY_THRESHOLD
            and snapshot.asset(c).category is not AssetCategory.DEMAND_ZONE
        )  # fmt: skip
        entries.append(
            CriticalityEntry(
                code=a.code,
                static_criticality=a.criticality,
                impact_score=result.final_metrics.impact_score,
                failed_assets=failed,
                critical_failed=critical,
                affected_population=result.final_metrics.affected_population,
                single_point_of_failure=bool(critical),
            )
        )
    return sorted(entries, key=lambda e: (-e.impact_score, e.code))
