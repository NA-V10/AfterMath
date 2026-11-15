# ADR-0008: Content-hash-bound approvals, explicit state machines, append-only hash-chained audit

- **Status:** Proposed (Phase 0, pending owner review)
- **Date:** 2026-11-15

## Context
Human approval must be meaningful: what was approved must be exactly what executes, and history must be tamper-evident.

## Decision
Strategies carry a canonical `content_hash`. Approvals record and require that hash. Execution re-verifies the hash and revalidates against the current inventory and picture inside a row-locked transaction with a required Idempotency-Key. Transitions are defined in one pure state-machine module. The audit log is append-only (trigger + grants) and hash-chained. Details: [SECURITY.md](../SECURITY.md).

## Consequences
- (+) Rejected, invalid, stale or altered strategies are provably non-executable; tamper-evidence is cheap.
- (-) Any edit to a strategy forces re-validation and re-approval. This is intended.

## Alternatives considered
Boolean `approved` flag (TOCTOU and tampering risk); event-sourcing the whole system (overkill).
