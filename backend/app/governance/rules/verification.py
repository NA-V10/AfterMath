"""Recovery verification (GUARDIAN, docs/RECOVERY_OPTIMIZATION.md §7). Pure.

Compares the executed recovery with the counterfactual "no recovery, same horizon" and with the
plan's expectation. Distinguishes repaired (condition INTACT) from functionally restored
(OPERATIONAL): a repaired asset can still be down because something it needs is not.
"""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict

from app.graph.model import AssetCategory, PhysicalCondition, TwinSnapshot
from app.recovery.model import ActionType, ScheduledAction
from app.simulation.model import AssetState, CauseKind, FunctionalStatus, SimulationResult


class AssetOutcome(BaseModel):
    model_config = ConfigDict(frozen=True)
    code: str
    name: str
    status: FunctionalStatus
    reason: str


class Restoration(BaseModel):
    model_config = ConfigDict(frozen=True)
    by_count: float  # % of infrastructure assets OPERATIONAL
    by_criticality: float  # criticality-weighted %
    by_population: float  # % of demand-zone population fully served


class VerificationResult(BaseModel):
    model_config = ConfigDict(frozen=True)
    outcome: str  # FULLY_RESTORED | PARTIALLY_RESTORED
    matches_expectation: bool
    expected_result_hash: str
    actual_result_hash: str
    repaired_assets: list[str]
    functionally_restored: list[str]
    repaired_not_functional: list[AssetOutcome]
    unresolved: list[AssetOutcome]
    before: Restoration  # without recovery, at the same horizon
    after: Restoration
    impact_score_before: float
    impact_score_after: float
    horizon_minutes: int


def _reason(state: AssetState) -> str:
    """The binding cause in plain words (first unmet requirement wins)."""
    if state.condition is not PhysicalCondition.INTACT:
        return f"physically {state.condition.value.lower()}"
    for c in state.causes:
        names = ", ".join(c.providers) or "providers"
        if c.kind is CauseKind.DEPENDENCY:
            service = c.service_type.value.lower() if c.service_type else "a required service"
            return f"{service} unavailable ({names})"
        if c.kind is CauseKind.BACKUP:
            return f"on backup power ({state.backup_remaining_minutes} min left)"
        if c.kind is CauseKind.SOFT_DEPENDENCY:
            service = c.service_type.value.lower() if c.service_type else "a supporting service"
            return f"supporting {service} lost ({names})"
    return state.status.value.lower().replace("_", " ")


def _restoration(snapshot: TwinSnapshot, states: dict[str, AssetState]) -> Restoration:
    infra = [a for a in snapshot.assets if a.category is not AssetCategory.DEMAND_ZONE]
    zones = [a for a in snapshot.assets if a.category is AssetCategory.DEMAND_ZONE]
    ok = {c for c, s in states.items() if s.status is FunctionalStatus.OPERATIONAL}
    crit_total = sum(a.criticality for a in infra) or 1
    pop_total = sum(a.population_served or 0 for a in zones) or 1
    return Restoration(
        by_count=round(100 * sum(a.code in ok for a in infra) / max(1, len(infra)), 1),
        by_criticality=round(
            100 * sum(a.criticality for a in infra if a.code in ok) / crit_total, 1
        ),
        by_population=round(
            100 * sum(a.population_served or 0 for a in zones if a.code in ok) / pop_total, 1
        ),
    )


def verify(
    snapshot: TwinSnapshot,
    actions: Sequence[ScheduledAction],
    *,
    without_recovery: SimulationResult,
    executed: SimulationResult,
    expected_result_hash: str,
) -> VerificationResult:
    before = {s.code: s for s in without_recovery.final_state}
    after = {s.code: s for s in executed.final_state}
    assets = snapshot.assets_by_code
    infra = [a.code for a in snapshot.assets if a.category is not AssetCategory.DEMAND_ZONE]
    repair_targets = sorted(
        {a.asset_code for a in actions if a.type in (ActionType.REPAIR, ActionType.REPLACE)}
    )
    repaired = [c for c in repair_targets if after[c].condition is PhysicalCondition.INTACT]

    def outcome(code: str) -> AssetOutcome:
        s = after[code]
        return AssetOutcome(code=code, name=assets[code].name, status=s.status, reason=_reason(s))

    up = FunctionalStatus.OPERATIONAL
    unresolved = [outcome(c) for c in infra if after[c].status is not up]
    return VerificationResult(
        outcome="FULLY_RESTORED" if not unresolved else "PARTIALLY_RESTORED",
        matches_expectation=executed.result_hash == expected_result_hash,
        expected_result_hash=expected_result_hash,
        actual_result_hash=executed.result_hash,
        repaired_assets=repaired,
        functionally_restored=[
            c for c in infra if after[c].status is up and before[c].status is not up
        ],
        repaired_not_functional=[outcome(c) for c in repaired if after[c].status is not up],
        unresolved=unresolved,
        before=_restoration(snapshot, before),
        after=_restoration(snapshot, after),
        impact_score_before=without_recovery.final_metrics.impact_score,
        impact_score_after=executed.final_metrics.impact_score,
        horizon_minutes=executed.horizon_minutes,
    )
