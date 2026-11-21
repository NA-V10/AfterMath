"""Persistence for agent workflows: runs, executions, and incident updates made by agents."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError
from app.database.models import AgentExecution, Incident, IncidentEvidence, WorkflowRun
from app.services.audit import append_audit

TERMINAL = frozenset({"COMPLETED", "FAILED"})


async def create_run(
    session: AsyncSession,
    incident_id: uuid.UUID,
    *,
    llm_mode: str,
    llm_provider: str,
    actor_id: str,
) -> WorkflowRun:
    incident = await session.get(Incident, incident_id)
    if incident is None:
        raise NotFoundError(f"Incident {incident_id} does not exist.")
    if incident.status in ("AWAITING_APPROVAL", "RECOVERING", "RECOVERED", "CLOSED"):
        raise ConflictError(
            f"Incident {incident.reference} is {incident.status}; cannot re-analyse."
        )
    run = WorkflowRun(
        id=uuid.uuid4(), incident_id=incident_id, status="RUNNING", current_node="SENTINEL",
        llm_mode=llm_mode, llm_provider=llm_provider, requested_by=actor_id,
    )  # fmt: skip
    reference = incident.reference  # captured before a possible rollback expires the row
    session.add(run)
    incident.status = "ANALYZING"
    incident.version += 1
    try:
        await session.flush()
    except IntegrityError:
        await session.rollback()
        raise ConflictError(
            f"An analysis of incident {reference} is already in progress."
        ) from None
    await append_audit(
        session, actor_type="USER", actor_id=actor_id, action="workflow.started",
        entity_type="workflow_run", entity_id=str(run.id),
        details={"incident": reference, "llm": llm_provider},
    )  # fmt: skip
    await session.commit()
    return run


async def update_run(session: AsyncSession, run_id: uuid.UUID, **fields: Any) -> WorkflowRun:
    run = await session.get(WorkflowRun, run_id)
    if run is None:
        raise NotFoundError(f"Workflow {run_id} does not exist.")
    for key, value in fields.items():
        setattr(run, key, value)
    if fields.get("status") in TERMINAL:
        run.completed_at = datetime.now(UTC)
    await session.commit()
    return run


async def finish_run(
    session: AsyncSession,
    run_id: uuid.UUID,
    *,
    status: str,
    incident_status: str,
    result: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
) -> None:
    run = await session.get(WorkflowRun, run_id)
    if run is None:
        raise NotFoundError(f"Workflow {run_id} does not exist.")
    run.status, run.current_node, run.pending_question = status, None, None
    run.result, run.error, run.completed_at = result, error, datetime.now(UTC)
    incident = await session.get(Incident, run.incident_id)
    assert incident is not None
    incident.status = incident_status
    incident.version += 1
    await append_audit(
        session, actor_type="SYSTEM", actor_id="workflow", action=f"workflow.{status.lower()}",
        entity_type="workflow_run", entity_id=str(run_id),
        workflow_run_id=run_id, details={"incident_status": incident_status, "error": error},
    )  # fmt: skip
    await session.commit()


async def start_execution(
    session: AsyncSession, run_id: uuid.UUID, agent: str, input_summary: dict[str, Any]
) -> AgentExecution:
    previous = await session.scalars(
        select(AgentExecution.id).where(
            AgentExecution.workflow_run_id == run_id, AgentExecution.agent == agent
        )
    )
    row = AgentExecution(
        id=uuid.uuid4(), workflow_run_id=run_id, agent=agent,
        attempt=len(previous.all()) + 1, status="RUNNING", input_summary=input_summary,
    )  # fmt: skip
    session.add(row)
    run = await session.get(WorkflowRun, run_id)
    if run is not None:
        run.current_node = agent
    await session.commit()
    return row


async def finish_execution(session: AsyncSession, execution_id: uuid.UUID, **fields: Any) -> None:
    row = await session.get(AgentExecution, execution_id)
    assert row is not None
    for key, value in fields.items():
        setattr(row, key, value)
    row.completed_at = datetime.now(UTC)
    await session.commit()


async def save_assessment(
    session: AsyncSession,
    incident_id: uuid.UUID,
    assessment: dict[str, Any],
    *,
    run_id: uuid.UUID,
    execution_id: uuid.UUID,
) -> None:
    """Persist SENTINEL's validated assessment on the incident (with evidence) and audit it."""
    incident = await session.get(Incident, incident_id)
    assert incident is not None
    before = {"incident_type": incident.incident_type, "severity": incident.severity}
    incident.incident_type = assessment["incident_type"]
    incident.severity = assessment["severity"]
    incident.initiating_events = assessment["initiating_events"]
    incident.confidence = assessment["confidence"]
    incident.missing_information = assessment["missing_information"]
    incident.version += 1
    for ev in assessment["evidence"]:
        session.add(
            IncidentEvidence(
                incident_id=incident_id, kind=ev["kind"],
                content={k: v for k, v in ev.items() if k not in ("kind", "score")},
                source_agent_execution_id=execution_id, confidence=ev.get("score"),
            )
        )  # fmt: skip
    await append_audit(
        session, actor_type="AGENT", actor_id="SENTINEL", action="incident.assessed",
        entity_type="incident", entity_id=str(incident_id), workflow_run_id=run_id,
        before=before,
        after={k: assessment[k] for k in ("incident_type", "severity", "confidence")},
        details={"initiating_events": assessment["initiating_events"]},
    )  # fmt: skip
    await session.commit()


async def get_run(session: AsyncSession, run_id: uuid.UUID) -> WorkflowRun:
    run = await session.get(WorkflowRun, run_id)
    if run is None:
        raise NotFoundError(f"Workflow {run_id} does not exist.")
    return run


async def executions_for(session: AsyncSession, run_id: uuid.UUID) -> list[AgentExecution]:
    rows = await session.scalars(
        select(AgentExecution)
        .where(AgentExecution.workflow_run_id == run_id)
        .order_by(AgentExecution.started_at, AgentExecution.id)
    )
    return list(rows.all())


async def runs_with_status(session: AsyncSession, status: str) -> list[WorkflowRun]:
    return list(
        (await session.scalars(select(WorkflowRun).where(WorkflowRun.status == status))).all()
    )
