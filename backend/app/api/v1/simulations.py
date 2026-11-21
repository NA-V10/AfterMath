from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.api.deps import SessionDep, TwinDep
from app.api.identity import ActorDep
from app.core.errors import InvalidInputError
from app.schemas.infrastructure import Page
from app.schemas.simulation import (
    OperationalPicture,
    PictureResetRequest,
    ReplayResult,
    ScenarioOut,
    SimulationComparison,
    SimulationDetail,
    SimulationRequest,
    SimulationSummary,
)
from app.services import scenarios as scenario_service
from app.services import simulations as service
from app.simulation.model import SimEvent

scenarios_router = APIRouter(prefix="/scenarios", tags=["scenarios"])
router = APIRouter(prefix="/simulations", tags=["simulations"])
picture_router = APIRouter(prefix="/operational-picture", tags=["operational picture"])


def _scenario_out(row) -> ScenarioOut:  # type: ignore[no-untyped-def]
    return ScenarioOut(
        key=row.key, name=row.name, description=row.description,
        horizon_minutes=row.horizon_minutes,
        initiating_events=scenario_service.EVENTS_ADAPTER.validate_python(row.initiating_events),
        content_hash=row.content_hash, version=row.version,
    )  # fmt: skip


@scenarios_router.get("", response_model=list[ScenarioOut])
async def list_scenarios(session: SessionDep) -> list[ScenarioOut]:
    return [_scenario_out(r) for r in await scenario_service.list_scenarios(session)]


@scenarios_router.get("/{key}", response_model=ScenarioOut)
async def get_scenario(key: str, session: SessionDep) -> ScenarioOut:
    return _scenario_out(await scenario_service.get_scenario(session, key))


@router.post("", response_model=SimulationDetail, status_code=status.HTTP_201_CREATED)
async def create_simulation(
    body: SimulationRequest, session: SessionDep, twin: TwinDep, actor: ActorDep
) -> SimulationDetail:
    """Run a deterministic simulation synchronously and persist it (immutable)."""
    return await service.run_simulation(session, twin, body, actor_id=actor)


@router.get("", response_model=Page[SimulationSummary])
async def list_simulations(
    session: SessionDep,
    incident_id: uuid.UUID | None = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    cursor: uuid.UUID | None = None,
) -> Page[SimulationSummary]:
    items, nxt = await service.list_runs(
        session, limit=limit, cursor=str(cursor) if cursor else None, incident_id=incident_id
    )
    return Page[SimulationSummary](items=items, next_cursor=nxt)


@router.get("/compare", response_model=SimulationComparison)
async def compare_simulations(
    session: SessionDep, ids: Annotated[str, Query(description="two ids: a,b")]
) -> SimulationComparison:
    parts = [p.strip() for p in ids.split(",") if p.strip()]
    try:
        a, b = (uuid.UUID(p) for p in parts)
    except ValueError:
        raise InvalidInputError("ids must be exactly two simulation UUIDs: 'a,b'") from None
    return await service.compare_runs(session, a, b)


@router.get("/{simulation_id}", response_model=SimulationDetail)
async def get_simulation(simulation_id: uuid.UUID, session: SessionDep) -> SimulationDetail:
    return await service.get_run(session, simulation_id)


@router.get("/{simulation_id}/events", response_model=list[SimEvent])
async def get_simulation_events(
    simulation_id: uuid.UUID,
    session: SessionDep,
    from_t: Annotated[int | None, Query(ge=0)] = None,
    to_t: Annotated[int | None, Query(ge=0)] = None,
) -> list[SimEvent]:
    return await service.run_events(session, simulation_id, from_t, to_t)


@router.post("/{simulation_id}/replay", response_model=ReplayResult)
async def replay_simulation(
    simulation_id: uuid.UUID, session: SessionDep, twin: TwinDep
) -> ReplayResult:
    """Re-run with identical inputs and compare result hashes (reproducibility check)."""
    return await service.replay_run(session, twin, simulation_id)


@picture_router.get("", response_model=OperationalPicture)
async def get_picture(session: SessionDep, twin: TwinDep) -> OperationalPicture:
    return await service.current_picture(session, twin)


@picture_router.post("/apply/{simulation_id}", response_model=OperationalPicture)
async def apply_picture(
    simulation_id: uuid.UUID, session: SessionDep, twin: TwinDep, actor: ActorDep
) -> OperationalPicture:
    await service.apply_picture(session, simulation_id, actor_id=actor)
    return await service.current_picture(session, twin)


@picture_router.post("/reset", response_model=OperationalPicture)
async def reset_picture(
    body: PictureResetRequest, session: SessionDep, twin: TwinDep, actor: ActorDep
) -> OperationalPicture:
    """Return the operational picture to the baseline. History is kept (append-only)."""
    await service.reset_picture(session, actor_id=actor, reason=body.reason)
    return await service.current_picture(session, twin)
