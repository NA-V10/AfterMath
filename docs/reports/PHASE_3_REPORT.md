# Phase 3 Report — Multi-Agent System

**Date:** 2026-11-21 · **Status:** complete for SENTINEL, CARTOGRAPHER and ORACLE. STRATEGIST and GUARDIAN are defined but not wired in, because they need the Phase 4 recovery engine. They are reported as unavailable rather than imitated.

## Delivered

| Area | What exists |
|---|---|
| LLM layer (`app.llm`) | Provider-neutral structured-output contract. Providers: **deterministic** (default, offline), **Anthropic** (official SDK, `claude-opus-5-5`, refusal fallbacks on), **OpenAI-compatible** (Ollama/vLLM/gateways). A fallback chain gives bounded retries for transient errors, one repair attempt for invalid output, and deterministic fallback, with every attempt recorded. |
| Orchestration | LangGraph `StateGraph` with typed state, per-node retry policies, a human-in-the-loop `interrupt()` for clarification, a 300 s workflow timeout, and an **asyncpg checkpoint saver** (ADR-0013). Workflows run in the background and resume after a restart. |
| SENTINEL | Structured incidents are normalised with no LLM. For free text, the LLM (or rules) extracts quotes only; a deterministic resolver maps quotes to assets, separates damaged from affected facilities, records evidence spans and scores confidence. At low confidence it asks a human. |
| CARTOGRAPHER | Deterministic downstream reach, exact N-1 single points of failure, and redundancy effects (required supply lost, supporting service lost, no spare left), plus a briefing that has passed the grounding check. |
| ORACLE | Runs and persists the incident simulation, applies it to the operational picture, and extracts critical failure chains and backup deadlines, plus a grounding-checked narrative. |
| Records | Each `agent_execution` stores its status, summary, structured output, tool calls (with result digests), LLM attempts, grounding result, tokens and latency. No model reasoning is stored. |
| API | `POST /incidents/{id}/analyze` (202), `GET /workflows`, `GET /workflows/{id}`, `POST /workflows/{id}/clarify`, `GET /workflows/{id}/events` (SSE), `GET /agents`, `GET /agents/activity`, `GET /agents/executions/{id}` |
| Frontend | **Agent Activity:** incident intake (free text or structured), live five-agent pipeline (SSE with polling fallback), a per-agent output view (evidence, matches, briefing, chains, deadlines, tool calls, LLM attempts, grounding badge), and a clarification form. |

## Tests (actual results, final run)

| Suite | Result |
|---|---|
| Backend pytest | **129 passed** (98 before this phase) |
| ruff, ruff format, mypy, import-linter (3 contracts; new: the LLM layer cannot touch domain or data) | clean |
| Frontend Vitest / tsc / ESLint / `next build` | 14 passed / clean / clean / success |
| Playwright E2E (Edge) | **11 passed** (2 new agent journeys) |

New coverage:
- **Corpus:** SENTINEL on the 10-report labelled corpus, including a prompt-injection report and an unrecognisable report.
- **Fallback chain:** timeouts, transient failure followed by success, repair of invalid output, refusal, and configuration errors.
- **Grounding:** the grounding check itself.
- **Checkpointer:** interrupt and resume with a fresh saver, simulating a restart.
- **Workflows:** a full structured workflow, a free-text workflow, the clarification round-trip, and the one-active-analysis rule.
- **Provider outage:** all agents FELL_BACK, and the workflow still completes.
- **Hallucinating LLM:** the invented asset and figure are discarded, the deterministic text is shown, and the rejection is recorded.
- **Stream:** the SSE stream.

## Defects found and fixed during the phase

- **Recorder crash:** serialising LLM attempt records failed on slots dataclasses. Found because the workflow correctly recorded itself as FAILED.
- **Duplicate-analysis error:** a duplicate analysis returned 500 instead of 409, because the ORM row was used after a rollback.
- **Startup with the database down:** resuming workflows at startup crashed the app when the database was unreachable. It now logs a warning, and readiness reports the outage.
- **Migration downgrade:** migration 0003 couldn't downgrade with `ANALYZED` rows present. The downgrade is now explicitly lossy, and the test database reset now drops the schema.
- **Misleading briefing:** CARTOGRAPHER reported SOFT SCADA losses as "requirements lost". It now separates required from supporting losses.
- **Fragile tests:** an audit E2E test assumed the seeding record was on page 1.

## Open items / known gaps

- **STRATEGIST and GUARDIAN** need the Phase 4 recovery engine.
- **SENTINEL accuracy is not established.** 10/10 is on a corpus the rules were tuned against. A held-out corpus, and a live-LLM evaluation, are still needed. The LLM providers are implemented but **were not exercised against a live API** in this phase: there is no key on this machine, and live calls cost money, which needs your approval.
- **Authentication:** analysis and clarification are unauthenticated until Phase 5 (attributed to `local:operator`).
- **Single-process orchestration:** concurrent workflows are bounded by one API process (ADR-0006).
