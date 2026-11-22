from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Body, Query, status

from app.api.deps import SessionDep, TwinDep
from app.api.identity import Operator, Viewer
from app.schemas.governance import CloseIncidentIn
from app.schemas.infrastructure import Page
from app.schemas.simulation import IncidentCreate, IncidentOut
from app.services import governance
from app.services import incidents as service

router = APIRouter(prefix="/incidents", tags=["incidents"])


@router.post("", response_model=IncidentOut, status_code=status.HTTP_201_CREATED)
async def create_incident(
    body: Annotated[IncidentCreate, Body()], session: SessionDep, twin: TwinDep, user: Operator
) -> IncidentOut:
    """Structured incidents are validated deterministically against the twin. Free-text reports
    are stored verbatim (untrusted) and await SENTINEL analysis. Role: operator."""
    return await service.create_incident(session, twin, body, actor_id=user.username)


@router.get("", response_model=Page[IncidentOut])
async def list_incidents(
    session: SessionDep,
    _: Viewer,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    cursor: uuid.UUID | None = None,
) -> Page[IncidentOut]:
    items, nxt = await service.list_incidents(
        session, limit=limit, cursor=str(cursor) if cursor else None
    )
    return Page[IncidentOut](items=items, next_cursor=nxt)


@router.get("/{incident_id}", response_model=IncidentOut)
async def get_incident(incident_id: uuid.UUID, session: SessionDep, _: Viewer) -> IncidentOut:
    return service.to_out(await service.get_incident_row(session, incident_id))


@router.post("/{incident_id}/close", response_model=IncidentOut)
async def close_incident(
    incident_id: uuid.UUID, body: CloseIncidentIn, session: SessionDep, user: Operator
) -> IncidentOut:
    """Close an incident with a reason. Open strategies are superseded. Role: operator."""
    await governance.close_incident(session, incident_id, user, body.reason)
    return service.to_out(await service.get_incident_row(session, incident_id))
