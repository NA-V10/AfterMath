"""Property-based tests of the simulation engine (docs/TESTING_STRATEGY.md P1-P8)."""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from app.graph.model import AssetCategory as C
from app.graph.model import Dependency, TwinSnapshot
from app.graph.model import DependencyMode as M
from app.graph.model import PhysicalCondition as P
from app.graph.model import ServiceType as S
from app.simulation.engine import simulate
from app.simulation.evaluator import (
    PHYS_LEVEL,
    DependencyIndex,
    _supply_of,
    evaluate,
    group_level,
)
from app.simulation.model import (
    AssetFailureEvent,
    EventKind,
    FunctionalStatus,
    SimulationConfig,
)
from tests.factories import asset, dep, snapshot


@st.composite
def twins(draw: st.DrawFn, prefix: str = "NN", max_nodes: int = 12) -> TwinSnapshot:
    """Random twins with sources, k-of-n HARD power groups, SOFT groups, cycles and backups."""
    n = draw(st.integers(min_value=2, max_value=max_nodes))
    codes = [f"{prefix}-{i:02d}" for i in range(n)]
    n_sources = draw(st.integers(min_value=1, max_value=max(1, n // 3)))
    assets = [asset(c, C.GRID_SUPPLY) for c in codes[:n_sources]]
    deps: list[Dependency] = []
    for c in codes[n_sources:]:
        backup = draw(st.sampled_from([None, None, 1.0, 2.5]))
        assets.append(asset(c, C.SUBSTATION, backup_power_hours=backup))
        others = [o for o in codes if o != c]
        providers = draw(st.lists(st.sampled_from(others), min_size=1, max_size=3, unique=True))
        k = draw(st.integers(min_value=1, max_value=len(providers)))
        deps += [dep(p, c, S.POWER, M.HARD, "power", k) for p in providers]
        if draw(st.booleans()):
            soft = draw(st.sampled_from([o for o in others if o not in providers] or others))
            if soft not in providers:
                deps.append(dep(soft, c, S.TELECOM, M.SOFT, "comms", 1))
    return snapshot(assets, deps)


def failures(snap: TwinSnapshot) -> st.SearchStrategy[list[AssetFailureEvent]]:
    codes = [a.code for a in snap.assets]
    return st.lists(
        st.builds(
            AssetFailureEvent,
            asset_code=st.sampled_from(codes),
            t_minutes=st.sampled_from([0, 0, 30, 90]),
            condition=st.sampled_from([P.DAMAGED, P.DEGRADED]),
        ),
        max_size=4,
    )


CFG = SimulationConfig(horizon_minutes=600)


@given(st.data())
def test_p1_identical_inputs_identical_outputs(data: st.DataObject) -> None:
    snap = data.draw(twins())
    events = data.draw(failures(snap))
    assert simulate(snap, events, CFG).result_hash == simulate(snap, events, CFG).result_hash


@given(st.data(), st.randoms(use_true_random=False))
def test_p2_order_of_assets_and_edges_does_not_matter(data: st.DataObject, rnd) -> None:  # type: ignore[no-untyped-def]
    snap = data.draw(twins())
    events = data.draw(failures(snap))
    assets, deps = list(snap.assets), list(snap.dependencies)
    rnd.shuffle(assets)
    rnd.shuffle(deps)
    shuffled = snapshot(assets, deps)
    assert simulate(snap, events, CFG).result_hash == simulate(shuffled, events, CFG).result_hash


@given(st.data())
def test_p3_final_state_is_a_fixed_point(data: st.DataObject) -> None:
    snap = data.draw(twins())
    idx = DependencyIndex(snap)
    conditions = {c: data.draw(st.sampled_from(list(P))) for c in idx.codes}
    backup = {c: data.draw(st.booleans()) for c in idx.codes}
    ev = evaluate(idx, conditions, backup)
    phys = {c: PHYS_LEVEL[conditions[c]] for c in idx.codes}
    assert {c: _supply_of(c, idx, phys, backup, ev.supply)[0] for c in idx.codes} == ev.supply


@given(st.data())
def test_p4_more_damage_never_improves_any_asset(data: st.DataObject) -> None:
    snap = data.draw(twins())
    idx = DependencyIndex(snap)
    hit = set(data.draw(st.lists(st.sampled_from(list(idx.codes)), max_size=4)))
    more = hit | set(data.draw(st.lists(st.sampled_from(list(idx.codes)), max_size=3)))
    backup = {c: data.draw(st.booleans()) for c in idx.codes}
    a = evaluate(idx, {c: P.DAMAGED if c in hit else P.INTACT for c in idx.codes}, backup)
    b = evaluate(idx, {c: P.DAMAGED if c in more else P.INTACT for c in idx.codes}, backup)
    assert all(b.supply[c] <= a.supply[c] for c in idx.codes)


@given(twins(prefix="AA"), twins(prefix="BB"), st.data())
def test_p5_unrelated_components_are_unaffected(
    left: TwinSnapshot, right: TwinSnapshot, data: st.DataObject
) -> None:
    combined = snapshot(
        list(left.assets) + list(right.assets), list(left.dependencies) + list(right.dependencies)
    )
    events = data.draw(failures(left))
    alone = {a.code: a.status for a in simulate(right, [], CFG).final_state}
    together = {a.code: a.status for a in simulate(combined, events, CFG).final_state}
    assert {c: together[c] for c in alone} == alone


@given(st.integers(min_value=1, max_value=5), st.data())
def test_p6_k_of_n_tolerates_exactly_n_minus_k_losses(n: int, data: st.DataObject) -> None:
    k = data.draw(st.integers(min_value=1, max_value=n))
    sources = [f"GS-{i:02d}" for i in range(n)]
    snap = snapshot(
        [*(asset(c, C.GRID_SUPPLY) for c in sources), asset("HOS-01", C.HOSPITAL)],
        [dep(c, "HOS-01", S.POWER, M.HARD, "power", k) for c in sources],
    )
    order = data.draw(st.permutations(sources))
    survivable = [AssetFailureEvent(asset_code=c) for c in order[: n - k]]
    assert {a.code: a.status for a in simulate(snap, survivable, CFG).final_state}["HOS-01"] is (
        FunctionalStatus.OPERATIONAL
    )
    fatal = [AssetFailureEvent(asset_code=c) for c in order[: n - k + 1]]
    assert {a.code: a.status for a in simulate(snap, fatal, CFG).final_state}["HOS-01"] is (
        FunctionalStatus.FAILED
    )


@given(st.data())
def test_p7_backup_exhaustion_happens_exactly_on_schedule(data: st.DataObject) -> None:
    snap = data.draw(twins())
    events = data.draw(failures(snap))
    r = simulate(snap, events, CFG)
    engaged: dict[str, int] = {}
    for e in r.events:
        if e.kind is EventKind.BACKUP_ENGAGED and e.asset_code:
            engaged[e.asset_code] = e.t_minutes + e.details["remaining_minutes"]
        elif e.kind is EventKind.BACKUP_DISENGAGED and e.asset_code:
            engaged.pop(e.asset_code, None)
        elif e.kind is EventKind.BACKUP_EXHAUSTED and e.asset_code:
            assert engaged.pop(e.asset_code) == e.t_minutes


@given(st.data())
def test_p8_fully_supplied_assets_satisfy_their_hard_requirements(data: st.DataObject) -> None:
    snap = data.draw(twins())
    r = simulate(snap, data.draw(failures(snap)), CFG)
    idx = DependencyIndex(snap)
    supply = {a.code: a.supply for a in r.final_state}
    for a in r.final_state:
        if a.status is FunctionalStatus.OPERATIONAL:
            assert all(group_level(g, supply) == 2 for g in idx.hard[a.code])
        if a.on_backup:
            assert any(
                group_level(g, supply) == 0 and g.service_type is S.POWER for g in idx.hard[a.code]
            )
