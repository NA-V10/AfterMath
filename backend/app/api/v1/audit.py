from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from app.api.deps import SessionDep
from app.core.errors import NotFoundError
from app.database.models import AuditLog
from app.schemas.infrastructure import Page

router = APIRouter(prefix="/audit", tags=["audit"])


class AuditRecord(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    occurred_at: datetime
    actor_type: str
    actor_id: str
    action: str
    entity_type: str
    entity_id: str | None
    request_id: str | None
    workflow_run_id: uuid.UUID | None
    before: dict[str, Any] | None
    after: dict[str, Any] | None
    details: dict[str, Any] | None
    prev_hash: str
    hash: str


@router.get("", response_model=Page[AuditRecord])
async def list_audit(
    session: SessionDep,
    entity_type: Annotated[str | None, Query(max_length=48)] = None,
    entity_id: Annotated[str | None, Query(max_length=128)] = None,
    action: Annotated[str | None, Query(max_length=64)] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    cursor: Annotated[
        int | None, Query(ge=1, description="return records with id < cursor")
    ] = None,
) -> Page[AuditRecord]:
    stmt = select(AuditLog).order_by(AuditLog.id.desc()).limit(limit + 1)
    if entity_type:
        stmt = stmt.where(AuditLog.entity_type == entity_type)
    if entity_id:
        stmt = stmt.where(AuditLog.entity_id == entity_id)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if cursor:
        stmt = stmt.where(AuditLog.id < cursor)
    rows = (await session.scalars(stmt)).all()
    page = rows[:limit]
    return Page[AuditRecord](
        items=[AuditRecord.model_validate(r) for r in page],
        next_cursor=str(page[-1].id) if len(rows) > limit else None,
    )


@router.get("/{record_id}", response_model=AuditRecord)
async def get_audit(record_id: int, session: SessionDep) -> AuditRecord:
    row = await session.get(AuditLog, record_id)
    if row is None:
        raise NotFoundError(f"Audit record {record_id} does not exist.")
    return AuditRecord.model_validate(row)
