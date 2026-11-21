from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Query

from app.api.deps import QueriesDep, TwinDep
from app.core.errors import InvalidInputError
from app.graph.model import AssetCategory, PhysicalCondition, ServiceType
from app.graph.twin_graph import Direction
from app.schemas.infrastructure import (
    AssetDetail,
    AssetSummary,
    GraphResult,
    InfrastructureHealth,
    Page,
    TraversalResult,
)
from app.schemas.simulation import CriticalityReport
from app.services import analysis_cache
from app.services.infrastructure import AssetFilter

router = APIRouter(prefix="/infrastructure", tags=["infrastructure"])


def _parse_bbox(raw: str | None) -> tuple[float, float, float, float] | None:
    if raw is None:
        return None
    try:
        parts = tuple(float(p) for p in raw.split(","))
    except ValueError:
        raise InvalidInputError("bbox must be 'minLon,minLat,maxLon,maxLat'") from None
    if len(parts) != 4 or parts[0] > parts[2] or parts[1] > parts[3]:
        raise InvalidInputError("bbox must be 'minLon,minLat,maxLon,maxLat' with min <= max")
    return (parts[0], parts[1], parts[2], parts[3])


@router.get("/assets", response_model=Page[AssetSummary])
async def list_assets(
    queries: QueriesDep,
    category: Annotated[list[AssetCategory] | None, Query()] = None,
    condition: Annotated[list[PhysicalCondition] | None, Query()] = None,
    min_criticality: Annotated[int | None, Query(ge=0, le=100)] = None,
    q: Annotated[str | None, Query(min_length=1, max_length=64)] = None,
    bbox: Annotated[str | None, Query(description="minLon,minLat,maxLon,maxLat")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 200,
    cursor: Annotated[str | None, Query(max_length=16)] = None,
) -> Page[AssetSummary]:
    flt = AssetFilter(
        categories=frozenset(category or ()),
        conditions=frozenset(condition or ()),
        min_criticality=min_criticality,
        q=q,
        bbox=_parse_bbox(bbox),
    )
    return queries.list_assets(flt, limit=limit, cursor=cursor)


@router.get("/assets/{code}", response_model=AssetDetail)
async def get_asset(code: str, queries: QueriesDep) -> AssetDetail:
    return queries.asset_detail(code)


@router.get("/assets/{code}/dependencies", response_model=TraversalResult)
async def get_dependencies(
    code: str,
    queries: QueriesDep,
    direction: Direction = Direction.DOWNSTREAM,
    depth: Annotated[int | None, Query(ge=1, le=20)] = None,
    service_type: Annotated[list[ServiceType] | None, Query()] = None,
    include_access: bool = False,
) -> TraversalResult:
    return queries.traverse(
        code,
        direction,
        max_depth=depth,
        service_types=frozenset(service_type) if service_type else None,
        include_access=include_access,
    )


@router.get("/graph", response_model=GraphResult)
async def get_graph(queries: QueriesDep) -> GraphResult:
    return queries.graph_view()


@router.get("/health", response_model=InfrastructureHealth)
async def get_health(queries: QueriesDep) -> InfrastructureHealth:
    return queries.health()


@router.get("/basemap", response_model=dict[str, Any])
async def get_basemap(queries: QueriesDep) -> dict[str, Any]:
    """Synthetic basemap (GeoJSON FeatureCollection) for the fictional district."""
    return queries.twin.basemap


@router.get("/criticality", response_model=CriticalityReport)
async def get_criticality(twin: TwinDep) -> CriticalityReport:
    """Structural criticality by exact N-1 simulation; single points of failure flagged."""
    return CriticalityReport(
        dataset_version=twin.snapshot.dataset_version,
        horizon_minutes=analysis_cache.CRITICALITY_HORIZON_MINUTES,
        entries=await analysis_cache.criticality(twin.snapshot),
    )
