"""FastAPI application factory.

SIMULATION ENVIRONMENT — NOT CONNECTED TO LIVE INFRASTRUCTURE.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.exc import SQLAlchemyError

from app.agents.nodes import Deps
from app.agents.workflow import WorkflowRunner
from app.api.v1.router import api_router
from app.core.config import API_PREFIX, APP_VERSION, Settings, get_settings
from app.core.errors import register_exception_handlers
from app.core.events import EventBus
from app.core.logging import configure_logging, get_logger
from app.core.middleware import RequestContextMiddleware
from app.database.session import Database
from app.llm.chain import LLMClient, build_llm_client
from app.services.twin_store import TwinStore

BACKEND_ROOT = Path(__file__).resolve().parents[1]


def migration_head() -> str | None:
    script = ScriptDirectory.from_config(Config(str(BACKEND_ROOT / "alembic.ini")))
    return script.get_current_head()


def create_app(settings: Settings | None = None, *, llm: LLMClient | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, json=settings.json_logs)
    log = get_logger("aftermath")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.db = Database(settings.database_url, pool_size=settings.db_pool_size)
        app.state.twin_store = TwinStore()
        app.state.migration_head = migration_head()
        app.state.event_bus = EventBus()
        app.state.llm = llm or build_llm_client(settings)
        app.state.workflow_runner = WorkflowRunner(
            Deps(app.state.db, app.state.twin_store, app.state.llm, app.state.event_bus)
        )
        try:
            resumed = await app.state.workflow_runner.resume_incomplete()
        except (OSError, SQLAlchemyError) as exc:  # DB down: start anyway; readiness reports it
            log.warning("workflow_resume_skipped", error_type=type(exc).__name__)
            resumed = 0
        log.info(
            "startup",
            version=APP_VERSION,
            environment=settings.aftermath_env,
            llm=app.state.llm.description,
            workflows_resumed=resumed,
        )
        yield
        await app.state.workflow_runner.shutdown()
        await app.state.db.dispose()

    app = FastAPI(
        title="AFTERMATH API",
        version=APP_VERSION,
        description=(
            "Infrastructure resilience & recovery decision support. "
            "**SIMULATION ENVIRONMENT — NOT CONNECTED TO LIVE INFRASTRUCTURE.** "
            "All data is synthetic."
        ),
        openapi_url=f"{API_PREFIX}/openapi.json",
        docs_url=f"{API_PREFIX}/docs",
        redoc_url=None,
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["content-type", "x-request-id", "idempotency-key", "authorization"],
        expose_headers=["x-request-id", "x-aftermath-environment"],
    )
    app.add_middleware(RequestContextMiddleware)  # outermost: ids/headers on every response
    register_exception_handlers(app)
    app.include_router(api_router, prefix=API_PREFIX)
    return app


app = create_app()
