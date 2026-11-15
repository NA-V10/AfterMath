"""The synthetic district must be valid, meaningful, and clearly synthetic."""

from __future__ import annotations

import json

from app.graph.dataset import expand_dependencies, load_dataset_dir, to_snapshot
from app.graph.model import AssetCategory, PolygonGeometry, TwinSnapshot, geometry_positions
from app.graph.twin_graph import TwinGraph
from app.graph.validation import validate_snapshot
from tests.conftest import DATASET_DIR, SCENARIOS_DIR


def test_dataset_has_no_validation_issues(district: TwinSnapshot) -> None:
    assert validate_snapshot(district) == []


def test_asset_counts_within_phase1_target(district: TwinSnapshot) -> None:
    infra = [a for a in district.assets if a.category is not AssetCategory.DEMAND_ZONE]
    assert 30 <= len(infra) <= 50
    assert len({a.category for a in infra}) >= 10


def test_everything_is_marked_synthetic(dataset_files) -> None:  # type: ignore[no-untyped-def]
    assert dataset_files.manifest.synthetic is True
    assert all(a.metadata.get("synthetic") is True for a in dataset_files.assets)


def test_loading_is_deterministic() -> None:
    a = to_snapshot(load_dataset_dir(DATASET_DIR)[0])
    b = to_snapshot(load_dataset_dir(DATASET_DIR)[0])
    assert a.content_hash == b.content_hash


def test_every_dependency_is_explained(dataset_files) -> None:  # type: ignore[no-untyped-def]
    edges = expand_dependencies(dataset_files.dependents)
    assert all(len(e.description) >= 10 for e in edges)


def test_riverside_substation_downstream_matches_hand_derived_set(
    district_graph: TwinGraph,
) -> None:
    """Hand-derived in docs/PHASE_1_PLAN.md — structural reach of SUB-02 (no access edges)."""
    expected = {
        "PDN-03", "PDN-04", "HOS-02", "TEL-03", "WIN-01", "WTP-01", "ZN-04", "TEL-04",
        "WPS-03", "FUL-02", "ZN-05", "FIR-02", "WPS-02", "HOS-03", "ZN-07", "HOS-01",
        "ZN-01", "ZN-02", "ZN-03",
    }  # fmt: skip
    assert {h.code for h in district_graph.downstream("SUB-02")} == expected


def test_hillside_system_is_an_independent_component(district_graph: TwinGraph) -> None:
    comps = district_graph.components()
    assert len(comps) == 2
    assert district_graph.component_of("SOL-01") == (
        "RD-05", "SOL-01", "WIN-02", "WPS-01", "WTP-02", "ZN-06",
    )  # fmt: skip


def test_meridian_general_has_n_minus_1_power(district_graph: TwinGraph) -> None:
    power = [d for d in district_graph.providers_of("HOS-01") if d.redundancy_group == "power"]
    assert {d.provider for d in power} == {"PDN-02", "PDN-07"}
    assert all(d.min_required == 1 for d in power)


def test_scenarios_reference_existing_assets_and_stay_in_bounds(district: TwinSnapshot) -> None:
    files = sorted(SCENARIOS_DIR.glob("*.json"))
    assert {f.stem for f in files} >= {
        "substation-riverside", "river-flood", "power-telecom-combined",
    }  # fmt: skip
    min_lon, min_lat, max_lon, max_lat = district.bounds
    for f in files:
        scenario = json.loads(f.read_text(encoding="utf-8"))
        assert scenario["synthetic"] is True
        for event in scenario["initiating_events"]:
            if "asset_code" in event:
                assert event["asset_code"] in district.assets_by_code
            if "polygon" in event:
                poly = PolygonGeometry.model_validate(event["polygon"])
                for lon, lat in geometry_positions(poly):
                    assert min_lon <= lon <= max_lon
                    assert min_lat <= lat <= max_lat
