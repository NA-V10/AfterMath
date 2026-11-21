"""ORM models. See docs/DATA_MODEL.md. Phase 1 tables: dataset_release, infrastructure_asset,
infrastructure_dependency, audit_log."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    text,
    true,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Base, created_at_col, updated_at_col, uuid_pk


def _enum_check(column: str, values: list[str]) -> str:
    quoted = ", ".join(f"'{v}'" for v in values)
    return f"{column} IN ({quoted})"


class DatasetRelease(Base):
    """Which synthetic dataset version is loaded (seeding is idempotent per version+hash)."""

    __tablename__ = "dataset_release"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    asset_count: Mapped[int] = mapped_column(Integer, nullable=False)
    dependency_count: Mapped[int] = mapped_column(Integer, nullable=False)
    basemap: Mapped[dict[str, Any]] = mapped_column(nullable=False)
    bounds: Mapped[list[Any]] = mapped_column(nullable=False)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=true())
    created_at: Mapped[datetime] = created_at_col()

    __table_args__ = (
        UniqueConstraint("name", "version"),
        CheckConstraint("is_synthetic", name="synthetic_only"),
        Index(
            "uq_dataset_release_current",
            "is_current",
            unique=True,
            postgresql_where=text("is_current"),
        ),
    )


ASSET_CATEGORIES = [
    "GRID_SUPPLY", "POWER_GENERATION", "SUBSTATION", "POWER_DISTRIBUTION", "HOSPITAL",
    "TELECOM_HUB", "TELECOM_TOWER", "DATA_CENTER", "EMERGENCY_OPS_CENTER", "FIRE_STATION",
    "WATER_INTAKE", "WATER_TREATMENT", "WATER_PUMPING", "FUEL_DEPOT", "ROAD_SEGMENT", "BRIDGE",
    "DEMAND_ZONE",
]  # fmt: skip
CONDITIONS = ["INTACT", "DEGRADED", "DAMAGED", "DESTROYED"]
SERVICE_TYPES = ["POWER", "TELECOM", "WATER", "FUEL", "DATA", "HEALTHCARE", "ACCESS"]


class InfrastructureAsset(Base):
    __tablename__ = "infrastructure_asset"

    id: Mapped[uuid.UUID] = uuid_pk()
    code: Mapped[str] = mapped_column(String(16), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    category: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    geometry: Mapped[dict[str, Any]] = mapped_column(nullable=False)
    elevation_m: Mapped[float | None] = mapped_column(Float)
    physical_condition: Mapped[str] = mapped_column(String(16), nullable=False)
    criticality: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    capacity: Mapped[float | None] = mapped_column(Float)
    capacity_unit: Mapped[str | None] = mapped_column(String(32))
    utilization: Mapped[float | None] = mapped_column(Float)
    population_served: Mapped[int | None] = mapped_column(Integer)
    is_source: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    backup_power_hours: Mapped[float | None] = mapped_column(Float)
    recovery_profile: Mapped[dict[str, Any] | None] = mapped_column()
    meta: Mapped[dict[str, Any]] = mapped_column("metadata", nullable=False, default=dict)
    dataset_version: Mapped[str] = mapped_column(String(32), nullable=False)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=true())
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __table_args__ = (
        CheckConstraint(_enum_check("category", ASSET_CATEGORIES), name="category_valid"),
        CheckConstraint(_enum_check("physical_condition", CONDITIONS), name="condition_valid"),
        CheckConstraint("criticality BETWEEN 0 AND 100", name="criticality_range"),
        CheckConstraint("utilization IS NULL OR utilization BETWEEN 0 AND 1", name="util_range"),
        CheckConstraint("is_synthetic", name="synthetic_only"),
    )


class InfrastructureDependency(Base):
    __tablename__ = "infrastructure_dependency"

    id: Mapped[uuid.UUID] = uuid_pk()
    provider_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("infrastructure_asset.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    dependent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("infrastructure_asset.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    service_type: Mapped[str] = mapped_column(String(16), nullable=False)
    mode: Mapped[str] = mapped_column(String(8), nullable=False)
    redundancy_group: Mapped[str] = mapped_column(String(48), nullable=False)
    min_required: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = created_at_col()

    provider: Mapped[InfrastructureAsset] = relationship(foreign_keys=[provider_id])
    dependent: Mapped[InfrastructureAsset] = relationship(foreign_keys=[dependent_id])

    __table_args__ = (
        UniqueConstraint("provider_id", "dependent_id", "service_type", name="uq_dependency_edge"),
        CheckConstraint("provider_id <> dependent_id", name="no_self_loop"),
        CheckConstraint(_enum_check("service_type", SERVICE_TYPES), name="service_type_valid"),
        CheckConstraint("mode IN ('HARD', 'SOFT')", name="mode_valid"),
        CheckConstraint("min_required >= 1", name="min_required_positive"),
    )


class AuditLog(Base):
    """Append-only, hash-chained audit trail (UPDATE/DELETE blocked by trigger)."""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_id: Mapped[str] = mapped_column(String(128), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(48), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(128))
    request_id: Mapped[str | None] = mapped_column(String(64), index=True)
    workflow_run_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    before: Mapped[dict[str, Any] | None] = mapped_column()
    after: Mapped[dict[str, Any] | None] = mapped_column()
    details: Mapped[dict[str, Any] | None] = mapped_column()
    prev_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)

    __table_args__ = (
        CheckConstraint("actor_type IN ('USER', 'AGENT', 'SYSTEM')", name="actor_type_valid"),
        Index("ix_audit_log_entity", "entity_type", "entity_id"),
        Index("ix_audit_log_occurred_at", "occurred_at"),
    )


# ============================================================ Phase 2
INCIDENT_SOURCES = ["MANUAL", "STRUCTURED", "FREE_TEXT", "SENSOR", "SCENARIO"]
INCIDENT_TYPES = [
    "POWER_FAILURE", "FLOODING", "TELECOM_OUTAGE", "WATER_DISRUPTION", "EQUIPMENT_FAILURE",
    "COMBINED",
]  # fmt: skip
SEVERITIES = ["LOW", "MODERATE", "HIGH", "CRITICAL"]
INCIDENT_STATUSES = [
    "REPORTED", "ANALYZING", "ANALYSIS_FAILED", "AWAITING_APPROVAL", "RECOVERING", "RECOVERED",
    "CLOSED",
]  # fmt: skip
EVIDENCE_KINDS = [
    "REPORT_SPAN", "SENSOR_READING", "ASSET_MATCH", "GEOSPATIAL_MATCH", "OPERATOR_NOTE",
]  # fmt: skip


class SimulationScenario(Base):
    __tablename__ = "simulation_scenario"

    id: Mapped[uuid.UUID] = uuid_pk()
    key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(160), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    initiating_events: Mapped[list[Any]] = mapped_column(nullable=False)
    horizon_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    is_predefined: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=true())
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __table_args__ = (CheckConstraint("is_synthetic", name="synthetic_only"),)


class Incident(Base):
    __tablename__ = "incident"

    id: Mapped[uuid.UUID] = uuid_pk()
    reference: Mapped[str] = mapped_column(String(24), nullable=False, unique=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    raw_report: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(String(160))
    incident_type: Mapped[str | None] = mapped_column(String(32))
    severity: Mapped[str | None] = mapped_column(String(16))
    occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    location: Mapped[dict[str, Any] | None] = mapped_column()
    initiating_events: Mapped[list[Any] | None] = mapped_column()
    confidence: Mapped[float | None] = mapped_column(Float)
    missing_information: Mapped[list[Any]] = mapped_column(nullable=False, default=list)
    scenario_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("simulation_scenario.id", ondelete="RESTRICT")
    )
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="REPORTED")
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=true())
    created_at: Mapped[datetime] = created_at_col()
    updated_at: Mapped[datetime] = updated_at_col()
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    __table_args__ = (
        CheckConstraint(_enum_check("source", INCIDENT_SOURCES), name="source_valid"),
        CheckConstraint(
            "incident_type IS NULL OR " + _enum_check("incident_type", INCIDENT_TYPES),
            name="type_valid",
        ),
        CheckConstraint(
            "severity IS NULL OR " + _enum_check("severity", SEVERITIES), name="severity_valid"
        ),
        CheckConstraint(_enum_check("status", INCIDENT_STATUSES), name="status_valid"),
        CheckConstraint(
            "confidence IS NULL OR confidence BETWEEN 0 AND 1", name="confidence_range"
        ),
        CheckConstraint(
            "source <> 'FREE_TEXT' OR raw_report IS NOT NULL", name="free_text_has_report"
        ),
        CheckConstraint("is_synthetic", name="synthetic_only"),
        Index("ix_incident_created_at", "created_at"),
    )


class IncidentEvidence(Base):
    __tablename__ = "incident_evidence"

    id: Mapped[uuid.UUID] = uuid_pk()
    incident_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("incident.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    content: Mapped[dict[str, Any]] = mapped_column(nullable=False)
    source_agent_execution_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    confidence: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = created_at_col()

    __table_args__ = (CheckConstraint(_enum_check("kind", EVIDENCE_KINDS), name="kind_valid"),)


class SimulationRun(Base):
    __tablename__ = "simulation_run"

    id: Mapped[uuid.UUID] = uuid_pk()
    label: Mapped[str | None] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="IMPACT")
    incident_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("incident.id", ondelete="RESTRICT"), index=True
    )
    scenario_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("simulation_scenario.id", ondelete="RESTRICT")
    )
    inputs: Mapped[dict[str, Any]] = mapped_column(nullable=False)
    snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    dataset_version: Mapped[str] = mapped_column(String(32), nullable=False)
    engine_version: Mapped[str] = mapped_column(String(16), nullable=False)
    scoring_version: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    final_state: Mapped[list[Any] | None] = mapped_column()
    metrics: Mapped[dict[str, Any] | None] = mapped_column()
    result_hash: Mapped[str | None] = mapped_column(String(64))
    error: Mapped[dict[str, Any] | None] = mapped_column()
    requested_by: Mapped[str] = mapped_column(String(128), nullable=False)
    duration_ms: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = created_at_col()

    __table_args__ = (
        CheckConstraint("kind IN ('IMPACT', 'RECOVERY')", name="kind_valid"),
        CheckConstraint("status IN ('COMPLETED', 'FAILED')", name="status_valid"),
        CheckConstraint(
            "status <> 'COMPLETED' OR (result_hash IS NOT NULL AND final_state IS NOT NULL)",
            name="completed_has_result",
        ),
        Index("ix_simulation_run_created_at", "created_at"),
    )


class SimulationEventRow(Base):
    """One engine event of a run (append-only, ordered by seq)."""

    __tablename__ = "simulation_event"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("simulation_run.id", ondelete="CASCADE"), nullable=False
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    t_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    wave: Mapped[int] = mapped_column(Integer, nullable=False)
    event_type: Mapped[str] = mapped_column(String(32), nullable=False)
    asset_code: Mapped[str | None] = mapped_column(String(16))
    from_status: Mapped[str | None] = mapped_column(String(16))
    to_status: Mapped[str | None] = mapped_column(String(16))
    details: Mapped[dict[str, Any]] = mapped_column(nullable=False, default=dict)

    __table_args__ = (
        UniqueConstraint("run_id", "seq", name="uq_simulation_event_run_seq"),
        Index("ix_simulation_event_run_time", "run_id", "t_minutes", "wave"),
    )


class OperationalPictureChange(Base):
    """Append-only history of what the operational picture shows (baseline or a run)."""

    __tablename__ = "operational_picture_change"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String(8), nullable=False)
    simulation_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("simulation_run.id", ondelete="RESTRICT")
    )
    actor_id: Mapped[str] = mapped_column(String(128), nullable=False)
    reason: Mapped[str | None] = mapped_column(String(300))
    created_at: Mapped[datetime] = created_at_col()

    __table_args__ = (
        CheckConstraint("kind IN ('APPLY', 'RESET')", name="kind_valid"),
        CheckConstraint(
            "(kind = 'APPLY') = (simulation_run_id IS NOT NULL)", name="apply_references_run"
        ),
    )
