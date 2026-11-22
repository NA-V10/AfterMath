# Roadmap & Risk Register

Complexity: S ≈ ½–1 day · M ≈ 2–4 days · L ≈ 1–2 weeks (solo developer with AI assistance).

| Phase | Objective | Key deliverables | Depends on | Complexity | Exit criteria (summary) |
|---|---|---|---|---|---|
| **0** | Architecture foundation | `docs/*`, ADRs, Phase 1 plan | — | M | ✅ complete |
| **1** | Infrastructure digital twin | Dataset + validator, asset/dependency tables, graph builder + traversal, infrastructure API, Twin screen (map + graph + inspector) | 0 | L | ✅ complete ([report](reports/PHASE_1_REPORT.md)) |
| **2** | Deterministic simulation | Lattice fixed-point evaluator, event engine, flood resolution, impact metrics, scenarios, simulation persistence + API, structural criticality, Simulation Lab basics | 1 | L | ✅ complete ([report](reports/PHASE_2_REPORT.md)) |
| **3** | Multi-agent system | `app.llm` providers + fallback, LangGraph workflow, 5 agents, execution logging, SSE, Agent Activity screen basics | 2 | L | ✅ complete ([report](reports/PHASE_3_REPORT.md)); STRATEGIST/GUARDIAN wired in Phase 4 |
| **4** | Recovery optimisation | Inventory, action catalogue, SGS scheduler, 3 policies, risk score, validator V-001…V-012, comparison | 2 (3 for agent integration) | L | ✅ complete ([report](reports/PHASE_4_REPORT.md)). V-001…V-009 built; V-010…V-012 (execution-time) moved to Phase 5. Distinct strategies only where resources are contended (2 of 4 scenarios); see report |
| **5** | Governance & execution | Auth + roles, approval/rejection, execute + revalidation, verification, audit chain, reports | 4 | M–L | P11–P14 pass; stateful governance tests pass |
| **6** | Complete frontend | All six screens on live API; loading/error states; playback; comparison; approvals; reports | 1–5 | L | E2E journeys 1–5 pass |
| **7** | Hardening & deployment | Full compose, CI, security scans, performance, README, demo walkthrough | all | M | Clean-machine setup ≤ 15 min following the README; all suites green |

Frontend work is spread across phases (Twin in 1, Lab in 2, Agents in 3, Recovery in 4–5). Phase 6 completes and polishes the screens rather than starting them.

## Risk register

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| R1 | **Low host RAM (11.7 GB, ~2.5 GB free)** slows dev; Docker + Next dev + IDE thrash | High | Medium | Hybrid dev topology (only Postgres in Docker, capped at 512 MB); Turbopack dev; full compose only for E2E |
| R2 | Python 3.14 wheel gaps for native deps | Medium | Medium | Pin 3.13 through uv; test 3.14 in CI later |
| R3 | Dependency model too simple to feel credible (or too complex to explain) | Medium | High | k-of-n groups, backup timers and partial degradation; documented semantics; golden scenarios reviewed by the owner |
| R4 | Synthetic dataset produces boring or unrealistic cascades | Medium | High | Hand-designed topology with deliberate redundancy and SPOFs; scenario expectations written *before* the engine |
| R5 | Greedy scheduler gives poor plans | Medium | Medium | Bundle valuation; brute-force gap benchmark; CP-SAT as an approved-only escalation |
| R6 | LLM hallucinates assets or numbers | High | High | Tools resolve all entities; grounding check; deterministic fallback; numbers never come from the LLM |
| R7 | Prompt injection via incident reports | Medium | High | No state-changing tools; narrow schemas; authorisation outside agents |
| R8 | LangGraph API churn | Medium | Low–Med | Pin the version; isolate workflow wiring in one module; agent logic stays in plain functions |
| R9 | Scope creep / "demo-ware" | High | High | Phase gates with acceptance criteria; endpoints only when backed; no static mock data in the UI |
| R10 | Map/graph performance and readability | Low | Medium | ≤ 60 nodes; ELK layout cached; MapLibre GeoJSON sources with feature-state for status |
| R11 | Misinterpreted as real infrastructure | Low | High | Fictional district, synthetic basemap, persistent banner, `is_synthetic` constraint |
| R12 | Governance bypass through race conditions | Low | High | Row locks, idempotency keys, unique execution per strategy, stateful tests |
