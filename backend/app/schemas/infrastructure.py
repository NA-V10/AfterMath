"""API response/request DTOs for the infrastructure twin."""

from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.graph.model import (
    AssetCategory,
    DependencyMode,
    PhysicalCondition,
    RecoveryProfile,
    ServiceType,
)
from app.graph.twin_graph import Direction


class _Out(BaseModel):
    model_config = ConfigDict(frozen=True)


class AssetRef(_Out):
    code: str
    name: str
    category: AssetCategory


class AssetSummary(_Out):
    id: uuid.UUID
    code: str
    name: str
    category: AssetCategory
    condition: PhysicalCondition = Field(description="Physical condition in the baseline twin.")
    criticality: int
    position: tuple[float, float] = Field(description="[lon, lat] marker position")
    elevation_m: float | None
    capacity: float | None
    capacity_unit: str | None
    utilization: float | None
    population_served: int | None
    is_source: bool
    backup_power_hours: float | None
    synthetic: Literal[True] = True


class DependencyEdge(_Out):
    provider: str
    dependent: str
    service_type: ServiceType
    mode: DependencyMode
    redundancy_group: str
    min_required: int
    description: str


class RequirementGroup(_Out):
    """A k-of-n requirement of an asset."""

    group: str
    service_type: ServiceType
    mode: DependencyMode
    min_required: int
    providers: list[AssetRef]
    spare_providers: int = Field(description="n - k: providers that can be lost without impact")
    description: str


class DependentLink(_Out):
    asset: AssetRef
    service_type: ServiceType
    mode: DependencyMode
    redundancy_group: str
    min_required: int
    description: str


class AssetDetail(AssetSummary):
    geometry: dict[str, Any]
    recovery_profile: RecoveryProfile | None
    metadata: dict[str, Any]
    requirements: list[RequirementGroup]
    dependents: list[DependentLink]
    upstream_count: int
    downstream_count: int
    component_size: int


class TraversalItem(_Out):
    asset: AssetRef
    depth: int
    path: list[str]
    via: DependencyEdge


class TraversalResult(_Out):
    focus: AssetRef
    direction: Direction
    max_depth: int | None
    include_access: bool
    items: list[TraversalItem]


class GraphNode(_Out):
    code: str
    name: str
    category: AssetCategory
    condition: PhysicalCondition
    criticality: int
    position: tuple[float, float]
    geometry: dict[str, Any] = Field(description="GeoJSON geometry (Point, LineString, Polygon)")
    population_served: int | None
    component: int


class GraphResult(_Out):
    dataset_version: str
    content_hash: str
    nodes: list[GraphNode]
    edges: list[DependencyEdge]


class CategoryHealth(_Out):
    total: int
    by_condition: dict[PhysicalCondition, int]


class InfrastructureHealth(_Out):
    picture: Literal["baseline"] = Field(
        description=(
            "Which operational picture this describes. Simulation pictures arrive in Phase 2."
        )
    )
    dataset_version: str
    content_hash: str
    asset_count: int
    infrastructure_asset_count: int
    demand_zone_count: int
    dependency_count: int
    population_total: int
    by_condition: dict[PhysicalCondition, int]
    by_category: dict[AssetCategory, CategoryHealth]
    component_count: int


class Page[T](BaseModel):
    items: list[T]
    next_cursor: str | None
