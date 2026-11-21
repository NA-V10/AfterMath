# ADR-0013: LangGraph checkpointer on asyncpg

- **Status:** Accepted (Phase 3)
- **Date:** 2026-11-21

## Context
ADR-0006 planned `langgraph-checkpoint-postgres`, which requires psycopg 3. On the development host, Windows Application Control blocks psycopg-binary's bundled libpq. The application already uses SQLAlchemy with asyncpg.

## Decision
Implement `AsyncpgCheckpointSaver` (`app/database/checkpointer.py`, about 200 lines). It follows the storage design of LangGraph's reference `InMemorySaver`: checkpoints, per-channel versioned blobs, and pending writes with LangGraph's special-channel overwrite rules. It runs on the existing SQLAlchemy async engine. Tables are owned by Alembic (migration 0003). Only the async API is implemented.

## Consequences
- (+) No new driver or infrastructure; works natively on the dev host and in containers.
- (+) Tested through a real interrupt/resume across a fresh saver instance (simulated restart).
- (-) We maintain it against LangGraph's `BaseCheckpointSaver` contract; a LangGraph upgrade must re-run `tests/integration/test_checkpointer.py`. The beta delta-channel history uses the base-class default implementation.
- (-) No pruning yet; checkpoint tables grow with workflow count (small at this scale).

## Alternatives considered
Running the backend in Docker during development (heavier on an 11.7 GB host); installing a signed PostgreSQL client for psycopg's pure-Python mode (extra host dependency); the in-memory saver (loses interrupted workflows on restart).
