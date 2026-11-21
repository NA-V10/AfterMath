"""Structured agent outputs (docs/AGENT_DESIGN.md §3).

Two kinds of models live here:
* LLM-facing schemas (`*Extraction`, `Briefing`, `Narrative`) — the ONLY things an LLM may produce:
  extracted text spans or prose. They contain no codes, statuses, numbers or actions that the
  system acts on without deterministic resolution.
* Agent outputs (`IncidentAssessment`, `DependencyAnalysis`, `SimulationSummary`) — assembled from
  deterministic tool results, plus the (grounding-checked) prose.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.simulation.model import InitiatingEvent

IncidentType = Literal[
    "POWER_FAILURE", "FLOODING", "TELECOM_OUTAGE", "WATER_DISRUPTION", "EQUIPMENT_FAILURE",
    "COMBINED",
]  # fmt: skip
Severity = Literal["LOW", "MODERATE", "HIGH", "CRITICAL"]
Condition = Literal["DEGRADED", "DAMAGED", "DESTROYED"]

_F = ConfigDict(frozen=True, extra="forbid")


# ------------------------------------------------------------------ LLM-facing
class AssetMention(BaseModel):
    model_config = _F
    quote: str = Field(description="Exact words from the report that refer to one facility.")
    role: Literal["damaged", "affected"] = Field(
        description="'damaged': the report says this facility itself failed or was hit. "
        "'affected': it is only suffering consequences (e.g. running on a generator)."
    )
    condition: Condition = Field(description="For damaged facilities: how badly.")


class IncidentExtraction(BaseModel):
    """SENTINEL's LLM step: read an untrusted report and extract what it states."""

    model_config = _F
    incident_type: IncidentType
    severity: Severity
    asset_mentions: list[AssetMention] = Field(max_length=10)
    reported_consequences: list[str] = Field(default_factory=list, max_length=8)
    missing_information: list[str] = Field(default_factory=list, max_length=8)


class Briefing(BaseModel):
    model_config = _F
    text: str = Field(max_length=1500)


class Narrative(BaseModel):
    model_config = _F
    text: str = Field(max_length=1500)


# ------------------------------------------------------------------ shared
class Grounding(BaseModel):
    model_config = _F
    checked: bool
    ok: bool
    unknown_asset_codes: list[str] = Field(default_factory=list)
    unknown_numbers: list[str] = Field(default_factory=list)


class Evidence(BaseModel):
    model_config = _F
    kind: Literal["REPORT_SPAN", "ASSET_MATCH", "OPERATOR_NOTE"]
    text: str
    start: int | None = None
    end: int | None = None
    asset_code: str | None = None
    score: float | None = None


class AssetMatch(BaseModel):
    model_config = _F
    code: str
    name: str
    quote: str
    method: Literal["code", "name", "keywords", "operator"]
    score: float = Field(ge=0, le=1)
    role: Literal["damaged", "affected"]
    condition: Condition


# ------------------------------------------------------------------ agent outputs
class IncidentAssessment(BaseModel):
    model_config = _F
    source: Literal["STRUCTURED", "REPORT"]
    incident_type: IncidentType
    severity: Severity
    affected_assets: list[AssetMatch]
    initiating_events: list[InitiatingEvent]
    confidence: float = Field(ge=0, le=1)
    evidence: list[Evidence]
    missing_information: list[str]
    reported_consequences: list[str] = Field(
        description="Consequences stated in the report; NOT authoritative (see ORACLE)."
    )
    needs_clarification: bool
    extraction_provider: str


class DownstreamAsset(BaseModel):
    model_config = _F
    code: str
    depth: int


class SinglePointOfFailure(BaseModel):
    model_config = _F
    code: str
    critical_failed: list[str]


class RedundancyEffect(BaseModel):
    model_config = _F
    dependent: str
    group: str
    service_type: str
    providers_lost: list[str]
    providers_remaining: int
    required: int
    mode: Literal["HARD", "SOFT"]
    effect: Literal["REDUNDANCY_REDUCED", "REQUIREMENT_LOST", "SUPPORT_LOST"]


class DependencyAnalysis(BaseModel):
    model_config = _F
    focus_assets: list[str]
    downstream: list[DownstreamAsset]
    single_points_of_failure: list[SinglePointOfFailure]
    redundancy_effects: list[RedundancyEffect]
    briefing: str
    briefing_source: str
    grounding: Grounding


class FailureChain(BaseModel):
    model_config = _F
    asset: str
    status: str
    chain: list[str] = Field(description="asset <- provider <- ... <- initiating asset")


class BackupDeadline(BaseModel):
    model_config = _F
    asset: str
    exhausts_at_minutes: int
    exhausted_within_horizon: bool


class SimulationSummary(BaseModel):
    model_config = _F
    simulation_id: str
    result_hash: str
    horizon_minutes: int
    impact_score: float
    peak_impact_score: float
    failed: int
    on_backup: int
    degraded: int
    affected_population: int
    key_chains: list[FailureChain]
    deadlines: list[BackupDeadline]
    narrative: str
    narrative_source: str
    grounding: Grounding
