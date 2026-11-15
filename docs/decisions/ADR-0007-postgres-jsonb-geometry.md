# ADR-0007: PostgreSQL with GeoJSON in JSONB; no PostGIS

- **Status:** Proposed (Phase 0, pending owner review)
- **Date:** 2026-11-15

## Context
We need to store points, lines and polygons and do flood-polygon intersections on ~50 features.

## Decision
Store GeoJSON in `jsonb`, validated on write. Spatial operations run in Python with Shapely inside the pure domain core.

## Consequences
- (+) Stock Postgres image; spatial logic is unit-testable without a DB.
- (-) No spatial indexes or SQL spatial queries. Migrate to PostGIS if datasets grow beyond ~10k features.

## Alternatives considered
PostGIS now (heavier image, extensions, no current need).
