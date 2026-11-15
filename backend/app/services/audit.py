"""Append-only, hash-chained audit trail.

hash_n = sha256(prev_hash || canonical_json(record_n)); the first record chains from GENESIS.
Appends are serialised with a transaction-scoped advisory lock so the chain never forks.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.context import request_id_var
from app.database.models import AuditLog

GENESIS_HASH = "0" * 64
_AUDIT_LOCK_KEY = 0x4146544552  # "AFTER"

ActorType = Literal["USER", "AGENT", "SYSTEM"]


def _canonical_record(row: AuditLog) -> dict[str, Any]:
    return {
        "occurred_at": row.occurred_at.astimezone(UTC).isoformat(),
        "actor_type": row.actor_type,
        "actor_id": row.actor_id,
        "action": row.action,
        "entity_type": row.entity_type,
        "entity_id": row.entity_id,
        "request_id": row.request_id,
        "workflow_run_id": str(row.workflow_run_id) if row.workflow_run_id else None,
        "before": row.before,
        "after": row.after,
        "details": row.details,
    }


def compute_hash(prev_hash: str, row: AuditLog) -> str:
    canonical = json.dumps(
        _canonical_record(row), sort_keys=True, separators=(",", ":"), default=str
    )
    return hashlib.sha256((prev_hash + canonical).encode("utf-8")).hexdigest()


async def append_audit(
    session: AsyncSession,
    *,
    actor_type: ActorType,
    actor_id: str,
    action: str,
    entity_type: str,
    entity_id: str | None = None,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
    details: dict[str, Any] | None = None,
    workflow_run_id: uuid.UUID | None = None,
) -> AuditLog:
    """Add an audit record to the caller's transaction (committed together with the change)."""
    await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _AUDIT_LOCK_KEY})
    prev = await session.scalar(select(AuditLog.hash).order_by(AuditLog.id.desc()).limit(1))
    row = AuditLog(
        occurred_at=datetime.now(UTC),
        actor_type=actor_type,
        actor_id=actor_id,
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        request_id=request_id_var.get(),
        workflow_run_id=workflow_run_id,
        before=before,
        after=after,
        details=details,
        prev_hash=prev or GENESIS_HASH,
    )
    row.hash = compute_hash(row.prev_hash, row)
    session.add(row)
    await session.flush()
    return row


@dataclass(frozen=True, slots=True)
class ChainVerification:
    ok: bool
    records_checked: int
    first_broken_id: int | None


async def verify_chain(session: AsyncSession) -> ChainVerification:
    prev = GENESIS_HASH
    checked = 0
    result = await session.stream_scalars(select(AuditLog).order_by(AuditLog.id))
    async for row in result:
        checked += 1
        if row.prev_hash != prev or compute_hash(prev, row) != row.hash:
            return ChainVerification(False, checked, row.id)
        prev = row.hash
    return ChainVerification(True, checked, None)
