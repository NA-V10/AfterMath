from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Header, Query, Request, status

from app.api.deps import SessionDep, TwinDep
from app.api.identity import Admin, Approver, Operator, Viewer
from app.governance.rules.validator import ValidationReport
from app.schemas.governance import (
    ApprovalOut,
    ApproveIn,
    RecoveryExecutionOut,
    RejectIn,
    VerificationOut,
)
from app.schemas.recovery import (
    GenerateStrategiesIn,
    InventoryIn,
    InventoryOut,
    StrategyDetail,
    StrategyRound,
    StrategySummary,
)
from app.services import governance
from app.services import recovery as service

router = APIRouter(tags=["recovery"])

IdempotencyKey = Annotated[
    str,
    Header(
        alias="Idempotency-Key", min_length=8, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$",
        description="Required. Repeating a request with the same key returns the first result.",
    ),
]  # fmt: skip


@router.get("/inventory", response_model=InventoryOut)
async def get_inventory(session: SessionDep, _: Viewer) -> InventoryOut:
    return await service.get_inventory(session)


@router.post("/inventory", response_model=InventoryOut, status_code=status.HTTP_201_CREATED)
async def update_inventory(body: InventoryIn, session: SessionDep, user: Admin) -> InventoryOut:
    """Record a new inventory version (existing strategies keep referencing their version).
    Role: admin."""
    return await service.set_inventory(session, body, actor_id=user.username)


@router.post(
    "/recovery/strategies", response_model=StrategyRound, status_code=status.HTTP_201_CREATED
)
async def generate_strategies(
    body: GenerateStrategiesIn, session: SessionDep, twin: TwinDep, user: Operator
) -> StrategyRound:
    """Plan three strategies (new planning round) and validate them with GUARDIAN's rules.
    Normally invoked by the agent workflow (STRATEGIST + GUARDIAN). Role: operator."""
    ids = await service.generate_strategies(session, twin, body.incident_id, actor_id=user.username)
    for sid in ids:
        await service.validate_strategy(session, twin, sid, actor_id=user.username)
    detail = await service.get_strategy(session, ids[0])
    await service.recommend(session, body.incident_id, detail.planning_round)
    return await service.latest_round(session, twin, body.incident_id)


@router.get("/recovery/strategies", response_model=list[StrategySummary])
async def list_strategies(
    session: SessionDep,
    _: Viewer,
    incident_id: uuid.UUID | None = None,
    status_filter: Annotated[str | None, Query(alias="status", pattern="^[A-Z_]+$")] = None,
) -> list[StrategySummary]:
    return await service.list_strategies(session, incident_id=incident_id, status=status_filter)


@router.get("/recovery/strategies/compare", response_model=StrategyRound)
async def compare_strategies(
    incident_id: uuid.UUID, session: SessionDep, twin: TwinDep, _: Viewer
) -> StrategyRound:
    """The latest planning round for an incident, with the no-action baseline for comparison."""
    return await service.latest_round(session, twin, incident_id)


@router.get("/recovery/strategies/{strategy_id}", response_model=StrategyDetail)
async def get_strategy(strategy_id: uuid.UUID, session: SessionDep, _: Viewer) -> StrategyDetail:
    return await service.get_strategy(session, strategy_id)


@router.post("/recovery/strategies/{strategy_id}/validate", response_model=ValidationReport)
async def validate_strategy(
    strategy_id: uuid.UUID, session: SessionDep, twin: TwinDep, user: Operator
) -> ValidationReport:
    """Run GUARDIAN's deterministic rules (V-001..V-009) against the stored strategy."""
    return await service.validate_strategy(session, twin, strategy_id, actor_id=user.username)


@router.post(
    "/recovery/strategies/{strategy_id}/approve",
    response_model=ApprovalOut,
    status_code=status.HTTP_201_CREATED,
)
async def approve_strategy(
    strategy_id: uuid.UUID, body: ApproveIn, request: Request, session: SessionDep, user: Approver
) -> ApprovalOut:
    """Approve exactly the content you reviewed: `content_hash` and `expected_version` must match
    the stored strategy. Role: approver; separation of duties applies (see `GET /auth/me`)."""
    return await governance.decide(
        session, strategy_id, user, decision="APPROVE", content_hash=body.content_hash,
        expected_version=body.expected_version, comment=body.comment,
        separation_of_duties=request.app.state.settings.governance_separation_of_duties,
    )  # fmt: skip


@router.post(
    "/recovery/strategies/{strategy_id}/reject",
    response_model=ApprovalOut,
    status_code=status.HTTP_201_CREATED,
)
async def reject_strategy(
    strategy_id: uuid.UUID, body: RejectIn, request: Request, session: SessionDep, user: Approver
) -> ApprovalOut:
    """Reject with a required comment. REJECTED is final. Role: approver."""
    return await governance.decide(
        session, strategy_id, user, decision="REJECT", content_hash=body.content_hash,
        expected_version=body.expected_version, comment=body.comment,
        separation_of_duties=request.app.state.settings.governance_separation_of_duties,
    )  # fmt: skip


@router.post(
    "/recovery/strategies/{strategy_id}/execute",
    response_model=RecoveryExecutionOut,
    status_code=status.HTTP_201_CREATED,
)
async def execute_strategy(
    strategy_id: uuid.UUID,
    idempotency_key: IdempotencyKey,
    session: SessionDep,
    twin: TwinDep,
    user: Operator,
) -> RecoveryExecutionOut:
    """**Simulated** execution of an APPROVED strategy: GUARDIAN revalidates it (V-001…V-012)
    against the current twin and inventory, the plan is replayed through the simulation engine,
    the result is applied to the operational picture and verified. Nothing leaves the simulator.
    Role: operator. Runs synchronously (milliseconds), so it returns 201 with the result."""
    return await governance.execute(
        session, twin, strategy_id, user, idempotency_key=idempotency_key
    )


@router.get("/recovery/executions/{execution_id}", response_model=RecoveryExecutionOut)
async def get_execution(
    execution_id: uuid.UUID, session: SessionDep, _: Viewer
) -> RecoveryExecutionOut:
    return await governance.get_execution(session, execution_id)


@router.get("/recovery/executions/{execution_id}/verification", response_model=VerificationOut)
async def get_verification(
    execution_id: uuid.UUID, session: SessionDep, _: Viewer
) -> VerificationOut:
    return await governance.get_verification(session, execution_id)
