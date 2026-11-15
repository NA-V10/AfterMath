"use client";

import "maplibre-gl/dist/maplibre-gl.css";

import type { FeatureCollection, Point } from "geojson";
import maplibregl, { type GeoJSONSource, type LngLatBoundsLike } from "maplibre-gl";
import { useEffect, useRef } from "react";

import type { Schemas } from "@/lib/api";

import type { Highlight } from "./highlight";
import {
  INTERACTIVE_LAYERS,
  assetFeatures,
  buildStyle,
  featureStates,
  selectionLinks,
} from "./mapData";

interface Props {
  graph: Schemas["GraphResult"];
  basemap: FeatureCollection;
  bounds: [number, number, number, number];
  highlight: Highlight;
  showAccess: boolean;
  onSelect: (code: string | null) => void;
}

function escapeHtml(text: string): string {
  return text.replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
}

export default function TwinMap({ graph, basemap, bounds, highlight, showAccess, onSelect }: Props) {
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const loaded = useRef(false);
  const onSelectRef = useRef(onSelect);
  useEffect(() => {
    onSelectRef.current = onSelect;
  }, [onSelect]);

  // ---- create the map once
  useEffect(() => {
    if (!container.current) return;
    const [minLon, minLat, maxLon, maxLat] = bounds;
    const fit: LngLatBoundsLike = [[minLon, minLat], [maxLon, maxLat]];
    const map = new maplibregl.Map({
      container: container.current,
      style: buildStyle(basemap),
      bounds: fit,
      fitBoundsOptions: { padding: 24 },
      maxBounds: [[minLon - 0.08, minLat - 0.06], [maxLon + 0.08, maxLat + 0.06]],
      attributionControl: false,
      dragRotate: false,
      pitchWithRotate: false,
    });
    map.touchZoomRotate.disableRotation();
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-right");
    mapRef.current = map;

    // Area labels as DOM markers (no glyph server required).
    const labels = basemap.features
      .filter((f) => f.properties?.layer === "label" && f.geometry.type === "Point")
      .map((f) => {
        const el = document.createElement("div");
        el.className =
          "pointer-events-none select-none text-[10px] font-semibold tracking-[0.2em] text-[#5d6876]";
        el.textContent = String(f.properties?.name ?? "");
        return new maplibregl.Marker({ element: el })
          .setLngLat((f.geometry as Point).coordinates as [number, number])
          .addTo(map);
      });

    const popup = new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 10 });
    map.on("mousemove", (e) => {
      const feature = map.queryRenderedFeatures(e.point, { layers: INTERACTIVE_LAYERS })[0];
      map.getCanvas().style.cursor = feature ? "pointer" : "";
      if (!feature) {
        popup.remove();
        return;
      }
      const p = feature.properties as Record<string, string>;
      popup
        .setLngLat(e.lngLat)
        .setHTML(
          `<div style="font-family:var(--font-mono);font-weight:600">${escapeHtml(p.code)}</div>` +
            `<div>${escapeHtml(p.name)}</div>` +
            `<div style="color:#8b97a6">${escapeHtml(p.categoryLabel)} · ${escapeHtml(p.conditionLabel)}</div>`,
        )
        .addTo(map);
    });
    map.on("mouseout", () => popup.remove());
    map.on("click", (e) => {
      const feature = map.queryRenderedFeatures(e.point, { layers: INTERACTIVE_LAYERS })[0];
      onSelectRef.current(feature ? String(feature.properties?.code) : null);
    });
    map.on("load", () => {
      loaded.current = true;
      map.fire("aftermath:ready");
    });

    return () => {
      labels.forEach((m) => m.remove());
      popup.remove();
      map.remove();
      mapRef.current = null;
      loaded.current = false;
    };
    // The map is created once per basemap/bounds; data and highlight update incrementally.
  }, [basemap, bounds]);

  // ---- asset data + highlight + links (incremental updates)
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const apply = () => {
      (map.getSource("assets") as GeoJSONSource | undefined)?.setData(assetFeatures(graph.nodes));
      (map.getSource("links") as GeoJSONSource | undefined)?.setData(
        selectionLinks(graph.nodes, graph.edges, highlight.selected, showAccess),
      );
      for (const [code, state] of featureStates(graph.nodes, highlight)) {
        map.setFeatureState({ source: "assets", id: code }, state);
      }
    };
    if (loaded.current) apply();
    else map.once("aftermath:ready", apply);
  }, [graph, highlight, showAccess]);

  // ---- bring the selection into view when it is outside the viewport
  useEffect(() => {
    const map = mapRef.current;
    const node = graph.nodes.find((n) => n.code === highlight.selected);
    if (!map || !node) return;
    const [lon, lat] = node.position;
    if (!map.getBounds().contains([lon, lat])) map.easeTo({ center: [lon, lat], duration: 400 });
  }, [graph.nodes, highlight.selected]);

  return (
    <div
      ref={container}
      className="h-full w-full"
      role="application"
      aria-label="Infrastructure map of the synthetic district. Use the asset list or graph for keyboard selection."
      data-testid="twin-map"
    />
  );
}
