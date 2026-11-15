"""Mapping between ORM rows and the pure domain model (TwinSnapshot)."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.database.models import DatasetRelease, InfrastructureAsset, InfrastructureDependency
from app.graph.model import Asset, Dependency, TwinSnapshot


async def current_release(session: AsyncSession) -> DatasetRelease | None:
    return await session.scalar(select(DatasetRelease).where(DatasetRelease.is_current))


async def find_release(session: AsyncSession, name: str, version: str) -> DatasetRelease | None:
    return await session.scalar(
        select(DatasetRelease).where(DatasetRelease.name == name, DatasetRelease.version == version)
    )


def _asset_from_row(row: InfrastructureAsset) -> Asset:
    return Asset.model_validate(
        {
            "code": row.code,
            "name": row.name,
            "category": row.category,
            "geometry": row.geometry,
            "elevation_m": row.elevation_m,
            "physical_condition": row.physical_condition,
            "criticality": row.criticality,
            "capacity": row.capacity,
            "capacity_unit": row.capacity_unit,
            "utilization": row.utilization,
            "population_served": row.population_served,
            "is_source": row.is_source,
            "backup_power_hours": row.backup_power_hours,
            "recovery_profile": row.recovery_profile,
            "metadata": row.meta,
        }
    )


def _row_values(asset: Asset, dataset_version: str) -> dict[str, Any]:
    data = asset.model_dump(mode="json")
    return {
        "code": asset.code,
        "name": asset.name,
        "category": asset.category.value,
        "geometry": data["geometry"],
        "elevation_m": asset.elevation_m,
        "physical_condition": asset.physical_condition.value,
        "criticality": asset.criticality,
        "capacity": asset.capacity,
        "capacity_unit": asset.capacity_unit,
        "utilization": asset.utilization,
        "population_served": asset.population_served,
        "is_source": asset.is_source,
        "backup_power_hours": asset.backup_power_hours,
        "recovery_profile": data["recovery_profile"],
        "meta": data["metadata"],
        "dataset_version": dataset_version,
    }


async def load_snapshot(
    session: AsyncSession, release: DatasetRelease
) -> tuple[TwinSnapshot, dict[str, uuid.UUID]]:
    rows: Sequence[InfrastructureAsset] = (
        await session.scalars(select(InfrastructureAsset).order_by(InfrastructureAsset.code))
    ).all()
    provider = aliased(InfrastructureAsset)
    dependent = aliased(InfrastructureAsset)
    edges = (
        await session.execute(
            select(InfrastructureDependency, provider.code, dependent.code)
            .join(provider, InfrastructureDependency.provider_id == provider.id)
            .join(dependent, InfrastructureDependency.dependent_id == dependent.id)
        )
    ).all()
    snapshot = TwinSnapshot(
        dataset_name=release.name,
        dataset_version=release.version,
        bounds=tuple(release.bounds),
        assets=tuple(_asset_from_row(r) for r in rows),
        dependencies=tuple(
            Dependency(
                provider=p_code,
                dependent=d_code,
                service_type=e.service_type,
                mode=e.mode,
                redundancy_group=e.redundancy_group,
                min_required=e.min_required,
                description=e.description,
            )
            for e, p_code, d_code in edges
        ),
    )
    return snapshot, {r.code: r.id for r in rows}


async def replace_twin(session: AsyncSession, snapshot: TwinSnapshot) -> None:
    """Upsert assets by code, replace all dependencies, remove assets no longer present."""
    await session.execute(delete(InfrastructureDependency))
    existing = {r.code: r for r in (await session.scalars(select(InfrastructureAsset))).all()}
    wanted = snapshot.assets_by_code
    for code, row in existing.items():
        if code not in wanted:
            await session.delete(row)
    ids: dict[str, uuid.UUID] = {}
    for asset in snapshot.assets:
        values = _row_values(asset, snapshot.dataset_version)
        current = existing.get(asset.code)
        if current is None:
            current = InfrastructureAsset(id=uuid.uuid4(), **values)
            session.add(current)
        else:
            for key, value in values.items():
                setattr(current, key, value)
            current.version += 1
        ids[asset.code] = current.id
    await session.flush()
    session.add_all(
        InfrastructureDependency(
            provider_id=ids[d.provider],
            dependent_id=ids[d.dependent],
            service_type=d.service_type.value,
            mode=d.mode.value,
            redundancy_group=d.redundancy_group,
            min_required=d.min_required,
            description=d.description,
        )
        for d in snapshot.dependencies
    )
    await session.flush()
