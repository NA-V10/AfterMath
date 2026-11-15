# AFTERMATH — Product Requirements Document

> "When everything fails, we figure out what to save, what to fix, and how to bring everything back."

**Status:** Draft v0.1 (Phase 0) · **Owner:** Project owner · **Last updated:** 2026-11-15

> **SIMULATION ENVIRONMENT — NOT CONNECTED TO LIVE INFRASTRUCTURE.**
> AFTERMATH is a simulation and decision-support platform. It never connects to, controls or issues commands to real-world infrastructure.

## 1. Problem

Critical infrastructure is tightly coupled. When a substation fails, hospitals, telecom, water treatment and emergency coordination can follow, each on its own timescale, which depends on backup power and redundancy. Monitoring tools report *that* something failed. They rarely answer:

1. What happened?
2. What infrastructure is affected, now and over the next hours?
3. What additional failures will follow, and when?
4. What should be restored first, given limited crews, parts, fuel and budget?
5. Did the recovery actually restore *services*, not just repair *assets*?

## 2. Users

| Persona | Need | Permissions (see [SECURITY.md](SECURITY.md)) |
|---|---|---|
| **Viewer / analyst** | Explore the twin, run what-if simulations | `viewer` |
| **Operator** | Report incidents, run analyses, generate strategies, execute approved plans | `operator` |
| **Approver (incident commander)** | Review strategies and approve or reject them, with comments | `approver` |
| **Administrator** | Manage users, inventory and datasets | `admin` |

## 3. Product principles

1. **Deterministic core, explanatory AI.** All numbers (propagation, impact, schedules, resource use) come from deterministic, reproducible engines. LLMs interpret unstructured input and explain results. They never compute and never authorise.
2. **Human authority.** Nothing executes without explicit human approval of a validated, content-hashed plan.
3. **Auditable by construction.** Every state change produces an append-only audit record.
4. **Works offline.** Demo mode needs no API key and no third-party tiles.
5. **Synthetic and labelled.** All data is synthetic and marked as such in the database, the API and the UI.

## 4. Capabilities and requirements

Priority: **P0** is required for the end-to-end demo. **P1** is part of the product but can follow the demo. **P2** is future work.

### A. Infrastructure Digital Twin
| ID | Requirement | Pri |
|---|---|---|
| TW-1 | Fictional district with 40–50 assets across 10+ categories (power, health, telecom, water, emergency, roads, fuel, data) | P0 |
| TW-2 | Each asset has ID, code, name, category, coordinates/geometry, physical condition, functional status, criticality, capacity, utilisation, backup endurance, recovery estimate, resource requirements and metadata | P0 |
| TW-3 | Dependencies form a directed graph with typed edges (power, telecom, water, fuel, data, access) and redundancy groups (k-of-n) | P0 |
| TW-4 | Interactive map and dependency graph that show the same data, with selection kept in sync | P0 |
| TW-5 | Asset inspection, upstream/downstream exploration, filtering by category/status/criticality | P0 |
| TW-6 | Structural criticality (N-1 impact) and single-point-of-failure identification | P1 |

### B. Incident Detection
| ID | Requirement | Pri |
|---|---|---|
| IN-1 | Create incidents from a structured payload (validated deterministically) | P0 |
| IN-2 | Create incidents from free-text reports, interpreted by SENTINEL with confidence and evidence | P0 |
| IN-3 | Simulated sensor alerts (structured, scriptable) | P1 |
| IN-4 | Types: power failure, flooding, telecom outage, water disruption, equipment failure | P0 |
| IN-5 | Missing or ambiguous information is reported explicitly, never guessed silently | P0 |

### C. Cascading Failure Simulation
| ID | Requirement | Pri |
|---|---|---|
| SM-1 | Deterministic propagation over the dependency graph, including cycles and redundancy | P0 |
| SM-2 | Time-aware: backup power endurance delays failures; a chronological event timeline | P0 |
| SM-3 | Single, multiple, area (flood polygon) and combined initiating events; partial degradation | P0 |
| SM-4 | Impact score, affected population, critical-service availability, isolated components | P0 |
| SM-5 | Identical inputs give byte-identical results (result hash) | P0 |
| SM-6 | Scenario comparison | P1 |

### D. Recovery Strategy Engine
| ID | Requirement | Pri |
|---|---|---|
| RC-1 | Three strategies per incident: Critical Services First, Maximum Restoration, Balanced | P0 |
| RC-2 | Each strategy has an ordered, scheduled action list, resources, durations, expected asset and service restoration over time, risk score, benefits, limitations and rationale | P0 |
| RC-3 | Never exceeds crews, equipment, fuel or budget. Actions that cannot be scheduled are reported, not hidden | P0 |
| RC-4 | Strategy comparison view | P0 |

### E. Governance
| ID | Requirement | Pri |
|---|---|---|
| GV-1 | Strategy state machine: draft → validated → approved/rejected → executing → executed → verified | P0 |
| GV-2 | Approval is bound to the strategy's content hash; any change invalidates it | P0 |
| GV-3 | Rejected, unvalidated or stale strategies can never execute (enforced server-side) | P0 |
| GV-4 | Role-based authorisation on approve and execute | P0 (Phase 5) |
| GV-5 | Append-only, hash-chained audit log | P0 |

### F. Recovery Verification
| ID | Requirement | Pri |
|---|---|---|
| VF-1 | Re-evaluate the graph after simulated execution; distinguish *repaired* from *functionally restored* | P0 |
| VF-2 | Before/after comparison, restoration % (asset count, criticality-weighted, population), unresolved failures | P0 |
| VF-3 | Exportable recovery report (Markdown/JSON; PDF later) | P1 |

## 5. End-to-end demo (acceptance of the product)

1. Open the Command Center and see the healthy synthetic district.
2. Introduce the "Riverside substation failure" (free text or scenario).
3. SENTINEL produces a structured incident with evidence and confidence.
4. CARTOGRAPHER lists downstream dependencies and single points of failure.
5. ORACLE runs the cascade. The map and graph animate the failure waves, and the timeline shows backup expiries.
6. STRATEGIST presents three scheduled strategies. GUARDIAN validates each one.
7. The operator compares the strategies. The approver approves one, with a comment.
8. Simulated execution runs. GUARDIAN verifies outcomes.
9. The audit trail shows every step. The dashboard shows before/after health.

## 6. Non-goals (for now)

- Any connection to real infrastructure, SCADA or live data feeds.
- Multi-district, multi-tenant or real geospatial datasets.
- Power-flow or hydraulic physics simulation (the dependency model is logical, not electrical).
- Mobile apps, offline-first sync, or real-time multi-user collaboration.

## 7. Success metrics

- The end-to-end demo completes in demo mode with no API key, in under 3 minutes.
- 100% of simulation and recovery numbers are reproducible (replay hash matches).
- 0 executable paths for unapproved, rejected or invalid strategies (proven by property and stateful tests).
- SENTINEL extracts the correct incident type and asset from at least 90% of the labelled synthetic report corpus (LLM mode). Demo mode passes on its rule-based corpus.
- Every LLM explanation cites only entity IDs present in the deterministic tool output (grounding check: 100%).
