# ADR-0012: Hybrid local development topology

- **Status:** Proposed (Phase 0, pending owner review)
- **Date:** 2026-11-15

## Context
The host has 11.7 GB RAM (~2.5 GB free observed) and a 4-thread CPU. Running Docker Desktop + three containers + `next dev` + an IDE risks constant swapping.

## Decision
Run only PostgreSQL in Docker during development (memory-capped). Run uvicorn and `next dev` natively (uv/pnpm). The full compose stack (db, backend, frontend) is used for E2E, demos and CI. Python is pinned to 3.13 through uv; the host's 3.14 is not used for the project venv. See [ENVIRONMENT.md](../ENVIRONMENT.md).

## Consequences
- (+) Lower memory, faster reloads.
- (-) Two run modes to document and keep working. Both are covered in the README and the Phase 7 checks.

## Alternatives considered
Everything in containers with bind mounts (slow file watching on Windows, high RAM); no Docker at all (needs a local Postgres install).
