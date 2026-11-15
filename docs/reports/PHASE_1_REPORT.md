# Phase 1 Report — Infrastructure Digital Twin

**Date:** 2026-11-15 · **Status:** complete, pending owner review of the district topology.

## Delivered

| Area | What exists |
|---|---|
| Synthetic district | `data/synthetic/meridian-valley` v1.1.0. 43 infrastructure assets in 16 categories, plus 7 demand zones (180,000 synthetic residents). 131 dependency edges, each with a written rationale. A synthetic basemap (river, 4 m floodplain, terrain, streets, labels). Coordinates are placed near 0°N 0°E on purpose. |
| Scenarios | `data/scenarios/`: `substation-riverside`, `river-flood`, `power-telecom-combined` (inputs only; the engine comes in Phase 2) |
| Domain core (`app.graph`, pure) | Immutable canonical `TwinSnapshot` with a SHA-256 content hash; GeoJSON geometry models; k-of-n dependency model; deterministic BFS traversal; weakly connected components; dataset validator with 15 stable rule codes |
| Persistence | Alembic revision `0001`: `dataset_release`, `infrastructure_asset`, `infrastructure_dependency`, `audit_log`. CHECK constraints (including `is_synthetic`). A trigger makes the audit log append-only. |
| Services | Idempotent seeding: validate → upsert → audit, all in one transaction. The audit trail is hash-chained, with a verifier. The twin cache refuses to serve rows that no longer match the seeded hash. |
| API (`/api/v1`) | `health`, `health/ready`, `system/status`, `infrastructure/{assets, assets/{code}, assets/{code}/dependencies, graph, health, basemap}`, `audit`, `audit/{id}`. Errors are RFC 9457 problem+json. Every response carries a request ID and `X-Aftermath-Environment: SIMULATION`. |
| CLI | `python -m app.cli validate-dataset | seed | export-schemas | export-openapi | verify-audit` |
| Frontend | App shell with a persistent simulation banner and six-screen navigation. The **Infrastructure Twin** has a MapLibre map, a React Flow/ELK dependency graph and an asset inspector, all sharing one selection. It also has filters, an accessible asset list and redundancy display. **Command Center** shows the real baseline; **Audit** shows the real trail. Lab, Recovery and Agents show phase notices with no fake data. Types are generated from OpenAPI. |

## Tests (actual results, final run)

| Suite | Result |
|---|---|
| Backend pytest (unit, Hypothesis property, integration on PostgreSQL 16) | **56 passed** |
| Backend static checks: ruff, ruff format, mypy (strict on `app.graph`/`app.core`), import-linter (2 contracts) | clean |
| Frontend Vitest | **9 passed** |
| Frontend tsc, ESLint, `next build` | clean / success |
| Playwright E2E (Microsoft Edge) | **5 passed** |

Property tests (Hypothesis, 200 examples each) cover:
- traversal is independent of input order (equal content hash and equal results);
- upstream and downstream are duals of each other;
- reported depths are shortest paths and every path follows real edges;
- disconnected components never reach each other;
- the depth limit is respected.

## Changes from the Phase 0 design (all documented)

1. **asyncpg instead of psycopg 3.** Windows Application Control blocks psycopg-binary's libpq DLL. The LangGraph checkpointer question moves to Phase 3 (see ENVIRONMENT.md).
2. **New `dataset_release` table** for idempotent, hash-verified seeding.
3. **`HEALTHCARE` service type and `POWER_GENERATION` category** were added to model demand zones and the islanded hillside microgrid.
4. **Graph nodes carry geometry,** so one endpoint drives both the map and the graph and they cannot disagree.
5. **Supply vs. displayed status** was added to SIMULATION_ENGINE.md §2.1. SOFT losses must not cascade as brownouts. This was found while authoring the dataset.
6. **Selection precedence:** a selected asset's dependency chain stays visible even when filters would hide it. This was found in E2E.
7. The **seeding gap was closed:** reusing a version with a different basemap is now rejected.

## Bugs found and fixed through tests

- A test-data generator used invalid asset codes. This was a test bug; the model correctly rejected them.
- An active search filter hid the selected asset's own dependency chain (UX bug; E2E).
- A refused DB connection returned 500 instead of 503, because asyncpg's raw `ConnectionRefusedError` isn't wrapped by SQLAlchemy (integration test).

## Open items

- **Owner review of the district topology**, especially the redundancy choices (HOS-01 has N-1 power; SUB-02 is the deliberate single point of failure for the east bank and the main water works).
- Pre-commit hooks and CI are not set up yet (planned for Phase 7). The checks run through the commands in the README.
- Structural criticality (N-1) and functional status overlays need the Phase 2 engine. The UI states this rather than approximating it.
- The full-stack `docker compose --profile full` containers come in Phase 7. Only `db` is containerised now.
