from __future__ import annotations

import pytest
from sqlalchemy import text, update
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, InvalidInputError, ServiceUnavailableError
from app.database.models import InfrastructureAsset
from app.database.session import Database
from app.graph.dataset import load_dataset_dir
from app.services.audit import append_audit, verify_chain
from app.services.dataset import seed_dataset
from app.services.twin_store import TwinStore
from tests.conftest import DATASET_DIR


async def test_seeding_is_idempotent(seeded: None, database: Database) -> None:
    files, basemap = load_dataset_dir(DATASET_DIR)
    async with database.sessionmaker() as s, s.begin():
        result = await seed_dataset(s, files, basemap, actor_id="test")
    assert result.status == "unchanged"


async def test_same_version_with_different_content_is_rejected(
    seeded: None, database: Database
) -> None:
    files, basemap = load_dataset_dir(DATASET_DIR)
    first = files.assets[0].model_copy(update={"criticality": 1})
    changed = files.model_copy(update={"assets": (first, *files.assets[1:])})
    with pytest.raises(ConflictError):
        async with database.sessionmaker() as s, s.begin():
            await seed_dataset(s, changed, basemap, actor_id="test")


async def test_same_version_with_different_basemap_is_rejected(
    seeded: None, database: Database
) -> None:
    files, basemap = load_dataset_dir(DATASET_DIR)
    changed = {**basemap, "features": basemap["features"][:-1]}
    with pytest.raises(ConflictError):
        async with database.sessionmaker() as s, s.begin():
            await seed_dataset(s, files, changed, actor_id="test")


async def test_invalid_dataset_is_rejected_before_any_write(
    seeded: None, database: Database
) -> None:
    files, basemap = load_dataset_dir(DATASET_DIR)
    broken = files.model_copy(
        update={
            "manifest": files.manifest.model_copy(update={"version": "9.9.9"}),
            "assets": tuple(a for a in files.assets if a.code != "GSP-01"),
        }
    )
    with pytest.raises(InvalidInputError) as info:
        async with database.sessionmaker() as s, s.begin():
            await seed_dataset(s, broken, basemap, actor_id="test")
    assert any("D-001" in issue for issue in info.value.extra["issues"])


async def test_twin_round_trips_through_database_with_identical_hash(
    seeded: None, session: AsyncSession
) -> None:
    files, _ = load_dataset_dir(DATASET_DIR)
    from app.graph.dataset import to_snapshot

    loaded = await TwinStore().current(session)
    assert loaded.snapshot.content_hash == to_snapshot(files).content_hash
    assert loaded.snapshot == to_snapshot(files)


async def test_out_of_band_modification_fails_integrity_check(
    seeded: None, database: Database
) -> None:
    async with database.sessionmaker() as s:
        await s.execute(
            update(InfrastructureAsset)
            .where(InfrastructureAsset.code == "SUB-02")
            .values(criticality=1)
        )
        with pytest.raises(ServiceUnavailableError, match="integrity"):
            await TwinStore().current(s)
        await s.rollback()  # leave the shared database untouched


async def test_audit_log_is_append_only(seeded: None, database: Database) -> None:
    async with database.sessionmaker() as s:
        with pytest.raises(DBAPIError, match="append-only"):
            await s.execute(text("UPDATE audit_log SET actor_id = 'mallory'"))
        await s.rollback()
        with pytest.raises(DBAPIError, match="append-only"):
            await s.execute(text("DELETE FROM audit_log"))
        await s.rollback()


async def test_audit_hash_chain_verifies_and_detects_tampering(
    seeded: None, database: Database
) -> None:
    async with database.sessionmaker() as s, s.begin():
        for i in range(3):
            await append_audit(
                s,
                actor_type="SYSTEM",
                actor_id="test",
                action="test.event",
                entity_type="test",
                entity_id=str(i),
                details={"n": i},
            )
    async with database.sessionmaker() as s:
        result = await verify_chain(s)
        assert result.ok
        assert result.records_checked >= 4

    # Tamper (bypassing the trigger as a superuser would) and confirm detection.
    async with database.sessionmaker() as s:
        await s.execute(text("ALTER TABLE audit_log DISABLE TRIGGER audit_log_append_only"))
        await s.execute(
            text(
                "UPDATE audit_log SET details = '{\"n\": 99}' "
                "WHERE entity_type = 'test' AND entity_id = '1'"
            )
        )
        broken = await verify_chain(s)
        await s.rollback()  # DDL is transactional in PostgreSQL: trigger and data restored
    assert not broken.ok
    assert broken.first_broken_id is not None
    async with database.sessionmaker() as s:
        assert (await verify_chain(s)).ok
