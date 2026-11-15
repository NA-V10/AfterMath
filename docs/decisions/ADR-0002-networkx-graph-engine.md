# ADR-0002: NetworkX in-memory graph; no Neo4j

- **Status:** Proposed (Phase 0, pending owner review)
- **Date:** 2026-11-15

## Context
The twin has ~50 nodes, growing to perhaps a few thousand. Propagation needs custom k-of-n lattice semantics that no graph database provides natively.

## Decision
Persist assets and edges relationally in PostgreSQL. Build an immutable `TwinSnapshot` and an `nx.MultiDiGraph` in memory per snapshot version (cached). Custom evaluators run over plain adjacency maps derived from the snapshot.

## Consequences
- (+) No extra database to operate; traversal is microseconds at this scale; easy to test.
- (-) Very large graphs (>100k nodes) would need another approach. Not a foreseeable requirement.

## Alternatives considered
Neo4j (operational cost; Cypher doesn't express our fixed-point semantics); igraph/rustworkx (faster but unnecessary; possible later behind the same interface).
