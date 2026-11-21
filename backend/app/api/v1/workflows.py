from __future__ import annotations

import asyncio
import uuid
from collections.abc import AsyncIterator
from datetime import datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import select

from app.agents.registry import AGENTS, AgentDefinition
from app.agents.workflow import WorkflowRunner
from app.api.deps import SessionDep, TwinDep
from app.api.identity import ActorDep
from app.core.errors import ConflictError, InvalidInputError, NotFoundError
from app.database.models import AgentExecution, Incident, WorkflowRun
from app.schemas.infrastructure import Page
from app.services import workflows as wf

router = APIRouter(tags=["agents"])

SSE_HEARTBEAT_S = 15


class ExecutionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: uuid.UUID
    workflow_run_id: uuid.UUID
    agent: str
    attempt: int
    status: str
    summary: str | None
    input_summary: dict[str, Any]
    output: dict[str, Any] | None
    tool_calls: list[Any]
    llm_calls: list[Any]
    grounding: dict[str, Any] | None
    tokens_in: int | None
    tokens_out: int | None
    latency_ms: float | None
    error: dict[str, Any] | None
    started_at: datetime
    completed_at: datetime | None


class WorkflowOut(BaseModel):
    id: uuid.UUID
    incident_id: uuid.UUID
    incident_reference: str
    status: str
    current_node: str | None
    llm_mode: str
    llm_provider: str
    pending_question: dict[str, Any] | None
    result: dict[str, Any] | None
    error: dict[str, Any] | None
    started_at: datetime
    completed_at: datetime | None
    executions: list[ExecutionOut]


class AnalyzeAccepted(BaseModel):
    workflow_run_id: uuid.UUID
    status: str


class ClarificationIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    asset_codes: list[str] = Field(min_length=1, max_length=20)
    condition: Literal["DEGRADED", "DAMAGED", "DESTROYED"] = "DAMAGED"
    incident_type: Literal[
        "POWER_FAILURE", "FLOODING", "TELECOM_OUTAGE", "WATER_DISRUPTION", "EQUIPMENT_FAILURE",
        "COMBINED",
    ] | None = None  # fmt: skip
    severity: Literal["LOW", "MODERATE", "HIGH", "CRITICAL"] | None = None


def _runner(request: Request) -> WorkflowRunner:
    runner: WorkflowRunner = request.app.state.workflow_runner
    return runner


async def _workflow_out(session: Any, run: WorkflowRun) -> WorkflowOut:
    incident = await session.get(Incident, run.incident_id)
    executions = await wf.executions_for(session, run.id)
    return WorkflowOut(
        id=run.id, incident_id=run.incident_id, incident_reference=incident.reference,
        status=run.status, current_node=run.current_node, llm_mode=run.llm_mode,
        llm_provider=run.llm_provider, pending_question=run.pending_question, result=run.result,
        error=run.error, started_at=run.started_at, completed_at=run.completed_at,
        executions=[ExecutionOut.model_validate(e) for e in executions],
    )  # fmt: skip


@router.post(
    "/incidents/{incident_id}/analyze",
    response_model=AnalyzeAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def analyze_incident(
    incident_id: uuid.UUID, request: Request, actor: ActorDep
) -> AnalyzeAccepted:
    """Start the agent workflow (SENTINEL -> CARTOGRAPHER -> ORACLE) in the background."""
    run = await _runner(request).start(incident_id, actor_id=actor)
    return AnalyzeAccepted(workflow_run_id=run.id, status=run.status)


@router.get("/workflows", response_model=list[WorkflowOut])
async def list_workflows(
    session: SessionDep, incident_id: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=50)] = 20,
) -> list[WorkflowOut]:  # fmt: skip
    stmt = select(WorkflowRun).order_by(WorkflowRun.started_at.desc()).limit(limit)
    if incident_id:
        stmt = stmt.where(WorkflowRun.incident_id == incident_id)
    return [await _workflow_out(session, r) for r in (await session.scalars(stmt)).all()]


@router.get("/workflows/{run_id}", response_model=WorkflowOut)
async def get_workflow(run_id: uuid.UUID, session: SessionDep) -> WorkflowOut:
    return await _workflow_out(session, await wf.get_run(session, run_id))


@router.post(
    "/workflows/{run_id}/clarify",
    response_model=AnalyzeAccepted,
    status_code=status.HTTP_202_ACCEPTED,
)
async def clarify_workflow(
    run_id: uuid.UUID, body: ClarificationIn, request: Request, session: SessionDep,
    twin: TwinDep, actor: ActorDep,
) -> AnalyzeAccepted:  # fmt: skip
    """Answer SENTINEL's question: confirm the damaged facilities (validated against the twin)."""
    run = await wf.get_run(session, run_id)
    if run.status != "AWAITING_CLARIFICATION":
        raise ConflictError(f"Workflow is {run.status}; it is not waiting for clarification.")
    unknown = sorted(set(body.asset_codes) - set(twin.snapshot.assets_by_code))
    if unknown:
        raise InvalidInputError(f"Unknown asset code(s): {', '.join(unknown)}")
    await _runner(request).clarify(run_id, body.model_dump(), actor_id=actor)
    return AnalyzeAccepted(workflow_run_id=run_id, status="RUNNING")


@router.get("/workflows/{run_id}/events")
async def workflow_events(run_id: uuid.UUID, request: Request) -> StreamingResponse:
    """Server-Sent Events: a `workflow` snapshot on connect and after every change; the stream
    ends after a terminal status. Clients may fall back to polling GET /workflows/{id}."""
    db = request.app.state.db
    bus = request.app.state.event_bus
    async with db.sessionmaker() as s:
        await wf.get_run(s, run_id)  # 404 before streaming starts

    async def stream() -> AsyncIterator[str]:
        async with bus.subscribe(f"workflow:{run_id}") as queue:
            while True:
                async with db.sessionmaker() as s:
                    run = await wf.get_run(s, run_id)
                    snapshot = await _workflow_out(s, run)
                yield f"event: workflow\ndata: {snapshot.model_dump_json()}\n\n"
                if snapshot.status in ("COMPLETED", "FAILED", "AWAITING_CLARIFICATION"):
                    return
                try:
                    await asyncio.wait_for(queue.get(), SSE_HEARTBEAT_S)
                except TimeoutError:
                    yield ": heartbeat\n\n"
                if await request.is_disconnected():
                    return

    return StreamingResponse(
        stream(), media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )  # fmt: skip


@router.get("/agents", response_model=list[AgentDefinition])
async def list_agents() -> list[AgentDefinition]:
    return AGENTS


@router.get("/agents/activity", response_model=Page[ExecutionOut])
async def agent_activity(
    session: SessionDep,
    agent: Annotated[str | None, Query(pattern="^[A-Z]+$")] = None,
    workflow_run_id: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    cursor: uuid.UUID | None = None,
) -> Page[ExecutionOut]:
    stmt = select(AgentExecution).order_by(
        AgentExecution.started_at.desc(), AgentExecution.id.desc()
    )
    if agent:
        stmt = stmt.where(AgentExecution.agent == agent)
    if workflow_run_id:
        stmt = stmt.where(AgentExecution.workflow_run_id == workflow_run_id)
    if cursor:
        anchor = await session.get(AgentExecution, cursor)
        if anchor is None:
            raise NotFoundError("Unknown cursor.")
        stmt = stmt.where(
            (AgentExecution.started_at < anchor.started_at)
            | ((AgentExecution.started_at == anchor.started_at) & (AgentExecution.id < anchor.id))
        )
    rows = list((await session.scalars(stmt.limit(limit + 1))).all())
    page = rows[:limit]
    return Page[ExecutionOut](
        items=[ExecutionOut.model_validate(r) for r in page],
        next_cursor=str(page[-1].id) if len(rows) > limit else None,
    )


@router.get("/agents/executions/{execution_id}", response_model=ExecutionOut)
async def get_execution(execution_id: uuid.UUID, session: SessionDep) -> ExecutionOut:
    row = await session.get(AgentExecution, execution_id)
    if row is None:
        raise NotFoundError(f"Agent execution {execution_id} does not exist.")
    return ExecutionOut.model_validate(row)


__all__ = ["router"]
