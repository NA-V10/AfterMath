/**
 * Converts API payloads into MapLibre style + GeoJSON. Pure functions (unit-tested).
 * No external tiles or glyphs are used: the basemap is synthetic GeoJSON from the backend.
 */
import type { FeatureCollection, Geometry, LineString } from "geojson";
import type { ExpressionSpecification, StyleSpecification } from "maplibre-gl";

import type { Schemas } from "@/lib/api";
import { CATEGORY, CONDITION, STATUS, categoryColor } from "@/lib/domain";
import type { FunctionalStatus } from "@/lib/queries";

import { type Highlight, isAccessEdge, roleOf } from "./highlight";

type GraphNode = Schemas["GraphNode"];
type Edge = Schemas["DependencyEdge"];

export const UPSTREAM_COLOR = "#5ab9fc";
export const DOWNSTREAM_COLOR = "#e7a65a";
export const SELECTED_COLOR = "#ffffff";

export function assetFeatures(nodes: GraphNode[]): FeatureCollection {
  return {
    type: "FeatureCollection",
    features: nodes.map((n) => ({
      type: "Feature",
      id: n.code,
      geometry: n.geometry as unknown as Geometry,
      properties: {
        code: n.code,
        name: n.name,
        category: n.category,
        categoryLabel: CATEGORY[n.category].label,
        criticality: n.criticality,
        color: categoryColor(n.category),
        conditionColor: CONDITION[n.condition].color,
        conditionLabel: CONDITION[n.condition].label,
      },
    })),
  };
}

/** Straight links from the selected asset to its direct providers and dependents. */
export function selectionLinks(
  nodes: GraphNode[],
  edges: Edge[],
  selected: string | null,
  showAccess: boolean,
): FeatureCollection<LineString> {
  if (!selected) return { type: "FeatureCollection", features: [] };
  const pos = new Map(nodes.map((n) => [n.code, n.position]));
  const features = edges
    .filter((e) => (e.provider === selected || e.dependent === selected) && (showAccess || !isAccessEdge(e)))
    .map((e) => ({
      type: "Feature" as const,
      geometry: {
        type: "LineString" as const,
        coordinates: [pos.get(e.provider)!, pos.get(e.dependent)!] as [number, number][],
      },
      properties: { kind: e.dependent === selected ? "up" : "down", mode: e.mode },
    }));
  return { type: "FeatureCollection", features };
}

/** Feature-state for each asset, derived from the shared highlight and optional status overlay. */
export function featureStates(
  nodes: GraphNode[],
  h: Highlight,
  statuses: ReadonlyMap<string, FunctionalStatus> | null = null,
): Map<string, Record<string, boolean | string>> {
  const states = new Map<string, Record<string, boolean | string>>();
  for (const n of nodes) {
    const role = roleOf(n.code, h);
    states.set(n.code, {
      status: statuses?.get(n.code) ?? "NONE",
      sel: role === "selected",
      up: role === "upstream",
      down: role === "downstream",
      hidden: role === "hidden",
      dim: role === "dimmed",
    });
  }
  return states;
}

const fs = (key: string): ExpressionSpecification => ["boolean", ["feature-state", key], false];

const opacity = (base: number): ExpressionSpecification => [
  "case", fs("hidden"), base * 0.08, fs("dim"), base * 0.25, base,
];

const strokeColor: ExpressionSpecification = [
  "case",
  fs("sel"), SELECTED_COLOR,
  fs("up"), UPSTREAM_COLOR,
  fs("down"), DOWNSTREAM_COLOR,
  ["get", "conditionColor"],
];

const geom = (type: string): ExpressionSpecification => ["==", ["geometry-type"], type];

/** Functional-status colour when an overlay is active, otherwise `fallback`. */
const byStatus = (fallback: ExpressionSpecification | string): ExpressionSpecification => [
  "match",
  ["to-string", ["coalesce", ["feature-state", "status"], "NONE"]],
  "FAILED", STATUS.FAILED.color,
  "ON_BACKUP", STATUS.ON_BACKUP.color,
  "DEGRADED", STATUS.DEGRADED.color,
  fallback,
];

export function buildStyle(basemap: FeatureCollection): StyleSpecification {
  const empty: FeatureCollection = { type: "FeatureCollection", features: [] };
  const layer = (name: string): ExpressionSpecification => ["==", ["get", "layer"], name];
  return {
    version: 8,
    sources: {
      basemap: { type: "geojson", data: basemap },
      assets: { type: "geojson", data: empty, promoteId: "code" },
      links: { type: "geojson", data: empty },
    },
    layers: [
      { id: "background", type: "background", paint: { "background-color": "#0a0d14" } },
      { id: "boundary-fill", type: "fill", source: "basemap", filter: layer("boundary"),
        paint: { "fill-color": "#0f1420" } },
      { id: "terrain", type: "fill", source: "basemap", filter: layer("terrain"),
        paint: { "fill-color": "#141a27" } },
      { id: "floodplain", type: "fill", source: "basemap", filter: layer("floodplain"),
        paint: { "fill-color": "#4493f8", "fill-opacity": 0.06 } },
      { id: "floodplain-edge", type: "line", source: "basemap", filter: layer("floodplain"),
        paint: { "line-color": "#4493f8", "line-opacity": 0.35, "line-width": 1, "line-dasharray": [3, 3] } },
      { id: "water", type: "fill", source: "basemap", filter: layer("water"),
        paint: { "fill-color": "#123049" } },
      { id: "streets", type: "line", source: "basemap", filter: layer("street"),
        paint: { "line-color": "#202736", "line-width": 1 } },
      { id: "boundary-edge", type: "line", source: "basemap", filter: layer("boundary"),
        paint: { "line-color": "#2f3a47", "line-width": 1, "line-dasharray": [4, 2] } },
      // demand zones
      { id: "asset-zones", type: "fill", source: "assets", filter: geom("Polygon"),
        paint: {
          "fill-color": ["case", fs("sel"), SELECTED_COLOR, fs("up"), UPSTREAM_COLOR, fs("down"), DOWNSTREAM_COLOR, byStatus("#8b949e")],
          "fill-opacity": [
            "case", fs("hidden"), 0, fs("sel"), 0.16, fs("up"), 0.1, fs("down"), 0.1, fs("dim"), 0.02,
            ["match", ["to-string", ["coalesce", ["feature-state", "status"], "NONE"]],
              "FAILED", 0.22, "DEGRADED", 0.12, "ON_BACKUP", 0.12, 0.05],
          ],
        } },
      { id: "asset-zones-edge", type: "line", source: "assets", filter: geom("Polygon"),
        paint: {
          "line-color": ["case", fs("sel"), SELECTED_COLOR, fs("up"), UPSTREAM_COLOR, fs("down"), DOWNSTREAM_COLOR, "#3a4654"],
          "line-opacity": opacity(0.8),
          "line-width": 1,
        } },
      // roads & bridges
      { id: "asset-lines-casing", type: "line", source: "assets", filter: geom("LineString"),
        layout: { "line-cap": "round" },
        paint: { "line-color": "#0a0d14", "line-width": 7, "line-opacity": opacity(1) } },
      { id: "asset-lines", type: "line", source: "assets", filter: geom("LineString"),
        layout: { "line-cap": "round" },
        paint: {
          "line-color": ["case", fs("sel"), SELECTED_COLOR, fs("up"), UPSTREAM_COLOR, fs("down"), DOWNSTREAM_COLOR, byStatus("#6b7684")],
          "line-width": ["case", fs("sel"), 5, 3],
          "line-opacity": opacity(1),
        } },
      // selection links
      { id: "links", type: "line", source: "links",
        paint: {
          "line-color": ["match", ["get", "kind"], "up", UPSTREAM_COLOR, DOWNSTREAM_COLOR],
          "line-width": 1.5,
          "line-opacity": 0.8,
          "line-dasharray": [2, 1.5],
        } },
      // facility markers
      { id: "asset-points", type: "circle", source: "assets", filter: geom("Point"),
        paint: {
          "circle-color": byStatus(["get", "color"]),
          "circle-radius": [
            "case", fs("sel"), 11,
            ["interpolate", ["linear"], ["get", "criticality"], 40, 4.5, 100, 9],
          ],
          "circle-stroke-color": strokeColor,
          "circle-stroke-width": ["case", fs("sel"), 3, fs("up"), 2.5, fs("down"), 2.5, 1.5],
          "circle-opacity": opacity(0.95),
          "circle-stroke-opacity": opacity(1),
        } },
    ],
  };
}

export const INTERACTIVE_LAYERS = ["asset-points", "asset-lines", "asset-zones"];
