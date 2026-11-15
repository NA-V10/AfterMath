"""Read-side queries over the current twin. All results derive from the immutable snapshot."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass

from app.core.errors import NotFoundError
from app.graph.model import (
    Asset,
    AssetCategory,
    Dependency,
    PhysicalCondition,
    ServiceType,
)
from app.graph.twin_graph import Direction
from app.schemas.infrastructure import (
    AssetDetail,
    AssetRef,
    AssetSummary,
    CategoryHealth,
    DependencyEdge,
    DependentLink,
    GraphNode,
    GraphResult,
    InfrastructureHealth,
    Page,
    RequirementGroup,
    TraversalItem,
    TraversalResult,
)
from app.services.twin_store import LoadedTwin


@dataclass(frozen=True, slots=True)
class AssetFilter:
    categories: frozenset[AssetCategory] = frozenset()
    conditions: frozenset[PhysicalCondition] = frozenset()
    min_criticality: int | None = None
    q: str | None = None
    bbox: tuple[float, float, float, float] | None = None

    def matches(self, a: Asset) -> bool:
        if self.categories and a.category not in self.categories:
            return False
        if self.conditions and a.physical_condition not in self.conditions:
            return False
        if self.min_criticality is not None and a.criticality < self.min_criticality:
            return False
        if self.q:
            needle = self.q.casefold()
            if needle not in a.code.casefold() and needle not in a.name.casefold():
                return False
        if self.bbox:
            lon, lat = a.position
            min_lon, min_lat, max_lon, max_lat = self.bbox
            if not (min_lon <= lon <= max_lon and min_lat <= lat <= max_lat):
                return False
        return True


class InfrastructureQueries:
    def __init__(self, twin: LoadedTwin) -> None:
        self.twin = twin
        self.snapshot = twin.snapshot
        self.graph = twin.graph

    # ---------------------------------------------------------------- helpers
    def _asset(self, code: str) -> Asset:
        asset = self.snapshot.assets_by_code.get(code)
        if asset is None:
            raise NotFoundError(f"Asset '{code}' does not exist in the current twin.")
        return asset

    def _ref(self, code: str) -> AssetRef:
        a = self.snapshot.asset(code)
        return AssetRef(code=a.code, name=a.name, category=a.category)

    def _summary_fields(self, a: Asset) -> dict[str, object]:
        return {
            "id": self.twin.ids[a.code],
            "code": a.code,
            "name": a.name,
            "category": a.category,
            "condition": a.physical_condition,
            "criticality": a.criticality,
            "position": a.position,
            "elevation_m": a.elevation_m,
            "capacity": a.capacity,
            "capacity_unit": a.capacity_unit,
            "utilization": a.utilization,
            "population_served": a.population_served,
            "is_source": a.is_source,
            "backup_power_hours": a.backup_power_hours,
        }

    @staticmethod
    def _edge(d: Dependency) -> DependencyEdge:
        return DependencyEdge(
            provider=d.provider,
            dependent=d.dependent,
            service_type=d.service_type,
            mode=d.mode,
            redundancy_group=d.redundancy_group,
            min_required=d.min_required,
            description=d.description,
        )

    # ---------------------------------------------------------------- queries
    def list_assets(
        self, flt: AssetFilter, *, limit: int, cursor: str | None
    ) -> Page[AssetSummary]:
        matching = [a for a in self.snapshot.assets if flt.matches(a)]  # sorted by code
        if cursor is not None:
            matching = [a for a in matching if a.code > cursor]
        page = matching[:limit]
        next_cursor = page[-1].code if len(matching) > limit else None
        return Page[AssetSummary](
            items=[AssetSummary.model_validate(self._summary_fields(a)) for a in page],
            next_cursor=next_cursor,
        )

    def asset_detail(self, code: str) -> AssetDetail:
        a = self._asset(code)
        groups: dict[str, list[Dependency]] = defaultdict(list)
        for d in self.graph.providers_of(code):
            groups[d.redundancy_group].append(d)
        requirements = [
            RequirementGroup(
                group=name,
                service_type=members[0].service_type,
                mode=members[0].mode,
                min_required=members[0].min_required,
                providers=[self._ref(m.provider) for m in members],
                spare_providers=len(members) - members[0].min_required,
                description=members[0].description,
            )
            for name, members in sorted(groups.items())
        ]
        dependents = [
            DependentLink(
                asset=self._ref(d.dependent),
                service_type=d.service_type,
                mode=d.mode,
                redundancy_group=d.redundancy_group,
                min_required=d.min_required,
                description=d.description,
            )
            for d in self.graph.dependents_of(code)
        ]
        return AssetDetail.model_validate(
            {
                **self._summary_fields(a),
                "geometry": a.geometry.model_dump(mode="json"),
                "recovery_profile": a.recovery_profile,
                "metadata": a.metadata,
                "requirements": requirements,
                "dependents": dependents,
                "upstream_count": len(self.graph.upstream(code)),
                "downstream_count": len(self.graph.downstream(code)),
                "component_size": len(self.graph.component_of(code)),
            }
        )

    def traverse(
        self,
        code: str,
        direction: Direction,
        *,
        max_depth: int | None,
        service_types: frozenset[ServiceType] | None,
        include_access: bool,
    ) -> TraversalResult:
        self._asset(code)
        hits = self.graph.traverse(
            code,
            direction,
            max_depth=max_depth,
            service_types=service_types,
            include_access=include_access,
        )
        return TraversalResult(
            focus=self._ref(code),
            direction=direction,
            max_depth=max_depth,
            include_access=include_access,
            items=[
                TraversalItem(
                    asset=self._ref(h.code), depth=h.depth, path=list(h.path), via=self._edge(h.via)
                )
                for h in hits
            ],
        )

    def graph_view(self) -> GraphResult:
        component_index = {
            code: i for i, comp in enumerate(self.graph.components()) for code in comp
        }
        return GraphResult(
            dataset_version=self.snapshot.dataset_version,
            content_hash=self.snapshot.content_hash,
            nodes=[
                GraphNode(
                    code=a.code,
                    name=a.name,
                    category=a.category,
                    condition=a.physical_condition,
                    criticality=a.criticality,
                    position=a.position,
                    component=component_index[a.code],
                )
                for a in self.snapshot.assets
            ],
            edges=[self._edge(d) for d in self.snapshot.dependencies],
        )

    def health(self) -> InfrastructureHealth:
        assets = self.snapshot.assets
        zones = [a for a in assets if a.category is AssetCategory.DEMAND_ZONE]
        by_category: dict[AssetCategory, Counter[PhysicalCondition]] = defaultdict(Counter)
        for a in assets:
            by_category[a.category][a.physical_condition] += 1
        return InfrastructureHealth(
            picture="baseline",
            dataset_version=self.snapshot.dataset_version,
            content_hash=self.snapshot.content_hash,
            asset_count=len(assets),
            infrastructure_asset_count=len(assets) - len(zones),
            demand_zone_count=len(zones),
            dependency_count=len(self.snapshot.dependencies),
            population_total=sum(z.population_served or 0 for z in zones),
            by_condition=dict(Counter(a.physical_condition for a in assets)),
            by_category={
                cat: CategoryHealth(total=sum(c.values()), by_condition=dict(c))
                for cat, c in sorted(by_category.items())
            },
            component_count=len(self.graph.components()),
        )
