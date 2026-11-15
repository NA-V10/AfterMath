"""Dataset seeding: validate -> upsert in one transaction -> audit. Idempotent per version."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, InvalidInputError
from app.database import repositories as repo
from app.database.models import DatasetRelease
from app.graph.dataset import DatasetFiles, to_snapshot
from app.graph.validation import errors_only, validate_snapshot
from app.services.audit import append_audit


@dataclass(frozen=True, slots=True)
class SeedResult:
    status: Literal["created", "unchanged"]
    name: str
    version: str
    content_hash: str
    asset_count: int
    dependency_count: int
    warnings: list[str]


async def seed_dataset(
    session: AsyncSession, files: DatasetFiles, basemap: dict[str, Any], *, actor_id: str
) -> SeedResult:
    snapshot = to_snapshot(files)
    issues = validate_snapshot(snapshot)
    if errors := errors_only(issues):
        raise InvalidInputError(
            f"dataset failed validation with {len(errors)} error(s)",
            extra={"issues": [f"{e.rule} {e.subject}: {e.message}" for e in errors]},
        )
    warnings = [f"{i.rule} {i.subject}: {i.message}" for i in issues if i not in errors]

    def result(status: Literal["created", "unchanged"]) -> SeedResult:
        return SeedResult(
            status,
            snapshot.dataset_name,
            snapshot.dataset_version,
            snapshot.content_hash,
            len(snapshot.assets),
            len(snapshot.dependencies),
            warnings,
        )

    existing = await repo.find_release(session, snapshot.dataset_name, snapshot.dataset_version)
    if existing is not None:
        # The basemap is not part of the twin hash, so compare it explicitly.
        if existing.content_hash != snapshot.content_hash or existing.basemap != basemap:
            raise ConflictError(
                f"dataset {snapshot.dataset_name}@{snapshot.dataset_version} is already seeded "
                "with different content; bump the version in manifest.json"
            )
        if existing.is_current:
            return result("unchanged")

    await session.execute(update(DatasetRelease).values(is_current=False))
    await session.flush()
    await repo.replace_twin(session, snapshot)
    if existing is not None:  # re-activating an older, identical release
        existing.is_current = True
    else:
        session.add(
            DatasetRelease(
                name=snapshot.dataset_name,
                version=snapshot.dataset_version,
                content_hash=snapshot.content_hash,
                asset_count=len(snapshot.assets),
                dependency_count=len(snapshot.dependencies),
                basemap=basemap,
                bounds=list(snapshot.bounds),
                is_current=True,
            )
        )
    await append_audit(
        session,
        actor_type="SYSTEM",
        actor_id=actor_id,
        action="dataset.seeded",
        entity_type="dataset_release",
        entity_id=f"{snapshot.dataset_name}@{snapshot.dataset_version}",
        details={
            "content_hash": snapshot.content_hash,
            "assets": len(snapshot.assets),
            "dependencies": len(snapshot.dependencies),
            "warnings": warnings,
        },
    )
    return result("created")
