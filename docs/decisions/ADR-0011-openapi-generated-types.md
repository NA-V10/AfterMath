# ADR-0011: OpenAPI as the single API contract; generated TypeScript types

- **Status:** Proposed (Phase 0, pending owner review)
- **Date:** 2026-11-15

## Context
Hand-maintained frontend DTOs drift from backend schemas.

## Decision
FastAPI's OpenAPI is the source of truth. `scripts/gen_api_types.py` runs `openapi-typescript` into `frontend/types/api.d.ts`. A CI check fails on drift. A small typed fetch wrapper (`openapi-fetch`) is used with TanStack Query.

## Consequences
- (+) Compile-time contract safety.
- (-) Generation step in the workflow.

## Alternatives considered
Handwritten types; tRPC/GraphQL (wrong fit for a Python backend).
