"""Builders for small, hand-made twins used by unit and property tests."""

from __future__ import annotations

from typing import Any

from app.graph.model import (
    Asset,
    AssetCategory,
    Dependency,
    DependencyMode,
    RecoveryProfile,
    ServiceType,
    Trade,
    TwinSnapshot,
)

PROFILE = RecoveryProfile(
    trade=Trade.ELECTRICAL, crew_size=1, repair_minutes=60, replace_minutes=120, cost=1
)


def asset(code: str, category: AssetCategory = AssetCategory.SUBSTATION, **kw: Any) -> Asset:
    defaults: dict[str, Any] = {
        "code": code,
        "name": f"Test {code}",
        "category": category,
        "geometry": {"type": "Point", "coordinates": (0.5, 0.5)},
        "criticality": 50,
        "recovery_profile": PROFILE,
        "is_source": category in (AssetCategory.GRID_SUPPLY, AssetCategory.POWER_GENERATION),
    }
    if category in (AssetCategory.ROAD_SEGMENT, AssetCategory.BRIDGE):
        defaults["geometry"] = {"type": "LineString", "coordinates": ((0.1, 0.1), (0.2, 0.2))}
    if category is AssetCategory.DEMAND_ZONE:
        defaults["geometry"] = {
            "type": "Polygon",
            "coordinates": (((0.1, 0.1), (0.2, 0.1), (0.2, 0.2), (0.1, 0.1)),),
        }
        defaults["recovery_profile"] = None
        defaults["population_served"] = 100
    defaults.update(kw)
    return Asset.model_validate(defaults)


def dep(
    provider: str,
    dependent: str,
    service_type: ServiceType = ServiceType.POWER,
    mode: DependencyMode = DependencyMode.HARD,
    group: str = "power",
    k: int = 1,
) -> Dependency:
    return Dependency(
        provider=provider,
        dependent=dependent,
        service_type=service_type,
        mode=mode,
        redundancy_group=group,
        min_required=k,
        description="test edge",
    )


def snapshot(assets: list[Asset], deps: list[Dependency]) -> TwinSnapshot:
    return TwinSnapshot(
        dataset_name="test",
        dataset_version="0.0.1",
        bounds=(0.0, 0.0, 1.0, 1.0),
        assets=tuple(assets),
        dependencies=tuple(deps),
    )
