# Phase 2 Report — Deterministic Simulation Engine

**Date:** 2026-11-21 · **Status:** complete. The district topology was treated as accepted; owner review is still open.

## Delivered

| Area | What exists |
|---|---|
| Engine (`app.simulation`, pure) | Greatest-fixed-point supply evaluation over k-of-n groups; derived status (SOFT losses never cascade); discrete-event time with backup-power exhaustion; flood resolution (Shapely); cascade waves; cause attribution; isolation detection; impact score and service availability; canonical SHA-256 result hash; restoration runs from an initial picture |
| Criticality | Exact N-1 analysis of all 43 infrastructure assets, flagging single points of failure (14 found) |
| Persistence | Migration `0002`: scenarios, incidents, evidence, simulation runs and events, operational-picture history. Runs, events and picture changes are immutable (DB triggers). |
| API | `/scenarios`, `/simulations` (create, list, detail, events, compare, replay), `/operational-picture` (get, apply, reset), `/incidents` (structured + free text), `/infrastructure/criticality` |
| Frontend | **Simulation Lab** has: <br>• scenario or custom failures, horizon, label, apply-to-picture <br>• run history and side-by-side comparison <br>• wave-by-wave playback over map or graph, plus a per-asset "why" from engine causes <br>• impact-over-time chart and event timeline <br>• critical-services bars and a replay-and-verify button <br>**Command Center** shows the operational picture with reset. **Twin** has a picture overlay and structural criticality in the inspector. |

## Tests (actual results, final run)

| Suite | Result |
|---|---|
| Backend pytest (unit, golden, Hypothesis properties, integration on PostgreSQL) | **98 passed** |
| ruff, ruff format, mypy (strict on `app.graph`, `app.core`, `app.simulation`), import-linter (2 contracts) | clean |
| Frontend Vitest | **14 passed** |
| tsc, ESLint, `next build` | clean / success |
| Playwright E2E (Edge) | **9 passed** (5 from Phase 1 + 4 new) |

The **golden tests** were derived by hand from the dependency table before the engine existed. They cover:
- the Riverside substation failure: statuses at t=0, backup exhaustion at 120 and 240 min, cascade waves, untouched assets, and HOS-02 isolated;
- the flood: exactly 6 inundated assets;
- the combined scenario: EOC fails at t+30, Meridian General keeps power through its N-1 feed, and SCADA loss does not brown out the grid.

**Properties P1–P8** (200 random twins each):
- P1 identical outputs;
- P2 input-order independence;
- P3 the result is a fixed point;
- P4 monotonicity;
- P5 unrelated components are unaffected;
- P6 k-of-n tolerates exactly n−k losses;
- P7 backup exhaustion is exactly on schedule;
- P8 operational assets satisfy their HARD requirements.

Result hashes are additionally checked to be identical across processes with different `PYTHONHASHSEED` values.

## Defects found and fixed during the phase

- Status-only changes took their wave from the *latest* cause instead of the earliest.
- Restored assets were reported one wave late.
- Stale backup timers produced empty timeline points.
- My first version of property P6 was a tautology; it was replaced with a real k-of-n test.
- An E2E race: a test compared runs before the second run had finished.
- **UX:** selecting an asset in the Lab dimmed the very cascade being studied.
- **UX:** a red "0 failed" read as an alarm.

## Open items / known gaps

- **Authentication:** state-changing endpoints (run, apply, reset, create incident) are unauthenticated until Phase 5. They are attributed to `local:operator` and refused in production mode.
- **Free-text incidents** are stored but can't be simulated until SENTINEL (Phase 3).
- **Impact chart scale:** on a 72 h axis, the early cascade (0–4 h) is compressed. The tooltip and the playback cover it, but a zoomable or log time axis would help.
- **Environment:** Application Control now blocks uv's venv launcher and the alembic shim. See ENVIRONMENT.md for the workaround.
- **Phase 3 decision still pending:** the LangGraph Postgres checkpointer needs psycopg, which is blocked on this host.
