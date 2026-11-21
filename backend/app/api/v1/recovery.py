from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import SessionDep, TwinDep
from app.api.identity import ActorDep
from app.governance.rules.validator import ValidationReport
from app.schemas.recovery import (
    GenerateStrategiesIn,
    InventoryIn,
    InventoryOut,
    StrategyDetail,
    StrategyRound,
    StrategySummary,
)
from app.services import recovery as service

router = APIRouter(tags=["recovery"])


@router.get("/inventory", response_model=InventoryOut)
async def get_inventory(session: SessionDep) -> InventoryOut:
    return await service.get_inventory(session)


@router.post("/inventory", response_model=InventoryOut, status_code=status.HTTP_201_CREATED)
async def update_inventory(body: InventoryIn, session: SessionDep, actor: ActorDep) -> InventoryOut:
    """Record a new inventory version (existing strategies keep referencing their version)."""
    return await service.set_inventory(session, body, actor_id=actor)


@router.post(
    "/recovery/strategies", response_model=StrategyRound, status_code=status.HTTP_201_CREATED
)
async def generate_strategies(
    body: GenerateStrategiesIn, session: SessionDep, twin: TwinDep, actor: ActorDep
) -> StrategyRound:
    """Plan three strategies (new planning round) and validate them with GUARDIAN's rules.
    Normally invoked by the agent workflow (STRATEGIST + GUARDIAN)."""
    ids = await service.generate_strategies(session, twin, body.incident_id, actor_id=actor)
    for sid in ids:
        await service.validate_strategy(session, twin, sid, actor_id=actor)
    detail = await service.get_strategy(session, ids[0])
    await service.recommend(session, body.incident_id, detail.planning_round)
    return await service.latest_round(session, twin, body.incident_id)


@router.get("/recovery/strategies", response_model=list[StrategySummary])
async def list_strategies(
    session: SessionDep,
    incident_id: uuid.UUID | None = None,
    status_filter: Annotated[str | None, Query(alias="status", pattern="^[A-Z_]+$")] = None,
) -> list[StrategySummary]:
    return await service.list_strategies(session, incident_id=incident_id, status=status_filter)


@router.get("/recovery/strategies/compare", response_model=StrategyRound)
async def compare_strategies(
    incident_id: uuid.UUID, session: SessionDep, twin: TwinDep
) -> StrategyRound:
    """The latest planning round for an incident, with the no-action baseline for comparison."""
    return await service.latest_round(session, twin, incident_id)


@router.get("/recovery/strategies/{strategy_id}", response_model=StrategyDetail)
async def get_strategy(strategy_id: uuid.UUID, session: SessionDep) -> StrategyDetail:
    return await service.get_strategy(session, strategy_id)


@router.post("/recovery/strategies/{strategy_id}/validate", response_model=ValidationReport)
async def validate_strategy(
    strategy_id: uuid.UUID, session: SessionDep, twin: TwinDep, actor: ActorDep
) -> ValidationReport:
    """Run GUARDIAN's deterministic rules (V-001..V-009) against the stored strategy."""
    return await service.validate_strategy(session, twin, strategy_id, actor_id=actor)
