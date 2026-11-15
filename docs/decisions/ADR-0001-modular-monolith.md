# ADR-0001: Modular monolith backend

- **Status:** Proposed (Phase 0, pending owner review)
- **Date:** 2026-11-15

## Context
AFTERMATH has one team, one district and tightly coupled workflows (simulation -> planning -> governance) that need transactional consistency.

## Decision
Build a single FastAPI service with strict internal layers (see ARCHITECTURE section 1), enforced by `import-linter`. The domain core (graph, simulation, recovery, governance rules) is pure Python with no I/O.

## Consequences
- (+) One deploy unit, one transaction boundary, simple local dev on a low-RAM machine.
- (+) The pure core can be extracted into a library or service later if needed.
- (-) Scaling is vertical only. That is acceptable: workloads are milliseconds at the target scale.

## Alternatives considered
Microservices (operational overhead, distributed transactions for approvals); serverless functions.
