# ADR-0009: Fictional district on a synthetic basemap

- **Status:** Proposed (Phase 0, pending owner review)
- **Date:** 2026-11-15

## Context
Plotting synthetic infrastructure over real-world map tiles could be mistaken for real infrastructure, and third-party tiles add an external dependency, API keys or terms of use.

## Decision
Create the fictional 'Meridian Valley' with coordinates in an arbitrary bounding box. Render it on a self-generated GeoJSON basemap (boundary, river, roads, zones, labels) with a custom dark MapLibre style and bundled glyphs. No external tiles by default.

## Consequences
- (+) Works offline, no keys, no misattribution risk; full control of the EOC aesthetic.
- (-) Less 'realistic' visual context. An optional real basemap could be added later with owner approval.

## Alternatives considered
OpenFreeMap/MapTiler tiles over a real city (realism, but safety and dependency concerns).
