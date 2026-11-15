"""Dataset file format (authoring format) and conversion to a `TwinSnapshot`.

A dataset directory contains:
  manifest.json      — name, version, bounds, synthetic flag
  assets.json        — list of `Asset`
  dependencies.json  — list of `DependencyGroupRecord` (grouped per dependent for readability)
  basemap.geojson    — synthetic basemap FeatureCollection (rendering only)

Pure parsing: callers pass file *contents*; reading files is done by `load_dataset_dir`,
which only uses the standard library.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.graph.model import (
    ASSET_CODE_PATTERN,
    Asset,
    Dependency,
    DependencyMode,
    ServiceType,
    TwinSnapshot,
)

_STRICT = ConfigDict(frozen=True, extra="forbid")


class DatasetManifest(BaseModel):
    model_config = _STRICT
    name: str = Field(pattern=r"^[a-z0-9-]+$")
    version: str = Field(pattern=r"^\d+\.\d+\.\d+$")
    synthetic: Literal[True]
    description: str
    bounds: tuple[float, float, float, float]
    center: tuple[float, float]


class DependencyGroupRecord(BaseModel):
    """One requirement group of one dependent: needs `min_required` of `providers`."""

    model_config = _STRICT
    group: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,40}$")
    service_type: ServiceType
    mode: DependencyMode
    min_required: int = Field(default=1, ge=1)
    providers: tuple[str, ...] = Field(min_length=1)
    description: str


class DependentRecord(BaseModel):
    model_config = _STRICT
    dependent: str = Field(pattern=ASSET_CODE_PATTERN)
    requirements: tuple[DependencyGroupRecord, ...]


class DatasetFiles(BaseModel):
    """The parsed content of a dataset directory."""

    model_config = _STRICT
    manifest: DatasetManifest
    assets: tuple[Asset, ...]
    dependents: tuple[DependentRecord, ...]


def expand_dependencies(dependents: tuple[DependentRecord, ...]) -> list[Dependency]:
    edges: list[Dependency] = []
    for record in dependents:
        for req in record.requirements:
            for provider in req.providers:
                edges.append(
                    Dependency(
                        provider=provider,
                        dependent=record.dependent,
                        service_type=req.service_type,
                        mode=req.mode,
                        redundancy_group=req.group,
                        min_required=req.min_required,
                        description=req.description,
                    )
                )
    return edges


def to_snapshot(files: DatasetFiles) -> TwinSnapshot:
    return TwinSnapshot(
        dataset_name=files.manifest.name,
        dataset_version=files.manifest.version,
        bounds=files.manifest.bounds,
        assets=files.assets,
        dependencies=tuple(expand_dependencies(files.dependents)),
    )


def parse_dataset(manifest: Any, assets: Any, dependencies: Any) -> DatasetFiles:
    return DatasetFiles.model_validate(
        {"manifest": manifest, "assets": assets, "dependents": dependencies}
    )


def _read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def load_dataset_dir(directory: Path) -> tuple[DatasetFiles, dict[str, Any]]:
    """Read and parse a dataset directory. Returns (files, basemap FeatureCollection)."""
    files = parse_dataset(
        _read_json(directory / "manifest.json"),
        _read_json(directory / "assets.json"),
        _read_json(directory / "dependencies.json"),
    )
    basemap = _read_json(directory / "basemap.geojson")
    if not isinstance(basemap, dict) or basemap.get("type") != "FeatureCollection":
        raise ValueError("basemap.geojson must be a GeoJSON FeatureCollection")
    return files, basemap
