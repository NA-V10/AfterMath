# AFTERMATH

> "When everything fails, we figure out what to save, what to fix, and how to bring everything back."

> **⚠ SIMULATION ENVIRONMENT — NOT CONNECTED TO LIVE INFRASTRUCTURE.**
> All infrastructure, incidents and recovery operations in AFTERMATH are synthetic. The software never connects to, controls or issues commands to real-world infrastructure.

AFTERMATH is an infrastructure resilience and disaster-recovery decision-support platform. It keeps a digital twin of a (fictional) district's interdependent infrastructure and simulates cascading failures **deterministically**. It generates resource-constrained recovery strategies, enforces **human approval** before any simulated recovery runs, and verifies that services were actually restored. Five bounded AI agents (SENTINEL, CARTOGRAPHER, ORACLE, STRATEGIST, GUARDIAN) interpret reports and explain results. They never compute the numbers and never authorise actions.

## Status

**Phase 0: architecture foundation (complete, awaiting review).** No application code yet.

## Documentation

| Doc | Contents |
|---|---|
| [docs/PRD.md](docs/PRD.md) | Product requirements |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | System architecture, layers, flows, stack, repo layout |
| [docs/SIMULATION_ENGINE.md](docs/SIMULATION_ENGINE.md) | Dependency model and cascading-failure algorithm |
| [docs/RECOVERY_OPTIMIZATION.md](docs/RECOVERY_OPTIMIZATION.md) | Recovery scheduling, strategies, risk, validation |
| [docs/AGENT_DESIGN.md](docs/AGENT_DESIGN.md) | The five agents, LangGraph workflow, LLM abstraction |
| [docs/DATA_MODEL.md](docs/DATA_MODEL.md) | Entities, relationships, lifecycles |
| [docs/API_DESIGN.md](docs/API_DESIGN.md) | `/api/v1` contract |
| [docs/SECURITY.md](docs/SECURITY.md) | Safety boundary, threat model, governance |
| [docs/TESTING_STRATEGY.md](docs/TESTING_STRATEGY.md) | Test layers and required properties |
| [docs/ROADMAP.md](docs/ROADMAP.md) | Phases and risk register |
| [docs/PHASE_1_PLAN.md](docs/PHASE_1_PLAN.md) | Next phase task breakdown |
| [docs/ENVIRONMENT.md](docs/ENVIRONMENT.md) | Dev environment assessment |
| [docs/decisions/](docs/decisions/README.md) | Architecture Decision Records |

## Stack (planned)

Next.js · React · TypeScript · Tailwind · shadcn/ui · MapLibre · React Flow · Recharts — FastAPI · Pydantic · SQLAlchemy · Alembic · LangGraph · NetworkX · Shapely — PostgreSQL — Docker Compose.
