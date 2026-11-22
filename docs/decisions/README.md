# Architecture Decision Records

| ADR | Decision | Status |
|---|---|---|
| [ADR-0001](ADR-0001-modular-monolith.md) | Modular monolith backend | Proposed |
| [ADR-0002](ADR-0002-networkx-graph-engine.md) | NetworkX in-memory graph; no Neo4j | Proposed |
| [ADR-0003](ADR-0003-fixed-point-propagation.md) | Greatest-fixed-point propagation over a status lattice with discrete-event time | Proposed |
| [ADR-0004](ADR-0004-recovery-scheduling-heuristic.md) | Priority-rule serial schedule generation with independent validation | Proposed |
| [ADR-0005](ADR-0005-llm-boundary-and-providers.md) | LLM boundary and provider-neutral abstraction | Proposed |
| [ADR-0006](ADR-0006-langgraph-orchestration.md) | LangGraph orchestration, in-process, Postgres checkpointer, no Redis | Proposed |
| [ADR-0007](ADR-0007-postgres-jsonb-geometry.md) | PostgreSQL with GeoJSON in JSONB; no PostGIS | Proposed |
| [ADR-0008](ADR-0008-governance-hash-bound-approvals.md) | Content-hash-bound approvals, explicit state machines, append-only hash-chained audit | Accepted (Phase 5) |
| [ADR-0009](ADR-0009-fictional-district-basemap.md) | Fictional district on a synthetic basemap | Proposed |
| [ADR-0010](ADR-0010-sse-for-realtime.md) | Server-Sent Events for progress streams | Proposed |
| [ADR-0011](ADR-0011-openapi-generated-types.md) | OpenAPI as the single API contract; generated TypeScript types | Proposed |
| [ADR-0012](ADR-0012-local-dev-topology.md) | Hybrid local development topology | Proposed |
| [ADR-0013](ADR-0013-asyncpg-langgraph-checkpointer.md) | LangGraph checkpointer on asyncpg | Accepted |
| [ADR-0014](ADR-0014-authentication-and-sessions.md) | Bearer-token auth (PyJWT HS256), scrypt passwords, roles re-read per request | Accepted |
