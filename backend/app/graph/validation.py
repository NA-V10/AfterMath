"""Deterministic dataset validation. Every rule has a stable code so tests and reports can
reference it. Errors block seeding; warnings are reported but allowed."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from enum import StrEnum

from app.graph.model import (
    AREA_CATEGORIES,
    LINEAR_CATEGORIES,
    POWER_SOURCE_CATEGORIES,
    SERVICE_PROVIDER_CATEGORIES,
    UNPOWERED_CATEGORIES,
    AssetCategory,
    Dependency,
    DependencyMode,
    LineStringGeometry,
    PointGeometry,
    PolygonGeometry,
    ServiceType,
    TwinSnapshot,
    geometry_positions,
)


class Severity(StrEnum):
    ERROR = "ERROR"
    WARNING = "WARNING"


@dataclass(frozen=True, slots=True, order=True)
class ValidationIssue:
    rule: str
    severity: Severity
    subject: str
    message: str


def validate_snapshot(snapshot: TwinSnapshot) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    issues += _check_references(snapshot)
    known = snapshot.assets_by_code
    resolvable = [d for d in snapshot.dependencies if d.provider in known and d.dependent in known]
    issues += _check_groups(resolvable)
    issues += _check_provider_categories(snapshot, resolvable)
    issues += _check_geometry(snapshot)
    issues += _check_attributes(snapshot, resolvable)
    issues += _check_power_reachability(snapshot, resolvable)
    return sorted(issues)


def errors_only(issues: list[ValidationIssue]) -> list[ValidationIssue]:
    return [i for i in issues if i.severity is Severity.ERROR]


def _err(rule: str, subject: str, message: str) -> ValidationIssue:
    return ValidationIssue(rule, Severity.ERROR, subject, message)


def _warn(rule: str, subject: str, message: str) -> ValidationIssue:
    return ValidationIssue(rule, Severity.WARNING, subject, message)


def _check_references(snapshot: TwinSnapshot) -> list[ValidationIssue]:
    known = snapshot.assets_by_code
    out = []
    for d in snapshot.dependencies:
        for role, code in (("provider", d.provider), ("dependent", d.dependent)):
            if code not in known:
                out.append(_err("D-001", code, f"{role} of {d.key} does not exist"))
        if d.provider == d.dependent:
            out.append(_err("D-002", d.provider, "self-dependency"))
    return out


def _check_groups(deps: list[Dependency]) -> list[ValidationIssue]:
    groups: dict[tuple[str, str], list[Dependency]] = defaultdict(list)
    for d in deps:
        groups[(d.dependent, d.redundancy_group)].append(d)
    out = []
    for (dependent, group), members in sorted(groups.items()):
        subject = f"{dependent}/{group}"
        if len({m.service_type for m in members}) > 1:
            out.append(_err("D-003", subject, "group mixes service types"))
        if len({m.mode for m in members}) > 1:
            out.append(_err("D-004", subject, "group mixes HARD and SOFT modes"))
        ks = {m.min_required for m in members}
        if len(ks) > 1:
            out.append(_err("D-005", subject, f"inconsistent min_required {sorted(ks)}"))
        elif (k := next(iter(ks))) > len(members):
            out.append(_err("D-006", subject, f"min_required={k} exceeds {len(members)} providers"))
    return out


def _check_provider_categories(
    snapshot: TwinSnapshot, deps: list[Dependency]
) -> list[ValidationIssue]:
    out = []
    for d in deps:
        provider = snapshot.asset(d.provider)
        if provider.category not in SERVICE_PROVIDER_CATEGORIES[d.service_type]:
            out.append(
                _err(
                    "D-007",
                    d.provider,
                    f"{provider.category} cannot provide {d.service_type} (to {d.dependent})",
                )
            )
        if d.service_type is ServiceType.ACCESS and d.mode is not DependencyMode.SOFT:
            out.append(_err("D-008", d.dependent, "ACCESS dependencies must be SOFT"))
    return out


def _check_geometry(snapshot: TwinSnapshot) -> list[ValidationIssue]:
    min_lon, min_lat, max_lon, max_lat = snapshot.bounds
    out = []
    for a in snapshot.assets:
        if a.category in LINEAR_CATEGORIES:
            expected: type = LineStringGeometry
        elif a.category in AREA_CATEGORIES:
            expected = PolygonGeometry
        else:
            expected = PointGeometry
        if not isinstance(a.geometry, expected):
            out.append(_err("G-001", a.code, f"{a.category} requires {expected.__name__}"))
        for lon, lat in geometry_positions(a.geometry):
            if not (min_lon <= lon <= max_lon and min_lat <= lat <= max_lat):
                out.append(_err("G-002", a.code, f"position ({lon}, {lat}) outside bounds"))
                break
    return out


def _check_attributes(snapshot: TwinSnapshot, deps: list[Dependency]) -> list[ValidationIssue]:
    has_power_dep = {d.dependent for d in deps if d.service_type is ServiceType.POWER}
    out = []
    for a in snapshot.assets:
        if a.category is AssetCategory.DEMAND_ZONE:
            if not a.population_served:
                out.append(_err("A-001", a.code, "demand zone requires population_served"))
        elif a.recovery_profile is None:
            out.append(_err("A-002", a.code, "infrastructure asset requires recovery_profile"))
        if a.backup_power_hours and a.code not in has_power_dep:
            out.append(_warn("A-003", a.code, "backup power declared but no POWER dependency"))
        needs_power = a.category not in UNPOWERED_CATEGORIES | POWER_SOURCE_CATEGORIES
        if needs_power and a.code not in has_power_dep:
            out.append(_err("A-004", a.code, "asset has no POWER dependency"))
        if a.category in POWER_SOURCE_CATEGORIES and not a.is_source:
            out.append(_err("A-005", a.code, f"{a.category} must be marked is_source"))
    return out


def _check_power_reachability(
    snapshot: TwinSnapshot, deps: list[Dependency]
) -> list[ValidationIssue]:
    """Every asset with a HARD POWER dependency must reach a power source through HARD POWER
    edges (ignoring redundancy — this checks the topology, not resilience)."""
    feeders: dict[str, list[str]] = defaultdict(list)
    for d in deps:
        if d.service_type is ServiceType.POWER and d.mode is DependencyMode.HARD:
            feeders[d.dependent].append(d.provider)
    sources = {
        a.code for a in snapshot.assets if a.category in POWER_SOURCE_CATEGORIES and a.is_source
    }
    powered: set[str] = set(sources)
    changed = True
    while changed:  # simple fixed point; graph is small
        changed = False
        for dependent, providers in sorted(feeders.items()):
            if dependent not in powered and any(p in powered for p in providers):
                powered.add(dependent)
                changed = True
    return [
        _err("P-001", code, "no HARD POWER path to a power source")
        for code in sorted(feeders)
        if code not in powered
    ]
