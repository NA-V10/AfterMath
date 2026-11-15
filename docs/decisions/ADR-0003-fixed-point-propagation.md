# ADR-0003: Greatest-fixed-point propagation over a status lattice with discrete-event time

- **Status:** Proposed (Phase 0, pending owner review)
- **Date:** 2026-11-15

## Context
Failure propagation must be deterministic, handle cycles (SCADA <-> telecom <-> power), redundancy (k-of-n), partial degradation, and time-delayed failures (backup power).

## Decision
Model functional status as levels {0,1,2}. Compute the greatest fixed point of a monotone evaluation function with synchronous (Jacobi) iteration; wave index = cascade depth. Advance time with a discrete-event queue ordered by (t_minutes, seq, asset_code). Details: [SIMULATION_ENGINE.md](../SIMULATION_ENGINE.md).

## Consequences
- (+) Final state is unique and order-independent (Knaster-Tarski); cycles handled correctly; termination bounded by 2|V| waves.
- (+) The same machinery runs recovery playback and verification.
- (-) Logical model only; no power-flow or hydraulic physics (explicit non-goal).

## Alternatives considered
BFS/DFS 'mark descendants failed' (ignores redundancy, order-dependent with cycles); stochastic agent-based simulation (not reproducible); physics simulators (out of scope).
