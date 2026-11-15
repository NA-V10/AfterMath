"""Immutable domain model of the infrastructure digital twin.

Pure module: no I/O, no web, no database. Every engine consumes a `TwinSnapshot`.
All data described here is SYNTHETIC.
"""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from functools import cached_property
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ASSET_CODE_PATTERN = r"^[A-Z]{2,5}-\d{2,3}$|^[A-Z]{2,5}-[A-Z]{2,5}$"


class AssetCategory(StrEnum):
    GRID_SUPPLY = "GRID_SUPPLY"
    POWER_GENERATION = "POWER_GENERATION"
    SUBSTATION = "SUBSTATION"
    POWER_DISTRIBUTION = "POWER_DISTRIBUTION"
    HOSPITAL = "HOSPITAL"
    TELECOM_HUB = "TELECOM_HUB"
    TELECOM_TOWER = "TELECOM_TOWER"
    DATA_CENTER = "DATA_CENTER"
    EMERGENCY_OPS_CENTER = "EMERGENCY_OPS_CENTER"
    FIRE_STATION = "FIRE_STATION"
    WATER_INTAKE = "WATER_INTAKE"
    WATER_TREATMENT = "WATER_TREATMENT"
    WATER_PUMPING = "WATER_PUMPING"
    FUEL_DEPOT = "FUEL_DEPOT"
    ROAD_SEGMENT = "ROAD_SEGMENT"
    BRIDGE = "BRIDGE"
    DEMAND_ZONE = "DEMAND_ZONE"


class PhysicalCondition(StrEnum):
    INTACT = "INTACT"
    DEGRADED = "DEGRADED"
    DAMAGED = "DAMAGED"
    DESTROYED = "DESTROYED"


class ServiceType(StrEnum):
    POWER = "POWER"
    TELECOM = "TELECOM"
    WATER = "WATER"
    FUEL = "FUEL"
    DATA = "DATA"
    HEALTHCARE = "HEALTHCARE"
    ACCESS = "ACCESS"


class DependencyMode(StrEnum):
    HARD = "HARD"
    SOFT = "SOFT"


class Trade(StrEnum):
    ELECTRICAL = "ELECTRICAL"
    TELECOM = "TELECOM"
    WATER = "WATER"
    CIVIL = "CIVIL"
    MECHANICAL = "MECHANICAL"


# Which provider categories may supply which service (used by dataset validation).
SERVICE_PROVIDER_CATEGORIES: dict[ServiceType, frozenset[AssetCategory]] = {
    ServiceType.POWER: frozenset(
        {
            AssetCategory.GRID_SUPPLY,
            AssetCategory.POWER_GENERATION,
            AssetCategory.SUBSTATION,
            AssetCategory.POWER_DISTRIBUTION,
        }
    ),
    ServiceType.TELECOM: frozenset({AssetCategory.TELECOM_HUB, AssetCategory.TELECOM_TOWER}),
    ServiceType.WATER: frozenset(
        {AssetCategory.WATER_INTAKE, AssetCategory.WATER_TREATMENT, AssetCategory.WATER_PUMPING}
    ),
    ServiceType.FUEL: frozenset({AssetCategory.FUEL_DEPOT}),
    ServiceType.DATA: frozenset({AssetCategory.DATA_CENTER}),
    ServiceType.HEALTHCARE: frozenset({AssetCategory.HOSPITAL}),
    ServiceType.ACCESS: frozenset({AssetCategory.ROAD_SEGMENT, AssetCategory.BRIDGE}),
}

POWER_SOURCE_CATEGORIES = frozenset({AssetCategory.GRID_SUPPLY, AssetCategory.POWER_GENERATION})
UNPOWERED_CATEGORIES = frozenset({AssetCategory.ROAD_SEGMENT, AssetCategory.BRIDGE})
LINEAR_CATEGORIES = UNPOWERED_CATEGORIES
AREA_CATEGORIES = frozenset({AssetCategory.DEMAND_ZONE})

_FROZEN = ConfigDict(frozen=True, extra="forbid")

Longitude = Annotated[float, Field(ge=-180, le=180)]
Latitude = Annotated[float, Field(ge=-90, le=90)]
Position = tuple[Longitude, Latitude]


# ------------------------------------------------------------------ GeoJSON geometry
class PointGeometry(BaseModel):
    model_config = _FROZEN
    type: Literal["Point"]
    coordinates: Position


class LineStringGeometry(BaseModel):
    model_config = _FROZEN
    type: Literal["LineString"]
    coordinates: tuple[Position, ...] = Field(min_length=2)


class PolygonGeometry(BaseModel):
    model_config = _FROZEN
    type: Literal["Polygon"]
    coordinates: tuple[tuple[Position, ...], ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _rings_closed(self) -> PolygonGeometry:
        for ring in self.coordinates:
            if len(ring) < 4 or ring[0] != ring[-1]:
                raise ValueError("polygon rings need >= 4 positions and must be closed")
        return self


Geometry = Annotated[
    PointGeometry | LineStringGeometry | PolygonGeometry, Field(discriminator="type")
]


def geometry_positions(geometry: Geometry) -> list[Position]:
    if isinstance(geometry, PointGeometry):
        return [geometry.coordinates]
    if isinstance(geometry, LineStringGeometry):
        return list(geometry.coordinates)
    return [pos for ring in geometry.coordinates for pos in ring]


def representative_point(geometry: Geometry) -> Position:
    """Deterministic label/marker position: the point itself, the middle vertex of a line,
    or the vertex average of a polygon's outer ring (excluding the closing vertex)."""
    if isinstance(geometry, PointGeometry):
        return geometry.coordinates
    if isinstance(geometry, LineStringGeometry):
        coords = geometry.coordinates
        if len(coords) % 2 == 1:
            return coords[len(coords) // 2]
        a, b = coords[len(coords) // 2 - 1], coords[len(coords) // 2]
        return ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
    ring = geometry.coordinates[0][:-1]
    return (
        round(sum(p[0] for p in ring) / len(ring), 6),
        round(sum(p[1] for p in ring) / len(ring), 6),
    )


# ------------------------------------------------------------------ assets & dependencies
class RecoveryProfile(BaseModel):
    """What it takes to repair/replace the asset (used from Phase 4)."""

    model_config = _FROZEN
    trade: Trade
    crew_size: int = Field(ge=1, le=20)
    repair_minutes: int = Field(gt=0)
    replace_minutes: int = Field(gt=0)
    parts: dict[str, int] = Field(default_factory=dict, description="consumed by a repair")
    replace_parts: dict[str, int] = Field(
        default_factory=dict, description="consumed by a full replacement"
    )
    cost: int = Field(ge=0, description="repair cost, synthetic currency units")


class Asset(BaseModel):
    model_config = _FROZEN

    code: str = Field(pattern=ASSET_CODE_PATTERN)
    name: str = Field(min_length=1, max_length=120)
    category: AssetCategory
    geometry: Geometry
    elevation_m: float | None = Field(default=None, ge=-100, le=9000)
    physical_condition: PhysicalCondition = PhysicalCondition.INTACT
    criticality: int = Field(ge=0, le=100)
    capacity: float | None = Field(default=None, ge=0)
    capacity_unit: str | None = None
    utilization: float | None = Field(default=None, ge=0, le=1)
    population_served: int | None = Field(default=None, ge=0)
    is_source: bool = False
    backup_power_hours: float | None = Field(default=None, ge=0, le=720)
    recovery_profile: RecoveryProfile | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def position(self) -> Position:
        return representative_point(self.geometry)


class Dependency(BaseModel):
    """Directed edge provider -> dependent. `dependent` needs at least `min_required` serving
    providers among the edges sharing its (dependent, redundancy_group)."""

    model_config = _FROZEN

    provider: str = Field(pattern=ASSET_CODE_PATTERN)
    dependent: str = Field(pattern=ASSET_CODE_PATTERN)
    service_type: ServiceType
    mode: DependencyMode
    redundancy_group: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,40}$")
    min_required: int = Field(ge=1)
    description: str = Field(min_length=1, max_length=300)

    @property
    def key(self) -> tuple[str, str, str]:
        return (self.provider, self.dependent, self.service_type.value)


class TwinSnapshot(BaseModel):
    """An immutable, canonically ordered view of the twin. Engines only ever see this."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    dataset_name: str
    dataset_version: str
    bounds: tuple[float, float, float, float]  # min_lon, min_lat, max_lon, max_lat
    assets: tuple[Asset, ...]
    dependencies: tuple[Dependency, ...]

    @model_validator(mode="after")
    def _canonical_and_unique(self) -> TwinSnapshot:
        codes = [a.code for a in self.assets]
        if len(codes) != len(set(codes)):
            dupes = sorted({c for c in codes if codes.count(c) > 1})
            raise ValueError(f"duplicate asset codes: {dupes}")
        keys = [d.key for d in self.dependencies]
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate dependency (provider, dependent, service_type)")
        # Canonical order makes every downstream computation order-independent.
        object.__setattr__(self, "assets", tuple(sorted(self.assets, key=lambda a: a.code)))
        object.__setattr__(
            self, "dependencies", tuple(sorted(self.dependencies, key=lambda d: d.key))
        )
        return self

    @cached_property
    def assets_by_code(self) -> dict[str, Asset]:
        return {a.code: a for a in self.assets}

    @cached_property
    def content_hash(self) -> str:
        """SHA-256 of the canonical JSON content; identifies a snapshot exactly."""
        payload = self.model_dump(mode="json")
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def asset(self, code: str) -> Asset:
        try:
            return self.assets_by_code[code]
        except KeyError:
            raise UnknownAssetError(code) from None


class UnknownAssetError(KeyError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code

    def __str__(self) -> str:
        return f"unknown asset code: {self.code}"
