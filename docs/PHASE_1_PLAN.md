# Phase 1 — Infrastructure Digital Twin: Implementation Plan

**Objective:** a validated synthetic district persisted in PostgreSQL, loaded into an immutable graph, served through the infrastructure API and explored in the Twin screen (map + dependency graph + inspector), with tests.

## 1. Synthetic district: "Meridian Valley" (fictional)

A river runs north–south and splits a western residential bank from an eastern industrial/low-lying bank, joined by two bridges. Two external grid supply points feed four substations. The design deliberately includes:

- **Redundancy:** Meridian General Hospital has two feeders (k=1 of 2) plus an 8 h generator.
- **Single points of failure:** Riverside substation (SUB-02) solely feeds the east-bank distribution, the main water treatment plant and Riverside Community Hospital (4 h generator).
- **Cycles:** substation SCADA has a SOFT dependency on the telecom hub, which has a HARD dependency on power.
- **Flood exposure:** SUB-02, a pumping station, the low bridge and an east road segment sit below the 4 m flood line.
- **Independent component:** a hillside water intake and pumping system with its own solar-battery supply. It must remain unaffected by grid scenarios (tests P5).

Planned inventory (≈ 46 nodes):

| Category | Count | Codes (planned) |
|---|---|---|
| Grid supply point (source) | 2 | GSP-01, GSP-02 |
| Substation | 4 | SUB-01 Northgate, SUB-02 Riverside, SUB-03 Southfield, SUB-04 Eastridge |
| Power distribution | 7 | PDN-01…07 |
| Hospital / clinic | 3 | HOS-01 Meridian General, HOS-02 Riverside Community, HOS-03 Eastridge Clinic |
| Telecom hub / towers | 1 / 5 | TEL-HUB, TEL-01…05 |
| Data centre | 1 | DC-01 (dispatch & records) |
| Emergency ops / fire stations | 1 / 2 | EOC-01, FIR-01, FIR-02 |
| Water intake / treatment / pumping | 2 / 2 / 3 | WIN-01, WIN-02 (hillside, independent), WTP-01, WTP-02, WPS-01…03 |
| Fuel depot | 2 | FUL-01, FUL-02 |
| Road segments / bridges | 5 / 2 | RD-01…05, BR-01 (low), BR-02 (high) |
| Demand zones (sinks, with population) | 6 | ZN-01…06 (total ≈ 180 000 synthetic residents) |

The exact attributes, dependencies and rationale per edge go in `data/synthetic/meridian-valley/*.json`. **The expected outcomes of the three scenarios are written down as tests before the Phase 2 engine exists.**

Predefined scenarios (`data/scenarios/`):
1. `substation-riverside`: SUB-02 DAMAGED at t=0.
2. `river-flood`: 4.2 m flood polygon along the east bank.
3. `power-telecom-combined`: SUB-01 DAMAGED + TEL-HUB DAMAGED at t=30.

## 2. Tasks (in implementation order)

| # | Task | Output | Cx | Depends |
|---|---|---|---|---|
| 1.1 | Repository bootstrap | `git init`, `.gitignore`, `.editorconfig`, pre-commit (ruff, mypy, detect-secrets, prettier/eslint), `docker-compose.yml` (db only + profiles), `.env.example` | S | — |
| 1.2 | Backend skeleton | `pyproject.toml` (uv, Python 3.13), app factory, pydantic-settings config, structlog JSON logging, request-ID middleware, problem+json handlers, `/health`, `/health/ready` | S | 1.1 |
| 1.3 | Persistence | Async SQLAlchemy session, models `infrastructure_asset`, `infrastructure_dependency`, `audit_log` (+ append-only trigger), Alembic initial migration | M | 1.2 |
| 1.4 | Dataset + schemas | JSON Schemas in `data/schemas/`; assets, dependencies, basemap GeoJSON; scenario files (inputs only) | M | — |
| 1.5 | Graph core (pure) | `TwinSnapshot` (frozen), builder → `MultiDiGraph`, `upstream/downstream` with paths, components, `validate_dataset()` | M | 1.4 |
| 1.6 | Seeding | `scripts/seed.py`: validate → upsert in one transaction → audit `dataset.seeded`; idempotent by `dataset_version` | S | 1.3, 1.5 |
| 1.7 | Infrastructure API | `assets` list/detail, `dependencies`, `graph`, `health` (baseline counts), `basemap`, `system/status`, `audit` (read) | M | 1.6 |
| 1.8 | Frontend skeleton | Next.js + TS + Tailwind + shadcn/ui, design tokens (dark EOC palette), app shell + nav for the 6 screens (unbuilt screens show "Available in Phase N", not fake data), persistent simulation banner, TanStack Query, generated API types | M | 1.7 |
| 1.9 | Twin screen | MapLibre map with synthetic basemap and asset layers (category icon, status colour, criticality size), filter panel, asset inspector, React Flow graph with ELK layout, synced selection, upstream/downstream highlight | L | 1.8 |
| 1.10 | Tests | unit (traversal, validator), property (P2, P5 on traversal), integration (API + DB), Playwright journey 1, Vitest | M | parallel with 1.5–1.9 |
| 1.11 | Docs | README quick-start, update ARCHITECTURE and DATA_MODEL where implementation diverged | S | end |

## 3. Acceptance criteria

Status after implementation (see [reports/PHASE_1_REPORT.md](reports/PHASE_1_REPORT.md)):

- [x] The seed command (`python -m app.cli seed`) loads 50 assets (43 infrastructure + 7 demand zones); validation reports zero errors; seeding twice is a no-op.
- [x] Every dependency has a `description`; the topology is hand-designed. **Owner review of the topology is still pending.**
- [x] `GET /infrastructure/assets` returns all assets; filters work; unknown asset code → 404 problem+json.
- [x] `GET …/dependencies?direction=downstream` for SUB-02 returns the 19-asset hand-derived set.
- [x] Map and graph render the same asset set (both are driven by `/infrastructure/graph`); selection is shared (E2E).
- [x] Simulation banner is visible on every screen (E2E).
- [x] `ruff`, `mypy` (strict on `app.graph` and `app.core`), `import-linter`, `tsc`, `eslint` are clean.
- [x] pytest unit + property + integration pass.
- [x] `/health/ready` returns 200 when ready and 503 when the DB is unreachable; data endpoints return a 503 problem (no stack trace). Both are integration-tested.

## 4. Risks specific to Phase 1

- MapLibre without tiles needs a hand-built style: budget time for a good-looking synthetic basemap (river, roads, zones, labels with a bundled glyph set).
- The ELK layout of a cyclic graph needs edge-direction hints; fall back to dagre if ELK is too heavy.
- Windows path/line-ending issues: `.gitattributes` with `* text=auto eol=lf`.

## 5. Commands to begin Phase 1

Run in PowerShell from `E:\aftermath`:

```powershell
# 0. Start Docker Desktop (the daemon is currently not running), then verify:
docker info --format '{{.ServerVersion}}'

# 1. Install uv and a pinned Python for the project
winget install --id=astral-sh.uv -e
uv python install 3.13

# 2. Initialise the repository
git init -b main
git add docs README.md .gitignore .env.example
git commit -m "docs: Phase 0 architecture foundation"

# 3. Then tell Claude: "Proceed with Phase 1"
#    (Claude will scaffold backend with `uv init`, frontend with
#     `pnpm create next-app@latest frontend --ts --tailwind --eslint --app --use-pnpm`,
#     and start Postgres with `docker compose up -d db`.)
```
