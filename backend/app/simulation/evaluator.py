"""Functional evaluation of the twin at one instant (pure, deterministic).

Supply levels (0 none, 1 reduced, 2 full) are the *greatest fixed point* of a monotone function
over the dependency graph (docs/SIMULATION_ENGINE.md §2, §2.1):

    sup(a) = min(phys(a), min over HARD groups g of a: kth_largest(sup of g's providers, k_g))

where a HARD POWER group that is unmet counts as fully supplied while backup power is available
(and the asset is physically functional). SOFT groups never reduce supply; they only degrade the
displayed status. Because the function is monotone on a finite lattice, Jacobi iteration from
the top reaches the unique greatest fixed point regardless of evaluation order, and cycles are
handled correctly.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from app.graph.model import (
    AssetCategory,
    Dependency,
    DependencyMode,
    PhysicalCondition,
    ServiceType,
    TwinSnapshot,
)
from app.simulation.model import Cause, CauseKind, FunctionalStatus

PHYS_LEVEL: dict[PhysicalCondition, int] = {
    PhysicalCondition.INTACT: 2,
    PhysicalCondition.DEGRADED: 1,
    PhysicalCondition.DAMAGED: 0,
    PhysicalCondition.DESTROYED: 0,
}

SOURCE_CATEGORIES = frozenset(
    {AssetCategory.GRID_SUPPLY, AssetCategory.POWER_GENERATION, AssetCategory.WATER_INTAKE}
)


@dataclass(frozen=True, slots=True)
class Group:
    name: str
    service_type: ServiceType
    mode: DependencyMode
    k: int
    providers: tuple[str, ...]


class DependencyIndex:
    """Requirement groups per asset (ACCESS excluded: it never affects function)."""

    def __init__(self, snapshot: TwinSnapshot) -> None:
        self.snapshot = snapshot
        self.codes: tuple[str, ...] = tuple(a.code for a in snapshot.assets)
        raw: dict[tuple[str, str], list[Dependency]] = {}
        for d in snapshot.dependencies:
            if d.service_type is ServiceType.ACCESS:
                continue
            raw.setdefault((d.dependent, d.redundancy_group), []).append(d)
        groups: dict[str, list[Group]] = {c: [] for c in self.codes}
        for (dependent, name), members in sorted(raw.items()):
            first = members[0]
            groups[dependent].append(
                Group(
                    name=name,
                    service_type=first.service_type,
                    mode=first.mode,
                    k=first.min_required,
                    providers=tuple(sorted(m.provider for m in members)),
                )
            )
        self.groups: dict[str, tuple[Group, ...]] = {c: tuple(g) for c, g in groups.items()}
        self.hard: dict[str, tuple[Group, ...]] = {
            c: tuple(g for g in gs if g.mode is DependencyMode.HARD)
            for c, gs in self.groups.items()
        }
        self.soft: dict[str, tuple[Group, ...]] = {
            c: tuple(g for g in gs if g.mode is DependencyMode.SOFT)
            for c, gs in self.groups.items()
        }
        dependents: dict[str, set[str]] = {c: set() for c in self.codes}
        for c, gs in self.groups.items():
            for g in gs:
                for p in g.providers:
                    dependents[p].add(c)
        self.dependents: dict[str, tuple[str, ...]] = {
            c: tuple(sorted(s)) for c, s in dependents.items()
        }
        self.sources = frozenset(
            a.code for a in snapshot.assets if a.is_source and a.category in SOURCE_CATEGORIES
        )


def group_level(group: Group, supply: Mapping[str, int]) -> int:
    """k-th largest provider supply (0 when fewer than k providers)."""
    levels = sorted((supply[p] for p in group.providers), reverse=True)
    return levels[group.k - 1] if len(levels) >= group.k else 0


@dataclass(frozen=True, slots=True)
class Evaluation:
    supply: dict[str, int]
    on_backup: frozenset[str]
    status: dict[str, FunctionalStatus]
    causes: dict[str, tuple[Cause, ...]]
    wave: dict[str, int]  # cascade depth at which each *changed* asset settled


def _supply_of(
    code: str,
    index: DependencyIndex,
    phys: Mapping[str, int],
    backup_available: Mapping[str, bool],
    supply: Mapping[str, int],
) -> tuple[int, bool]:
    level = phys[code]
    backup = False
    for g in index.hard[code]:
        gl = group_level(g, supply)
        if (
            gl == 0
            and g.service_type is ServiceType.POWER
            and phys[code] > 0
            and backup_available.get(code, False)
        ):
            backup = True
            gl = 2
        level = min(level, gl)
    return level, backup


def _greatest_fixed_point(
    index: DependencyIndex, phys: Mapping[str, int], backup_available: Mapping[str, bool]
) -> dict[str, int]:
    supply = dict(phys)  # top of the lattice, bounded by physical condition
    while True:
        nxt = {c: _supply_of(c, index, phys, backup_available, supply)[0] for c in index.codes}
        if nxt == supply:
            return supply
        supply = nxt


def _assign_waves(
    index: DependencyIndex,
    phys: Mapping[str, int],
    backup_available: Mapping[str, bool],
    previous: Mapping[str, int],
    final: Mapping[str, int],
) -> dict[str, int]:
    """Cascade depth per changed asset: Jacobi steps from the previous instant towards the new
    fixed point (each step moves values only towards their final value). Assets whose physical
    condition changed directly settle at wave 0."""
    # Wave 0: failures take effect directly; restorations take effect directly for assets whose
    # own requirements are already met at the previous instant (e.g. a repaired substation).
    f_prev = {c: _supply_of(c, index, phys, backup_available, previous)[0] for c in index.codes}
    x = {}
    for c in index.codes:
        if final[c] < previous[c]:
            x[c] = min(previous[c], phys[c])
        elif final[c] > previous[c]:
            x[c] = min(final[c], max(previous[c], f_prev[c]))
        else:
            x[c] = previous[c]
    waves = {c: 0 for c in index.codes if x[c] == final[c] and previous[c] != final[c]}
    step = 0
    while any(x[c] != final[c] for c in index.codes):
        step += 1
        fx = {c: _supply_of(c, index, phys, backup_available, x)[0] for c in index.codes}
        nxt = {}
        for c in index.codes:
            if final[c] < x[c]:
                nxt[c] = max(final[c], min(x[c], fx[c]))
            elif final[c] > x[c]:
                nxt[c] = min(final[c], max(x[c], fx[c]))
            else:
                nxt[c] = x[c]
        if nxt == x:  # e.g. a cycle revived only by the greatest fixed point
            for c in index.codes:
                if x[c] != final[c]:
                    waves[c] = step
            break
        for c in index.codes:
            if nxt[c] == final[c] and x[c] != final[c]:
                waves[c] = step
        x = nxt
    return waves


def evaluate(
    index: DependencyIndex,
    conditions: Mapping[str, PhysicalCondition],
    backup_available: Mapping[str, bool],
    previous_supply: Mapping[str, int] | None = None,
) -> Evaluation:
    phys = {c: PHYS_LEVEL[conditions[c]] for c in index.codes}
    supply = _greatest_fixed_point(index, phys, backup_available)

    on_backup: set[str] = set()
    status: dict[str, FunctionalStatus] = {}
    causes: dict[str, tuple[Cause, ...]] = {}
    for c in index.codes:
        _, backup = _supply_of(c, index, phys, backup_available, supply)
        if backup:
            on_backup.add(c)
        found: list[Cause] = []
        if phys[c] < 2:
            found.append(Cause(kind=CauseKind.PHYSICAL))
        for g in index.hard[c]:
            gl = group_level(g, supply)
            if gl < 2:
                down = tuple(p for p in g.providers if supply[p] < 2)
                kind = (
                    CauseKind.BACKUP
                    if gl == 0 and backup and g.service_type is ServiceType.POWER
                    else CauseKind.DEPENDENCY
                )
                found.append(
                    Cause(kind=kind, group=g.name, service_type=g.service_type, providers=down)
                )
        soft_unmet = False
        for g in index.soft[c]:
            if group_level(g, supply) == 0:
                soft_unmet = True
                found.append(
                    Cause(
                        kind=CauseKind.SOFT_DEPENDENCY,
                        group=g.name,
                        service_type=g.service_type,
                        providers=tuple(p for p in g.providers if supply[p] == 0),
                    )
                )
        if supply[c] == 0:
            status[c] = FunctionalStatus.FAILED
        elif backup:
            status[c] = FunctionalStatus.ON_BACKUP
        elif supply[c] == 1 or soft_unmet:
            status[c] = FunctionalStatus.DEGRADED
        else:
            status[c] = FunctionalStatus.OPERATIONAL
        causes[c] = tuple(found)

    previous = previous_supply if previous_supply is not None else supply
    waves = _assign_waves(index, phys, backup_available, previous, supply)
    return Evaluation(supply, frozenset(on_backup), status, causes, waves)


def isolated_assets(index: DependencyIndex, supply: Mapping[str, int]) -> frozenset[str]:
    """Serving assets with at least one HARD requirement that cannot be traced back to a serving
    source through serving HARD providers (e.g. a hospital island running on its generator)."""
    reached = {s for s in index.sources if supply[s] > 0}
    frontier = sorted(reached)
    while frontier:
        nxt: list[str] = []
        for p in frontier:
            for d in index.dependents[p]:
                if d in reached or supply[d] == 0:
                    continue
                if any(p in g.providers for g in index.hard[d]):
                    reached.add(d)
                    nxt.append(d)
        frontier = sorted(nxt)
    return frozenset(
        c
        for c in index.codes
        if supply[c] > 0 and index.hard[c] and c not in reached and c not in index.sources
    )
