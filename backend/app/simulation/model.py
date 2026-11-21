"""Inputs and outputs of the deterministic simulation engine (pure, no I/O).

All times are integer minutes from the start of the simulation. See docs/SIMULATION_ENGINE.md.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.graph.model import ASSET_CODE_PATTERN, PhysicalCondition, PolygonGeometry, ServiceType

ENGINE_VERSION = "1.1.0"  # 1.1: BACKUP_SUPPLIED events (results for 1.0 inputs unchanged)
SCORING_VERSION = "1.0"
MAX_HORIZON_MINUTES = 14 * 24 * 60
MAX_POLYGON_VERTICES = 500

_FROZEN = ConfigDict(frozen=True, extra="forbid")


class FunctionalStatus(StrEnum):
    OPERATIONAL = "OPERATIONAL"
    DEGRADED = "DEGRADED"
    ON_BACKUP = "ON_BACKUP"
    FAILED = "FAILED"


STATUS_LEVEL: dict[FunctionalStatus, int] = {
    FunctionalStatus.OPERATIONAL: 2,
    FunctionalStatus.DEGRADED: 1,
    FunctionalStatus.ON_BACKUP: 1,
    FunctionalStatus.FAILED: 0,
}


# ------------------------------------------------------------------ initiating events
class AssetFailureEvent(BaseModel):
    model_config = _FROZEN
    kind: Literal["ASSET_FAILURE"] = "ASSET_FAILURE"
    t_minutes: int = Field(default=0, ge=0)
    asset_code: str = Field(pattern=ASSET_CODE_PATTERN)
    condition: Literal[
        PhysicalCondition.DEGRADED, PhysicalCondition.DAMAGED, PhysicalCondition.DESTROYED
    ] = PhysicalCondition.DAMAGED


class AreaFloodEvent(BaseModel):
    """Assets intersecting the polygon whose elevation is below the water level are inundated
    (DAMAGED; roads and bridges become impassable). Demand zones are not damaged by floods."""

    model_config = _FROZEN
    kind: Literal["AREA_FLOOD"] = "AREA_FLOOD"
    t_minutes: int = Field(default=0, ge=0)
    polygon: PolygonGeometry
    water_level_m: float = Field(ge=-100, le=9000)

    @model_validator(mode="after")
    def _bounded(self) -> AreaFloodEvent:
        if sum(len(r) for r in self.polygon.coordinates) > MAX_POLYGON_VERTICES:
            raise ValueError(f"flood polygon exceeds {MAX_POLYGON_VERTICES} vertices")
        return self


class AssetRestoredEvent(BaseModel):
    """A completed repair: the asset's physical condition returns to INTACT."""

    model_config = _FROZEN
    kind: Literal["ASSET_RESTORED"] = "ASSET_RESTORED"
    t_minutes: int = Field(default=0, ge=0)
    asset_code: str = Field(pattern=ASSET_CODE_PATTERN)


class BackupSuppliedEvent(BaseModel):
    """Temporary power for an asset (mobile generator or refuelling of its own backup): adds
    `minutes` of backup endurance. Used by recovery plans."""

    model_config = _FROZEN
    kind: Literal["BACKUP_SUPPLIED"] = "BACKUP_SUPPLIED"
    t_minutes: int = Field(default=0, ge=0)
    asset_code: str = Field(pattern=ASSET_CODE_PATTERN)
    minutes: int = Field(gt=0, le=MAX_HORIZON_MINUTES)


InitiatingEvent = Annotated[
    AssetFailureEvent | AreaFloodEvent | AssetRestoredEvent | BackupSuppliedEvent,
    Field(discriminator="kind"),
]


class ScoringWeights(BaseModel):
    model_config = _FROZEN
    criticality_loss: float = 0.5
    population_loss: float = 0.3
    asset_count_loss: float = 0.2

    @model_validator(mode="after")
    def _sum_to_one(self) -> ScoringWeights:
        total = self.criticality_loss + self.population_loss + self.asset_count_loss
        if abs(total - 1.0) > 1e-9:
            raise ValueError("scoring weights must sum to 1")
        return self


class SimulationConfig(BaseModel):
    model_config = _FROZEN
    horizon_minutes: int = Field(default=72 * 60, ge=1, le=MAX_HORIZON_MINUTES)
    scoring: ScoringWeights = ScoringWeights()


class InitialAssetState(BaseModel):
    """Starting point for an asset when simulating from a non-baseline picture."""

    model_config = _FROZEN
    condition: PhysicalCondition
    backup_remaining_minutes: int = Field(ge=0)


class Scenario(BaseModel):
    """A predefined scenario file (data/scenarios/*.json)."""

    model_config = _FROZEN
    key: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{1,63}$")
    name: str
    description: str
    synthetic: Literal[True]
    horizon_minutes: int = Field(ge=1, le=MAX_HORIZON_MINUTES)
    initiating_events: tuple[InitiatingEvent, ...] = Field(min_length=1)


# ------------------------------------------------------------------ outputs
class CauseKind(StrEnum):
    PHYSICAL = "PHYSICAL"  # the asset itself is damaged/degraded
    DEPENDENCY = "DEPENDENCY"  # a HARD requirement group is unmet / reduced
    SOFT_DEPENDENCY = "SOFT_DEPENDENCY"  # a SOFT requirement group is unmet
    BACKUP = "BACKUP"  # running on backup power because POWER is unmet


class Cause(BaseModel):
    model_config = _FROZEN
    kind: CauseKind
    group: str | None = None
    service_type: ServiceType | None = None
    providers: tuple[str, ...] = ()  # providers in the group that are not supplying


class AssetState(BaseModel):
    model_config = _FROZEN
    code: str
    condition: PhysicalCondition
    supply: int = Field(ge=0, le=2, description="0 none, 1 reduced, 2 full")
    status: FunctionalStatus
    on_backup: bool
    backup_remaining_minutes: int
    isolated: bool
    causes: tuple[Cause, ...] = ()


class EventKind(StrEnum):
    CONDITION_CHANGED = "CONDITION_CHANGED"
    STATUS_CHANGED = "STATUS_CHANGED"
    BACKUP_ENGAGED = "BACKUP_ENGAGED"
    BACKUP_DISENGAGED = "BACKUP_DISENGAGED"
    BACKUP_EXHAUSTED = "BACKUP_EXHAUSTED"
    BACKUP_SUPPLIED = "BACKUP_SUPPLIED"
    ISOLATION_DETECTED = "ISOLATION_DETECTED"
    ISOLATION_RESOLVED = "ISOLATION_RESOLVED"
    HORIZON_REACHED = "HORIZON_REACHED"


class SimEvent(BaseModel):
    model_config = _FROZEN
    seq: int
    t_minutes: int
    wave: int
    kind: EventKind
    asset_code: str | None = None
    from_status: FunctionalStatus | None = None
    to_status: FunctionalStatus | None = None
    details: dict[str, Any] = Field(default_factory=dict)


class ServiceAvailability(BaseModel):
    model_config = _FROZEN
    service: str
    availability: float = Field(description="criticality-weighted share of full service, 0..1")
    assets_total: int
    assets_impaired: int


class ImpactMetrics(BaseModel):
    model_config = _FROZEN
    t_minutes: int
    impact_score: float
    criticality_loss: float
    population_loss: float
    asset_count_loss: float
    status_counts: dict[FunctionalStatus, int]
    affected_population: int
    population_by_service: dict[ServiceType, int]
    service_availability: tuple[ServiceAvailability, ...]
    isolated_assets: tuple[str, ...]


class TimelinePoint(BaseModel):
    model_config = _FROZEN
    t_minutes: int
    impact_score: float
    failed: int
    impaired: int
    affected_population: int


class SimulationResult(BaseModel):
    model_config = _FROZEN
    engine_version: str
    scoring_version: str
    snapshot_hash: str
    horizon_minutes: int
    events: tuple[SimEvent, ...]
    final_state: tuple[AssetState, ...]
    final_metrics: ImpactMetrics
    peak_metrics: ImpactMetrics
    timeline: tuple[TimelinePoint, ...]
    result_hash: str
