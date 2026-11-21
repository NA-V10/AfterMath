"""Incident intake (Phase 2: structured + stored free text; SENTINEL analysis is Phase 3)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import NotFoundError
from app.database.models import Incident
from app.schemas.simulation import (
    FreeTextIncidentCreate,
    IncidentOut,
    StructuredIncidentCreate,
)
from app.services.audit import append_audit
from app.services.scenarios import EVENTS_ADAPTER, check_events
from app.services.simulations import DEFAULT_HORIZON_MINUTES
from app.services.twin_store import LoadedTwin


def to_out(row: Incident) -> IncidentOut:
    return IncidentOut(
        id=row.id,
        reference=row.reference,
        source=row.source,
        status=row.status,
        title=row.title,
        incident_type=row.incident_type,
        severity=row.severity,
        occurred_at=row.occurred_at,
        raw_report=row.raw_report,
        initiating_events=(
            EVENTS_ADAPTER.validate_python(row.initiating_events) if row.initiating_events else None
        ),
        confidence=row.confidence,
        missing_information=[str(m) for m in row.missing_information],
        created_at=row.created_at,
        analysis_available=row.initiating_events is not None,
    )


async def create_incident(
    session: AsyncSession,
    twin: LoadedTwin,
    body: StructuredIncidentCreate | FreeTextIncidentCreate,
    *,
    actor_id: str,
) -> IncidentOut:
    seq = await session.scalar(text("SELECT nextval('incident_reference_seq')"))
    reference = f"INC-{datetime.now(UTC).year}-{int(seq or 0):04d}"
    if isinstance(body, StructuredIncidentCreate):
        check_events(twin.snapshot, body.initiating_events, DEFAULT_HORIZON_MINUTES)
        row = Incident(
            id=uuid.uuid4(), reference=reference, source="STRUCTURED", title=body.title,
            incident_type=body.incident_type, severity=body.severity,
            occurred_at=body.occurred_at,
            initiating_events=[e.model_dump(mode="json") for e in body.initiating_events],
            confidence=1.0, missing_information=[],
        )  # fmt: skip
    else:
        row = Incident(
            id=uuid.uuid4(), reference=reference, source="FREE_TEXT", raw_report=body.raw_report,
            occurred_at=body.occurred_at,
            missing_information=["incident_type", "severity", "initiating_events"],
        )  # fmt: skip
    session.add(row)
    await session.flush()
    await append_audit(
        session, actor_type="USER", actor_id=actor_id, action="incident.created",
        entity_type="incident", entity_id=str(row.id),
        details={"reference": reference, "source": row.source},
    )  # fmt: skip
    await session.commit()
    await session.refresh(row)
    return to_out(row)


async def list_incidents(
    session: AsyncSession, *, limit: int, cursor: str | None
) -> tuple[list[IncidentOut], str | None]:
    stmt = select(Incident).order_by(Incident.created_at.desc(), Incident.id.desc())
    if cursor:
        anchor = await get_incident_row(session, uuid.UUID(cursor))
        stmt = stmt.where(
            (Incident.created_at < anchor.created_at)
            | ((Incident.created_at == anchor.created_at) & (Incident.id < anchor.id))
        )
    rows = list((await session.scalars(stmt.limit(limit + 1))).all())
    page = rows[:limit]
    return [to_out(r) for r in page], (str(page[-1].id) if len(rows) > limit else None)


async def get_incident_row(session: AsyncSession, incident_id: uuid.UUID) -> Incident:
    row = await session.get(Incident, incident_id)
    if row is None:
        raise NotFoundError(f"Incident {incident_id} does not exist.")
    return row
