"""Integration fixtures: a real PostgreSQL database (TEST_DATABASE_URL), migrated from scratch.

Skipped (reported as skipped, never as passed) when the database is unreachable.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator

import asyncpg
import pytest
from alembic import command
from alembic.config import Config
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.database.session import Database
from app.graph.dataset import load_dataset_dir, to_snapshot
from app.main import BACKEND_ROOT, create_app
from app.services.dataset import seed_dataset
from app.services.scenarios import load_scenario_files, sync_scenarios
from tests.conftest import DATASET_DIR, SCENARIOS_DIR

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://aftermath:change-me-local-only@localhost:5432/aftermath_test",
)


def _reachable() -> str | None:
    async def probe() -> None:
        conn = await asyncpg.connect(TEST_DATABASE_URL.replace("+asyncpg", ""), timeout=3)
        await conn.close()

    try:
        asyncio.run(probe())
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}"
    return None


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    integration = [i for i in items if "integration" in i.nodeid.replace("\\", "/").split("/")]
    if not integration:
        return
    reason = _reachable()
    for item in integration:
        item.add_marker(pytest.mark.integration)
        if reason:
            item.add_marker(pytest.mark.skip(reason=f"test database unreachable ({reason})"))


def _alembic(*args: str) -> None:
    cfg = Config(str(BACKEND_ROOT / "alembic.ini"))
    cfg.attributes["database_url"] = TEST_DATABASE_URL
    cfg.attributes["configure_logging"] = False
    getattr(command, args[0])(cfg, *args[1:])


@pytest.fixture(scope="session")
def migrated_db() -> str:
    """Fresh schema for the session (sync fixture: Alembic runs its own event loop)."""

    async def reset() -> None:
        conn = await asyncpg.connect(TEST_DATABASE_URL.replace("+asyncpg", ""))
        try:
            await conn.execute("DROP SCHEMA public CASCADE")
            await conn.execute("CREATE SCHEMA public")
        finally:
            await conn.close()

    asyncio.run(reset())
    _alembic("upgrade", "head")
    return TEST_DATABASE_URL


@pytest.fixture(scope="session")
async def database(migrated_db: str) -> AsyncIterator[Database]:
    db = Database(migrated_db, pool_size=2)
    yield db
    await db.dispose()


@pytest.fixture(scope="session")
async def seeded(database: Database) -> None:
    files, basemap = load_dataset_dir(DATASET_DIR)
    async with database.sessionmaker() as session, session.begin():
        await seed_dataset(session, files, basemap, actor_id="test:seed")
        await sync_scenarios(
            session, to_snapshot(files), load_scenario_files(SCENARIOS_DIR), actor_id="test:seed"
        )


@pytest.fixture
async def session(database: Database) -> AsyncIterator[AsyncSession]:
    async with database.sessionmaker() as s:
        yield s


@pytest.fixture(scope="session")
async def client(seeded: None, migrated_db: str) -> AsyncIterator[AsyncClient]:
    app = create_app(Settings(database_url=migrated_db, aftermath_env="test", log_level="WARNING"))
    async with app.router.lifespan_context(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test/api/v1") as c:
            yield c
