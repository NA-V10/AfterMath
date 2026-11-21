"""API DTOs for scenarios, simulations, the operational picture and incidents.

Engine output models (AssetState, ImpactMetrics, SimEvent, TimelinePoint) are re-used directly:
they are the engine's public contract and keeping one definition avoids drift.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.simulation.criticality import CriticalityEntry
from app.simulation.model import (
    MAX_HORIZON_MINUTES,
    AssetState,
    FunctionalStatus,
    ImpactMetrics,
    InitiatingEvent,
    TimelinePoint,
)

_IN = ConfigDict(extra="forbid")


class ScenarioOut(BaseModel):
    key: str
    name: str
    description: str
    horizon_minutes: int
    initiating_events: list[InitiatingEvent]
    content_hash: str
    version: int
    synthetic: Literal[True] = True


class SimulationRequest(BaseModel):
    """Exactly one source of initiating events: a scenario, an incident, or explicit events."""

    model_config = _IN
    scenario_key: str | None = Field(default=None, max_length=64)
    incident_id: uuid.UUID | None = None
    initiating_events: list[InitiatingEvent] | None = Field(
        default=None, min_length=1, max_length=50
    )
    horizon_minutes: int | None = Field(default=None, ge=1, le=MAX_HORIZON_MINUTES)
    label: str | None = Field(default=None, max_length=120)
    apply_to_picture: bool = False

    @model_validator(mode="after")
    def _one_source(self) -> SimulationRequest:
        sources = [self.scenario_key, self.incident_id, self.initiating_events]
        if sum(s is not None for s in sources) != 1:
            raise ValueError("provide exactly one of scenario_key, incident_id, initiating_events")
        return self


class SimulationSummary(BaseModel):
    id: uuid.UUID
    created_at: datetime
    label: str | None
    kind: str
    status: Literal["COMPLETED", "FAILED"]
    scenario_key: str | None
    incident_id: uuid.UUID | None
    horizon_minutes: int
    impact_score: float | None
    peak_impact_score: float | None
    failed_count: int | None
    affected_population: int | None
    result_hash: str | None
    dataset_version: str
    engine_version: str
    duration_ms: float | None
    synthetic: Literal[True] = True


class SimulationDetail(SimulationSummary):
    initiating_events: list[InitiatingEvent]
    snapshot_hash: str
    scoring_version: str
    final_state: list[AssetState]
    final_metrics: ImpactMetrics | None
    peak_metrics: ImpactMetrics | None
    timeline: list[TimelinePoint]
    error: dict[str, str] | None


class StatusDifference(BaseModel):
    code: str
    a: FunctionalStatus
    b: FunctionalStatus


class SimulationComparison(BaseModel):
    a: SimulationSummary
    b: SimulationSummary
    impact_delta: float = Field(description="b - a, final impact score")
    affected_population_delta: int
    failed_only_in_a: list[str]
    failed_only_in_b: list[str]
    failed_in_both: list[str]
    status_differences: list[StatusDifference]


class ReplayResult(BaseModel):
    simulation_id: uuid.UUID
    original_hash: str
    replay_hash: str
    hash_matches: bool
    snapshot_matches: bool = Field(description="False if the twin changed since the original run")


class OperationalPicture(BaseModel):
    source: Literal["baseline", "simulation"]
    simulation_id: uuid.UUID | None
    label: str | None
    changed_at: datetime | None
    as_of_minutes: int = Field(description="Simulated time the picture reflects")
    stale: bool = Field(description="True if the twin changed after this picture was applied")
    states: list[AssetState]
    metrics: ImpactMetrics


class PictureResetRequest(BaseModel):
    model_config = _IN
    reason: str | None = Field(default=None, max_length=300)


class CriticalityReport(BaseModel):
    dataset_version: str
    horizon_minutes: int
    method: Literal["N-1 simulation"] = "N-1 simulation"
    entries: list[CriticalityEntry]


# ------------------------------------------------------------------ incidents
IncidentType = Literal[
    "POWER_FAILURE", "FLOODING", "TELECOM_OUTAGE", "WATER_DISRUPTION", "EQUIPMENT_FAILURE",
    "COMBINED",
]  # fmt: skip
Severity = Literal["LOW", "MODERATE", "HIGH", "CRITICAL"]


class StructuredIncidentCreate(BaseModel):
    model_config = _IN
    source: Literal["STRUCTURED"]
    title: str = Field(min_length=3, max_length=160)
    incident_type: IncidentType
    severity: Severity
    occurred_at: datetime | None = None
    initiating_events: list[InitiatingEvent] = Field(min_length=1, max_length=50)


class FreeTextIncidentCreate(BaseModel):
    model_config = _IN
    source: Literal["FREE_TEXT"]
    raw_report: str = Field(min_length=10, max_length=10_000)
    occurred_at: datetime | None = None


IncidentCreate = Annotated[
    StructuredIncidentCreate | FreeTextIncidentCreate, Field(discriminator="source")
]


class IncidentOut(BaseModel):
    id: uuid.UUID
    reference: str
    source: str
    status: str
    title: str | None
    incident_type: str | None
    severity: str | None
    occurred_at: datetime | None
    raw_report: str | None
    initiating_events: list[InitiatingEvent] | None
    confidence: float | None
    missing_information: list[str]
    created_at: datetime
    synthetic: Literal[True] = True
    analysis_available: bool = Field(
        description="Free-text incidents need SENTINEL analysis (Phase 3) before simulation."
    )
