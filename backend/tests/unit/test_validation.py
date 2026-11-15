"""Each dataset validation rule fires on a minimal counter-example."""

from __future__ import annotations

from app.graph.model import AssetCategory as C
from app.graph.model import DependencyMode as M
from app.graph.model import ServiceType as S
from app.graph.validation import Severity, validate_snapshot
from tests.factories import asset, dep, snapshot


def rules(snap) -> set[str]:  # type: ignore[no-untyped-def]
    return {i.rule for i in validate_snapshot(snap)}


BASE = [asset("GSP-01", C.GRID_SUPPLY), asset("SUB-01", C.SUBSTATION)]
BASE_DEPS = [dep("GSP-01", "SUB-01")]


def test_minimal_valid_twin_has_no_issues() -> None:
    assert validate_snapshot(snapshot(BASE, BASE_DEPS)) == []


def test_unknown_reference() -> None:
    assert "D-001" in rules(snapshot(BASE, [*BASE_DEPS, dep("SUB-99", "SUB-01", group="x")]))


def test_self_loop() -> None:
    assert "D-002" in rules(snapshot(BASE, [*BASE_DEPS, dep("SUB-01", "SUB-01", group="x")]))


def test_group_mixing_service_types_and_modes_and_k() -> None:
    a = [*BASE, asset("PDN-01", C.POWER_DISTRIBUTION), asset("TEL-01", C.TELECOM_TOWER),
         asset("HOS-01", C.HOSPITAL)]  # fmt: skip
    d = [
        *BASE_DEPS,
        dep("SUB-01", "PDN-01"),
        dep("PDN-01", "TEL-01"),
        dep("PDN-01", "HOS-01", group="g", k=1),
        dep("TEL-01", "HOS-01", S.TELECOM, M.SOFT, group="g", k=2),
    ]
    assert {"D-003", "D-004", "D-005"} <= rules(snapshot(a, d))


def test_k_exceeds_providers() -> None:
    a = [*BASE, asset("PDN-01", C.POWER_DISTRIBUTION)]
    assert "D-006" in rules(snapshot(a, [*BASE_DEPS, dep("SUB-01", "PDN-01", k=2)]))


def test_provider_category_must_supply_service() -> None:
    a = [*BASE, asset("HOS-01", C.HOSPITAL), asset("PDN-01", C.POWER_DISTRIBUTION)]
    d = [*BASE_DEPS, dep("SUB-01", "PDN-01"), dep("PDN-01", "HOS-01"),
         dep("SUB-01", "HOS-01", S.WATER, M.SOFT, "water")]  # fmt: skip
    assert "D-007" in rules(snapshot(a, d))


def test_access_must_be_soft() -> None:
    a = [*BASE, asset("RD-01", C.ROAD_SEGMENT)]
    assert "D-008" in rules(
        snapshot(a, [*BASE_DEPS, dep("RD-01", "SUB-01", S.ACCESS, M.HARD, "a")])
    )


def test_geometry_type_and_bounds() -> None:
    bad_type = asset("RD-01", C.ROAD_SEGMENT, geometry={"type": "Point", "coordinates": (0.5, 0.5)})
    out_of_bounds = asset("SUB-02", geometry={"type": "Point", "coordinates": (5.0, 0.5)})
    found = rules(snapshot([*BASE, bad_type, out_of_bounds], [*BASE_DEPS, dep("GSP-01", "SUB-02")]))
    assert {"G-001", "G-002"} <= found


def test_attribute_rules() -> None:
    zone = asset("ZN-01", C.DEMAND_ZONE, population_served=None)
    no_profile = asset("SUB-02", recovery_profile=None)
    no_power = asset("HOS-01", C.HOSPITAL)
    not_source = asset("GSP-02", C.GRID_SUPPLY, is_source=False)
    found = rules(
        snapshot(
            [*BASE, zone, no_profile, no_power, not_source], [*BASE_DEPS, dep("GSP-01", "SUB-02")]
        )
    )
    assert {"A-001", "A-002", "A-004", "A-005"} <= found


def test_backup_without_power_dependency_is_a_warning() -> None:
    road = asset("RD-01", C.ROAD_SEGMENT, backup_power_hours=4)
    issues = [i for i in validate_snapshot(snapshot([*BASE, road], BASE_DEPS)) if i.rule == "A-003"]
    assert issues
    assert issues[0].severity is Severity.WARNING


def test_power_must_reach_a_source() -> None:
    a = [*BASE, asset("SUB-02"), asset("PDN-01", C.POWER_DISTRIBUTION)]
    d = [*BASE_DEPS, dep("PDN-01", "SUB-02"), dep("SUB-02", "PDN-01")]  # an unpowered loop
    issues = {(i.rule, i.subject) for i in validate_snapshot(snapshot(a, d))}
    assert ("P-001", "SUB-02") in issues
    assert ("P-001", "PDN-01") in issues
