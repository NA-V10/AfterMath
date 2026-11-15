"""Graph view over a TwinSnapshot: construction and deterministic traversal.

Edges point provider -> dependent ("A supplies B"). Thus:
  * upstream(B)   = everything B (transitively) depends on
  * downstream(A) = everything that (transitively) depends on A — structural reach,
    which is NOT the same as failure impact (redundancy is evaluated by the simulation engine).
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum

import networkx as nx

from app.graph.model import Dependency, ServiceType, TwinSnapshot, UnknownAssetError


class Direction(StrEnum):
    UPSTREAM = "upstream"
    DOWNSTREAM = "downstream"


@dataclass(frozen=True, slots=True)
class TraversalHit:
    code: str
    depth: int
    path: tuple[str, ...]  # focus ... code, following the traversal direction
    via: Dependency  # the edge through which `code` was first reached


class TwinGraph:
    """Immutable graph wrapper. Build once per snapshot and share."""

    def __init__(self, snapshot: TwinSnapshot) -> None:
        self.snapshot = snapshot
        g: nx.MultiDiGraph[str] = nx.MultiDiGraph()
        for asset in snapshot.assets:  # canonical order
            g.add_node(asset.code)
        for dep in snapshot.dependencies:
            g.add_edge(dep.provider, dep.dependent, key=dep.service_type.value, dep=dep)
        self.graph = g
        self._in: dict[str, tuple[Dependency, ...]] = {}
        self._out: dict[str, tuple[Dependency, ...]] = {}
        incoming: dict[str, list[Dependency]] = {a.code: [] for a in snapshot.assets}
        outgoing: dict[str, list[Dependency]] = {a.code: [] for a in snapshot.assets}
        for dep in snapshot.dependencies:
            if dep.dependent in incoming:
                incoming[dep.dependent].append(dep)
            if dep.provider in outgoing:
                outgoing[dep.provider].append(dep)
        self._in = {k: tuple(v) for k, v in incoming.items()}
        self._out = {k: tuple(v) for k, v in outgoing.items()}

    # ------------------------------------------------------------ direct neighbours
    def _require(self, code: str) -> None:
        if code not in self._in:
            raise UnknownAssetError(code)

    def providers_of(self, code: str) -> tuple[Dependency, ...]:
        """Edges into `code` (what it depends on), sorted canonically."""
        self._require(code)
        return self._in[code]

    def dependents_of(self, code: str) -> tuple[Dependency, ...]:
        """Edges out of `code` (what depends on it), sorted canonically."""
        self._require(code)
        return self._out[code]

    # ------------------------------------------------------------ traversal
    def traverse(
        self,
        focus: str,
        direction: Direction,
        *,
        max_depth: int | None = None,
        service_types: Iterable[ServiceType] | None = None,
        include_access: bool = False,
    ) -> list[TraversalHit]:
        """Breadth-first traversal. Deterministic: neighbours are expanded in canonical
        order, so results (including each node's reported shortest path) are independent of
        the order in which assets and dependencies were supplied.

        ACCESS edges are excluded by default because road access does not propagate
        function; when included they are only followed from the focus asset itself.
        """
        self._require(focus)
        allowed = set(service_types) if service_types is not None else None
        seen = {focus}
        hits: list[TraversalHit] = []
        queue: deque[tuple[str, int, tuple[str, ...]]] = deque([(focus, 0, (focus,))])
        while queue:
            node, depth, path = queue.popleft()
            if max_depth is not None and depth >= max_depth:
                continue
            edges = self._in[node] if direction is Direction.UPSTREAM else self._out[node]
            for dep in edges:
                if dep.service_type is ServiceType.ACCESS and not (
                    include_access and node == focus
                ):
                    continue
                if allowed is not None and dep.service_type not in allowed:
                    continue
                nxt = dep.provider if direction is Direction.UPSTREAM else dep.dependent
                if nxt in seen:
                    continue
                seen.add(nxt)
                hit = TraversalHit(code=nxt, depth=depth + 1, path=(*path, nxt), via=dep)
                hits.append(hit)
                queue.append((nxt, depth + 1, hit.path))
        return sorted(hits, key=lambda h: (h.depth, h.code))

    def upstream(
        self, focus: str, *, max_depth: int | None = None, include_access: bool = False
    ) -> list[TraversalHit]:
        return self.traverse(
            focus, Direction.UPSTREAM, max_depth=max_depth, include_access=include_access
        )

    def downstream(
        self, focus: str, *, max_depth: int | None = None, include_access: bool = False
    ) -> list[TraversalHit]:
        return self.traverse(
            focus, Direction.DOWNSTREAM, max_depth=max_depth, include_access=include_access
        )

    # ------------------------------------------------------------ structure
    def components(self) -> list[tuple[str, ...]]:
        """Weakly connected components over all edges, each sorted, ordered by first code."""
        comps = [tuple(sorted(c)) for c in nx.weakly_connected_components(self.graph)]
        return sorted(comps, key=lambda c: c[0])

    def component_of(self, code: str) -> tuple[str, ...]:
        self._require(code)
        for comp in self.components():
            if code in comp:
                return comp
        raise AssertionError("unreachable: every node belongs to a component")
