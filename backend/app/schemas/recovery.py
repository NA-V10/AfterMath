"""API DTOs for recovery planning (Phase 4)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.governance.rules.validator import ValidationReport
from app.recovery.model import StrategyMetrics, Unschedulable
from app.schemas.governance import ApprovalOut


class InventoryOut(BaseModel):
    version: int
    renewables: dict[str, int]
    consumables: dict[str, int]
    reason: str | None
    created_by: str
    created_at: datetime
    synthetic: Literal[True] = True


class InventoryIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    renewables: dict[str, int] = Field(min_length=1)
    consumables: dict[str, int] = Field(min_length=1)
    reason: str = Field(min_length=3, max_length=300)


class GenerateStrategiesIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    incident_id: uuid.UUID


class ActionOut(BaseModel):
    seq: int
    key: str
    action_type: str
    target_asset_code: str
    start_minutes: int
    end_minutes: int
    trade: str | None
    crew_size: int | None
    resources: list[dict[str, Any]]
    consumables: dict[str, int]
    cost: int
    supplies_minutes: int | None
    prerequisite_seqs: list[int]
    rationale: str


class StrategySummary(BaseModel):
    id: uuid.UUID
    incident_id: uuid.UUID
    planning_round: int
    policy: str
    status: str
    recommended: bool
    objective: str
    impact_hours: float
    time_to_critical_services_minutes: int | None
    time_to_90pct_operational_minutes: int | None
    makespan_minutes: int
    total_cost: int
    risk_score: float
    actions_count: int
    unschedulable_count: int
    content_hash: str
    version: int = Field(description="optimistic-concurrency version (send as expected_version)")
    created_at: datetime
    synthetic: Literal[True] = True


class StrategyDetail(StrategySummary):
    requested_by: str | None = Field(description="who asked for this planning round")
    decisions: list[ApprovalOut]
    execution_id: uuid.UUID | None
    inventory_version: int
    horizon_minutes: int
    rationale: str | None
    rationale_source: str | None
    metrics: StrategyMetrics
    risk_components: dict[str, float]
    benefits: list[str]
    limitations: list[str]
    unschedulable: list[Unschedulable]
    expected_result_hash: str
    validation_report: ValidationReport | None
    validated_at: datetime | None
    actions: list[ActionOut]
    identical_to: list[str] = Field(description="other policies in this round with the same plan")


class StrategyRound(BaseModel):
    incident_id: uuid.UUID
    planning_round: int
    recommended_strategy_id: uuid.UUID | None
    baseline_impact_hours: float = Field(description="impact-hours with no recovery action")
    baseline_timeline: list[dict[str, Any]]
    strategies: list[StrategyDetail]
