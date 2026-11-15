from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text

from app.api.deps import SessionDep
from app.core.config import APP_VERSION, get_settings
from app.database import repositories as repo

router = APIRouter(tags=["system"])

SIMULATION_NOTICE = "SIMULATION ENVIRONMENT — NOT CONNECTED TO LIVE INFRASTRUCTURE."


class Liveness(BaseModel):
    status: Literal["ok"] = "ok"


class DatasetInfo(BaseModel):
    name: str
    version: str
    content_hash: str
    asset_count: int
    dependency_count: int


class Capabilities(BaseModel):
    """Which product capabilities are implemented in this build (no fake features)."""

    phase: int
    digital_twin: bool
    simulation: bool
    agents: bool
    recovery: bool
    governance: bool


class SystemStatus(BaseModel):
    app_version: str
    environment: str
    simulation_notice: str
    database_revision: str | None
    dataset: DatasetInfo | None
    capabilities: Capabilities


CAPABILITIES = Capabilities(
    phase=1, digital_twin=True, simulation=False, agents=False, recovery=False, governance=False
)


@router.get("/health", response_model=Liveness)
async def liveness() -> Liveness:
    return Liveness()


@router.get("/health/ready", responses={503: {"description": "Not ready"}})
async def readiness(request: Request, session: SessionDep) -> JSONResponse:
    checks: dict[str, Any] = {}
    try:
        await session.execute(text("SELECT 1"))
        checks["database"] = "ok"
        revision = await session.scalar(text("SELECT version_num FROM alembic_version"))
        expected = request.app.state.migration_head
        checks["migrations"] = (
            "ok" if revision == expected else f"at {revision}, expected {expected}"
        )
        release = await repo.current_release(session)
        checks["dataset"] = "ok" if release else "not seeded"
    except Exception as exc:  # report, don't raise: this endpoint must always answer
        checks.setdefault("database", f"unavailable ({type(exc).__name__})")
    ready = all(v == "ok" for v in checks.values()) and len(checks) == 3
    return JSONResponse(
        {"status": "ready" if ready else "not_ready", "checks": checks},
        status_code=200 if ready else 503,
    )


@router.get("/system/status", response_model=SystemStatus)
async def system_status(session: SessionDep) -> SystemStatus:
    revision = await session.scalar(text("SELECT version_num FROM alembic_version"))
    release = await repo.current_release(session)
    return SystemStatus(
        app_version=APP_VERSION,
        environment=get_settings().aftermath_env,
        simulation_notice=SIMULATION_NOTICE,
        database_revision=revision,
        dataset=DatasetInfo(
            name=release.name,
            version=release.version,
            content_hash=release.content_hash,
            asset_count=release.asset_count,
            dependency_count=release.dependency_count,
        )
        if release
        else None,
        capabilities=CAPABILITIES,
    )
