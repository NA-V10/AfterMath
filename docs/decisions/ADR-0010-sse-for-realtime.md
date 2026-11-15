# ADR-0010: Server-Sent Events for progress streams

- **Status:** Proposed (Phase 0, pending owner review)
- **Date:** 2026-11-15

## Context
The UI needs live workflow, simulation playback and execution progress. Communication is one-way, server to client.

## Decision
Use SSE endpoints backed by an in-process async pub/sub. Clients fall back to polling through TanStack Query.

## Consequences
- (+) Plain HTTP, works through proxies, trivial in FastAPI.
- (-) Single-process fan-out only (consistent with ADR-0006).

## Alternatives considered
WebSockets (bidirectional not needed); Redis pub/sub (no multi-process need).
