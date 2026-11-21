# AFTERMATH

> "When everything fails, we figure out what to save, what to fix, and how to bring everything back."

> **⚠ SIMULATION ENVIRONMENT — NOT CONNECTED TO LIVE INFRASTRUCTURE.**
> All infrastructure, incidents and recovery operations in AFTERMATH are synthetic. The software never connects to, controls or issues commands to real-world infrastructure.

AFTERMATH is an infrastructure resilience and disaster-recovery decision-support platform. It keeps a digital twin of a (fictional) district's interdependent infrastructure and simulates cascading failures **deterministically**. It generates resource-constrained recovery strategies, enforces **human approval** before any simulated recovery runs, and verifies that services were actually restored. Five bounded AI agents (SENTINEL, CARTOGRAPHER, ORACLE, STRATEGIST, GUARDIAN) interpret reports and explain results. They never compute the numbers and never authorise actions.

## Status

| Phase | Scope | State |
|---|---|---|
| 0 | Architecture & documentation | ✅ complete |
| 1 | Infrastructure digital twin | ✅ complete ([report](docs/reports/PHASE_1_REPORT.md)) |
| 2 | Deterministic simulation engine | ✅ complete ([report](docs/reports/PHASE_2_REPORT.md)) |
| 3 | Multi-agent system | ✅ complete ([report](docs/reports/PHASE_3_REPORT.md)) |
| 4 | Recovery optimisation | next |

## Quick start (Windows / PowerShell, hybrid dev mode)

Prerequisites: Docker Desktop (running), [uv](https://docs.astral.sh/uv/), Node 20+ and pnpm.

> On the current dev machine `uv` was installed with `pip install --user uv` and its folder
> (`%APPDATA%\Python\Python314\Scripts`) is not on `PATH`. Either add that folder to `PATH`
> or write `python -m uv` wherever this guide says `uv`.

```powershell
copy .env.example .env                 # local-only defaults
docker compose up -d db                # PostgreSQL 16 (localhost only)

cd backend
uv sync                                # Python 3.13 venv + dependencies
uv run python -m alembic upgrade head  # create the schema
uv run python -m app.cli seed          # load the synthetic district + scenarios (idempotent)
uv run python -m uvicorn app.main:app --port 8000   # API: http://localhost:8000/api/v1/docs

cd ..\frontend
pnpm install
pnpm dev                               # UI: http://localhost:3000
```

### Tests

```powershell
cd backend
uv run python -m pytest                # unit + Hypothesis property + integration (needs the db container)
uv run python -m ruff check . ; uv run python -m mypy app
uv run python -c "from importlinter.cli import lint_imports_command; lint_imports_command()"

cd ..\frontend
pnpm typecheck ; pnpm lint ; pnpm test ; pnpm build
pnpm test:e2e                          # Playwright via installed Microsoft Edge
```

> On this machine Windows Application Control blocks some executable shims (e.g. `pytest.exe`),
> so tools are invoked as `python -m <tool>`. See [docs/ENVIRONMENT.md](docs/ENVIRONMENT.md).

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
| [docs/PHASE_1_PLAN.md](docs/PHASE_1_PLAN.md) | Phase 1 plan and acceptance criteria |
| [docs/ENVIRONMENT.md](docs/ENVIRONMENT.md) | Dev environment assessment and constraints |
| [docs/decisions/](docs/decisions/README.md) | Architecture Decision Records |

## Repository layout

```
backend/    FastAPI app (app/graph = pure domain core), Alembic migrations, tests
frontend/   Next.js app (Twin, Command Center, Audit; other screens arrive with their phases)
data/       Synthetic dataset, scenario definitions, generated JSON Schemas
docs/       Product, architecture, ADRs, reports
scripts/    Database init scripts
```
