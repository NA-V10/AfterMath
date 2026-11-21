"""Recovery planning inputs/outputs (pure). See docs/RECOVERY_OPTIMIZATION.md."""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.simulation.model import TimelinePoint

_F = ConfigDict(frozen=True, extra="forbid")

PLANNING_HORIZON_MINUTES = 7 * 24 * 60
MOBILIZATION_MINUTES = 30


class ActionType(StrEnum):
    REPAIR = "REPAIR"  # DAMAGED / DEGRADED asset (incl. clearing a road or bridge)
    REPLACE = "REPLACE"  # DESTROYED asset
    DEPLOY_MOBILE_GENERATOR = "DEPLOY_MOBILE_GENERATOR"  # temporary power for an intact asset
    REFUEL_BACKUP = "REFUEL_BACKUP"  # extend an asset's own backup power


class Policy(StrEnum):
    CRITICAL_FIRST = "CRITICAL_FIRST"
    MAX_RESTORATION = "MAX_RESTORATION"
    BALANCED = "BALANCED"


class Inventory(BaseModel):
    """Renewable resources are units available at any time (crews per trade, generators, fuel
    trucks). Consumables are used up (parts, fuel litres, budget)."""

    model_config = _F
    version: int = Field(ge=1)
    renewables: dict[str, int]
    consumables: dict[str, int]


class ResourceUse(BaseModel):
    model_config = _F
    resource: str  # e.g. "crew:ELECTRICAL", "mobile_generator", "fuel_truck"
    units: int = Field(ge=1)
    minutes: int = Field(gt=0, description="how long the units are occupied from action start")


class AccessGroup(BaseModel):
    model_config = _F
    k: int
    providers: tuple[str, ...]


class ActionSpec(BaseModel):
    """An unscheduled candidate action."""

    model_config = _F
    key: str
    type: ActionType
    asset_code: str
    duration_minutes: int = Field(gt=0)
    resources: tuple[ResourceUse, ...]
    consumables: dict[str, int]
    cost: int = Field(ge=0)
    earliest_minutes: int = Field(ge=0)
    access: tuple[AccessGroup, ...] = ()
    supplies_minutes: int | None = None
    trade: str | None = None
    crew_size: int | None = None


class ScheduledAction(BaseModel):
    model_config = _F
    seq: int
    key: str
    type: ActionType
    asset_code: str
    start_minutes: int
    end_minutes: int
    resources: tuple[ResourceUse, ...]
    consumables: dict[str, int]
    cost: int
    supplies_minutes: int | None = None
    trade: str | None = None
    crew_size: int | None = None
    prerequisites: tuple[int, ...] = ()
    rationale: str


class Unschedulable(BaseModel):
    model_config = _F
    key: str
    asset_code: str
    reason: Literal["INSUFFICIENT_RESOURCES", "NO_ACCESS", "BEYOND_HORIZON", "NO_BENEFIT"]
    detail: str


class StrategyMetrics(BaseModel):
    model_config = _F
    impact_hours: float = Field(description="integral of impact score over the horizon / 60")
    policy_loss: float = Field(description="the policy's own weighted unserved service-hours")
    final_impact_score: float
    peak_impact_score: float
    makespan_minutes: int
    time_to_critical_services_minutes: int | None
    time_to_90pct_operational_minutes: int | None
    assets_restored: int
    unrestored_assets: list[str]
    affected_population_final: int
    total_cost: int
    crew_minutes: dict[str, int]
    consumption: dict[str, int]
    remaining: dict[str, int]
    backup_exhausted_before_restoration: list[str]
    timeline: list[TimelinePoint]


class Plan(BaseModel):
    model_config = _F
    policy: Policy
    horizon_minutes: int
    inventory_version: int
    actions: list[ScheduledAction]
    unschedulable: list[Unschedulable]
    metrics: StrategyMetrics
    risk_score: float
    risk_components: dict[str, float]
    expected_result_hash: str
