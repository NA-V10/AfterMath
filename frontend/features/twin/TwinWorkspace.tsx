"use client";

import type { FeatureCollection } from "geojson";
import dynamic from "next/dynamic";
import { useCallback, useMemo, useState } from "react";

import { ErrorState, Loading, PageHeader, Panel, Segmented, cn } from "@/components/ui/primitives";
import { DOMAIN_COLOR, DOMAIN_LABEL, type Domain } from "@/lib/domain";
import {
  type AssetCategory,
  type AssetFilters,
  EMPTY_FILTERS,
  useAssets,
  useBasemap,
  useGraph,
  usePicture,
  useTraversal,
} from "@/lib/queries";

import { AssetInspector } from "./AssetInspector";
import { ClearSelectionButton, FilterPanel } from "./FilterPanel";
import type { Highlight } from "./highlight";
import { DOWNSTREAM_COLOR, UPSTREAM_COLOR } from "./mapData";

// WebGL map and graph layout are browser-only.
const TwinMap = dynamic(() => import("./TwinMap"), { ssr: false, loading: () => <Loading label="Loading map" /> });
const DependencyGraph = dynamic(() => import("./DependencyGraph"), {
  ssr: false,
  loading: () => <Loading label="Laying out graph" />,
});

type View = "split" | "map" | "graph";
const EMPTY = new Set<string>();

function Legend() {
  const domains: Domain[] = ["power", "telecom", "water", "health", "emergency", "data", "fuel", "transport"];
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[13px] text-muted">
      {domains.map((d) => (
        <span key={d} className="flex items-center gap-1">
          <span className="size-2 rounded-full" style={{ background: DOMAIN_COLOR[d] }} />
          {DOMAIN_LABEL[d]}
        </span>
      ))}
      <span className="flex items-center gap-1">
        <span className="h-0.5 w-3" style={{ background: UPSTREAM_COLOR }} /> depends on
      </span>
      <span className="flex items-center gap-1">
        <span className="h-0.5 w-3" style={{ background: DOWNSTREAM_COLOR }} /> depended on by
      </span>
      <span className="flex items-center gap-1">
        <span className="w-3 border-t border-dashed border-muted" /> supporting (soft)
      </span>
    </div>
  );
}

export function TwinWorkspace() {
  const [selected, setSelected] = useState<string | null>(null);
  const [filters, setFilters] = useState<AssetFilters>(EMPTY_FILTERS);
  const [view, setView] = useState<View>("split");
  const [showAccess, setShowAccess] = useState(false);
  const [overlay, setOverlay] = useState(true);
  const picture = usePicture();

  const graph = useGraph();
  const basemap = useBasemap();
  const assets = useAssets(filters);
  const upstream = useTraversal(selected, "upstream");
  const downstream = useTraversal(selected, "downstream");

  const filtersActive =
    filters.categories.length > 0 || filters.minCriticality > 0 || filters.q.trim() !== "";

  const highlight: Highlight = useMemo(
    () => ({
      selected,
      upstream: upstream.data ? new Set(upstream.data.items.map((i) => i.asset.code)) : EMPTY,
      downstream: downstream.data ? new Set(downstream.data.items.map((i) => i.asset.code)) : EMPTY,
      visible: filtersActive && assets.data ? new Set(assets.data.items.map((a) => a.code)) : null,
    }),
    [selected, upstream.data, downstream.data, filtersActive, assets.data],
  );

  const categoryCounts = useMemo(() => {
    const counts = new Map<AssetCategory, number>();
    for (const n of graph.data?.nodes ?? []) counts.set(n.category, (counts.get(n.category) ?? 0) + 1);
    return counts;
  }, [graph.data]);

  // Map bounds come from the synthetic district boundary in the basemap.
  const bounds = useMemo(() => {
    const boundary = (basemap.data as FeatureCollection | undefined)?.features.find(
      (f) => f.properties?.layer === "boundary",
    );
    if (!boundary || boundary.geometry.type !== "Polygon") return null;
    const ring = boundary.geometry.coordinates[0];
    const lons = ring.map((p) => p[0]);
    const lats = ring.map((p) => p[1]);
    return [Math.min(...lons), Math.min(...lats), Math.max(...lons), Math.max(...lats)] as [
      number, number, number, number,
    ];
  }, [basemap.data]);

  const select = useCallback((code: string | null) => setSelected(code), []);

  // Overlay the operational picture only when it differs from the baseline.
  const pictureStatuses = useMemo(
    () =>
      overlay && picture.data?.source === "simulation"
        ? new Map(picture.data.states.map((s) => [s.code, s.status]))
        : null,
    [overlay, picture.data],
  );

  const loading = graph.isPending || basemap.isPending;
  const error = graph.error ?? basemap.error;

  const mapPanel = (
    <Panel
      title="District map"
      className={cn("min-h-[320px]", view === "graph" && "hidden")}
      actions={<span className="text-[13px] text-dim">fictional · synthetic coordinates</span>}
    >
      {loading ? (
        <Loading label="Loading twin" />
      ) : error ? (
        <ErrorState error={error} onRetry={() => { graph.refetch(); basemap.refetch(); }} />
      ) : bounds ? (
        <TwinMap
          graph={graph.data!}
          basemap={basemap.data as unknown as FeatureCollection}
          bounds={bounds}
          highlight={highlight}
          showAccess={showAccess}
          onSelect={select}
          statuses={pictureStatuses}
        />
      ) : (
        <ErrorState error={new Error("The basemap has no district boundary.")} />
      )}
    </Panel>
  );

  const graphPanel = (
    <Panel
      title="Dependency graph"
      className={cn("min-h-[320px]", view === "map" && "hidden")}
      actions={
        <span className="text-[13px] text-dim">
          {graph.data ? `${graph.data.nodes.length} nodes · providers → dependents` : ""}
        </span>
      }
    >
      {loading ? (
        <Loading label="Loading graph" />
      ) : error ? (
        <ErrorState error={error} onRetry={() => graph.refetch()} />
      ) : (
        <DependencyGraph
          graph={graph.data!}
          highlight={highlight}
          showAccess={showAccess}
          onSelect={select}
          statuses={pictureStatuses}
        />
      )}
    </Panel>
  );

  return (
    <div className="flex h-full min-h-0 flex-col">
      <PageHeader
        title="Infrastructure Twin"
        hint="50 synthetic assets and the dependencies between them, on a fictional district."
      >
        {picture.data?.source === "simulation" && (
          <label
            className="flex cursor-pointer items-center gap-2 text-[13px] text-muted"
            data-testid="picture-overlay-toggle"
          >
            <input
              type="checkbox"
              checked={overlay}
              onChange={(e) => setOverlay(e.target.checked)}
              className="accent-[#5ab9fc]"
            />
            Overlay operational picture
            <span className="max-w-56 truncate">({picture.data.label ?? "simulation"})</span>
          </label>
        )}
        <Segmented<View>
          label="Layout"
          value={view}
          onChange={setView}
          options={[
            { value: "split", label: "Split" },
            { value: "map", label: "Map" },
            { value: "graph", label: "Graph" },
          ]}
        />
      </PageHeader>
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-b border-line px-5 py-2">
        <Legend />
      </div>
      <div className="grid min-h-0 flex-1 grid-cols-1 gap-px bg-line lg:grid-cols-[240px_minmax(0,1fr)_360px]">
        <Panel className="max-h-[40dvh] border-0 lg:max-h-none" title="Filter & find">
          <FilterPanel
            filters={filters}
            onChange={setFilters}
            matches={assets.data?.items}
            isFetching={assets.isFetching}
            selected={selected}
            onSelect={select}
            showAccess={showAccess}
            onShowAccess={setShowAccess}
            categoryCounts={categoryCounts}
          />
        </Panel>
        <div
          className={cn(
            "grid min-h-0 gap-px bg-line",
            view === "split" ? "grid-rows-[minmax(320px,1fr)_minmax(320px,1fr)]" : "grid-rows-1",
          )}
        >
          {mapPanel}
          {graphPanel}
        </div>
        <Panel className="min-h-[240px] border-0" title={selected ? "Asset inspector" : "Inspector"}>
          {selected ? (
            <AssetInspector
              code={selected}
              onSelect={select}
              headerActions={<ClearSelectionButton onClear={() => select(null)} />}
            />
          ) : (
            <div className="p-4 text-muted">
              Select an asset on the map, in the graph or from the list to inspect its
              requirements, redundancy and dependency reach.
            </div>
          )}
        </Panel>
      </div>
    </div>
  );
}
