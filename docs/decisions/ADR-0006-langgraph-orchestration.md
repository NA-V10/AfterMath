# ADR-0006: LangGraph orchestration, in-process, Postgres checkpointer, no Redis

- **Status:** Proposed (Phase 0, pending owner review)
- **Date:** 2026-11-15

## Context
The workflow is sequential with conditional branches, two human interrupts (clarification, approval), retries and long waits.

## Decision
Use LangGraph StateGraph with typed Pydantic state, node RetryPolicy, `interrupt()` for human steps and `AsyncPostgresSaver` for checkpoints. Runs execute as asyncio tasks inside the API process; on startup, RUNNING workflow_runs resume from their checkpoints. No Redis or Celery.

## Consequences
- (+) HITL and durability without extra infrastructure; reuses Postgres.
- (-) A single process limits concurrent workflows. Fine for a decision-support tool; revisit (arq + Redis) only if multiple workers are needed, with owner approval.

## Alternatives considered
Hand-rolled state machine (re-implements checkpoints and interrupts); Celery + Redis (operational weight); Temporal (overkill).
