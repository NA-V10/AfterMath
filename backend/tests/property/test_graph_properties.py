"""Property-based tests of graph traversal (docs/TESTING_STRATEGY.md P2, P5 for traversal)."""

from __future__ import annotations

import networkx as nx
from hypothesis import given
from hypothesis import strategies as st

from app.graph.model import Asset, Dependency, ServiceType, TwinSnapshot
from app.graph.twin_graph import TwinGraph
from tests.factories import asset, dep, snapshot


@st.composite
def random_twin(
    draw: st.DrawFn, prefix: str = "NN", max_nodes: int = 14
) -> tuple[list[Asset], list[Dependency]]:
    n = draw(st.integers(min_value=1, max_value=max_nodes))
    codes = [f"{prefix}-{i:02d}" for i in range(n)]
    pairs = draw(
        st.lists(
            st.tuples(
                st.sampled_from(codes),
                st.sampled_from(codes),
                st.sampled_from([ServiceType.POWER, ServiceType.TELECOM, ServiceType.WATER]),
            ),
            max_size=n * 3,
        )
    )
    seen: set[tuple[str, str, ServiceType]] = set()
    deps = []
    for p, d, s in pairs:
        if p != d and (p, d, s) not in seen:
            seen.add((p, d, s))
            deps.append(dep(p, d, s, group=s.value.lower()))
    return [asset(c) for c in codes], deps


def _result(g: TwinGraph, code: str) -> tuple[object, object]:
    return (
        [(h.code, h.depth, h.path) for h in g.downstream(code)],
        [(h.code, h.depth, h.path) for h in g.upstream(code)],
    )


@given(random_twin(), st.randoms(use_true_random=False))
def test_results_independent_of_input_order(twin, rnd) -> None:  # type: ignore[no-untyped-def]
    assets, deps = twin
    shuffled_a, shuffled_d = assets[:], deps[:]
    rnd.shuffle(shuffled_a)
    rnd.shuffle(shuffled_d)
    s1, s2 = snapshot(assets, deps), snapshot(shuffled_a, shuffled_d)
    assert s1.content_hash == s2.content_hash
    g1, g2 = TwinGraph(s1), TwinGraph(s2)
    for a in assets:
        assert _result(g1, a.code) == _result(g2, a.code)


@given(random_twin())
def test_upstream_downstream_duality(twin) -> None:  # type: ignore[no-untyped-def]
    g = TwinGraph(snapshot(*twin))
    codes = [a.code for a in twin[0]]
    for a in codes:
        down = {h.code for h in g.downstream(a)}
        for b in codes:
            assert (b in down) == (a in {h.code for h in g.upstream(b)})


@given(random_twin())
def test_depths_are_shortest_paths_and_paths_follow_edges(twin) -> None:  # type: ignore[no-untyped-def]
    snap: TwinSnapshot = snapshot(*twin)
    g = TwinGraph(snap)
    simple = nx.DiGraph([(d.provider, d.dependent) for d in snap.dependencies])
    simple.add_nodes_from(a.code for a in snap.assets)
    for a in snap.assets:
        lengths = nx.single_source_shortest_path_length(simple, a.code)
        hits = g.downstream(a.code)
        assert {h.code: h.depth for h in hits} == {k: v for k, v in lengths.items() if k != a.code}
        for h in hits:
            assert len(h.path) == h.depth + 1
            assert h.path[0] == a.code
            assert h.path[-1] == h.code
            assert all(simple.has_edge(u, v) for u, v in zip(h.path, h.path[1:], strict=False))


@given(random_twin(prefix="AA"), random_twin(prefix="BB"))
def test_disconnected_components_never_reach_each_other(left, right) -> None:  # type: ignore[no-untyped-def]
    g = TwinGraph(snapshot(left[0] + right[0], left[1] + right[1]))
    for a in left[0]:
        reached = {h.code for h in g.downstream(a.code)} | {h.code for h in g.upstream(a.code)}
        assert all(code.startswith("AA-") for code in reached)
        assert all(code.startswith("AA-") for code in g.component_of(a.code))


@given(random_twin(), st.integers(min_value=1, max_value=4))
def test_max_depth_is_respected(twin, depth: int) -> None:  # type: ignore[no-untyped-def]
    g = TwinGraph(snapshot(*twin))
    for a in twin[0]:
        assert all(h.depth <= depth for h in g.downstream(a.code, max_depth=depth))
