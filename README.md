# AFTERMATH

> "When everything fails, we figure out what to save, what to fix, and how to bring everything back."

> **⚠ SIMULATION ENVIRONMENT — NOT CONNECTED TO LIVE INFRASTRUCTURE.**
> All infrastructure, incidents and recovery operations in AFTERMATH are synthetic. The software never connects to, controls or issues commands to real-world infrastructure.

AFTERMATH is an infrastructure resilience and disaster-recovery decision-support platform.

- **Digital twin:** it keeps a digital twin of a fictional district's interdependent infrastructure.
- **Simulation:** it simulates cascading failures **deterministically**.
- **Recovery:** it generates recovery strategies that respect crew and stock limits, and requires **human approval** before any simulated recovery runs.
- **Verification:** it verifies that services were actually restored.
- **Agents:** five bounded AI agents (SENTINEL, CARTOGRAPHER, ORACLE, STRATEGIST, GUARDIAN) interpret reports and explain results. They never compute the numbers and never authorise actions.

## Status

All eight phases are complete; see each phase's report for its open items.

| Phase | Scope | Report |
|---|---|---|
| 0 | Architecture & documentation | — |
| 1 | Infrastructure digital twin | [report](docs/reports/PHASE_1_REPORT.md) |
| 2 | Deterministic simulation engine | [report](docs/reports/PHASE_2_REPORT.md) |
| 3 | Multi-agent system | [report](docs/reports/PHASE_3_REPORT.md) |
| 4 | Recovery optimisation | [report](docs/reports/PHASE_4_REPORT.md) |
| 5 | Governance & execution | [report](docs/reports/PHASE_5_REPORT.md) |
| 6 | Complete frontend | [report](docs/reports/PHASE_6_REPORT.md) |
| 7 | Hardening & deployment | [report](docs/reports/PHASE_7_REPORT.md) |

## Quick start: the full stack in containers (recommended)

**Prerequisites:** Docker with Compose v2 (Docker Desktop on Windows or macOS) and Python 3.11+ (only to generate secrets).

```sh
python scripts/init_env.py                       # writes .env with random secrets (git-ignored)
docker compose --profile full up -d --build --wait
```

**First run:**
- The first build takes a few minutes. Later starts take about 30 seconds.
- A one-shot `migrate` container creates the schema, loads the synthetic district, scenarios and inventory, and creates the demo accounts.

**Open the app:**
- <http://localhost:3000>: the product page.
- <http://localhost:3000/command>: the console. Sign in as `viewer`, `operator`, `approver` or `admin`; the password is `DEMO_PASSWORD` in `.env`.
- <http://localhost:8000/api/v1/docs>: the API, OpenAPI interactive docs.

**A first scenario:** [docs/DEMO.md](docs/DEMO.md) walks through a storm from report to verified recovery in about ten minutes.

**Stop or reset:**
- `docker compose --profile full down` stops the stack.
- Add `-v` to also delete the database volume.

**What the stack runs**
- **Mode:** production. The API refuses placeholder secrets.
- **Ports:** bound to localhost only.
- **Containers:** non-root, read-only, with all Linux capabilities dropped.
- **Language model:** none by default. The agents run in deterministic mode with no AI provider or key. To use a model, set `LLM_PROVIDER` and `LLM_API_KEY` in `.env`; see [docs/AGENT_DESIGN.md](docs/AGENT_DESIGN.md).

## Development: hybrid mode (Windows / PowerShell)

The API and web app run natively for fast reloads; only PostgreSQL runs in Docker.

**Prerequisites:** Docker, [uv](https://docs.astral.sh/uv/), Node 22+ and pnpm 12.

```powershell
python scripts/init_env.py             # or copy .env.example .env and set JWT_SECRET, DEMO_PASSWORD
docker compose up -d db                # PostgreSQL 16 (localhost only)

cd backend
uv sync                                # Python 3.13 venv + dependencies
uv run python -m alembic upgrade head  # create the schema
uv run python -m app.cli seed          # synthetic district, scenarios and inventory (idempotent)
uv run python -m app.cli seed-users    # demo accounts (password: DEMO_PASSWORD in .env)
uv run python -m uvicorn app.main:app --port 8000

cd ..\frontend
pnpm install
pnpm dev                               # http://localhost:3000 (product page), /command (console)
```

## Roles

Everything requires signing in.

| Role | Can |
|---|---|
| Viewer | Read everything and run what-if simulations |
| Operator | Report incidents, run analyses and execute approved plans |
| Approver | Approve or reject plans |
| Admin | Change the inventory and reset the operational picture |

By default an approver cannot approve a plan they requested (separation of duties). Execution is **simulated**: it replays the plan in the simulator.

## Tests and checks

CI runs all of this on every push: [.github/workflows/ci.yml](.github/workflows/ci.yml).

```sh
# backend (native)
cd backend
uv run pytest > pytest.log             # unit, property and integration (needs the db container)
uv run ruff check . && uv run mypy app && uv run lint-imports

# backend in a container: for hosts that block native extensions (see docs/ENVIRONMENT.md)
docker build -f backend/Dockerfile --target test -t aftermath-api:test .
docker run --rm --network aftermath_default \
  -e TEST_DATABASE_URL=postgresql+asyncpg://aftermath:<POSTGRES_PASSWORD>@db:5432/aftermath_test \
  aftermath-api:test

# frontend
cd frontend
pnpm typecheck && pnpm lint && pnpm test && pnpm build
DEMO_PASSWORD=... pnpm test:e2e        # Playwright against a running stack (Edge locally, Chromium in CI)
```

## Documentation

| Doc | Contents |
|---|---|
| [docs/DEMO.md](docs/DEMO.md) | Guided walkthrough |
| [docs/PRD.md](docs/PRD.md) | Product requirements |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | System architecture, layers, flows, stack, repository layout |
| [docs/SIMULATION_ENGINE.md](docs/SIMULATION_ENGINE.md) | Dependency model and cascading-failure algorithm |
| [docs/RECOVERY_OPTIMIZATION.md](docs/RECOVERY_OPTIMIZATION.md) | Recovery scheduling, strategies, risk, validation |
| [docs/AGENT_DESIGN.md](docs/AGENT_DESIGN.md) | The five agents, LangGraph workflow, LLM abstraction |
| [docs/DATA_MODEL.md](docs/DATA_MODEL.md) | Entities, relationships, lifecycles |
| [docs/API_DESIGN.md](docs/API_DESIGN.md) | `/api/v1` contract |
| [docs/SECURITY.md](docs/SECURITY.md) | Safety boundary, threat model, governance, hardening |
| [docs/TESTING_STRATEGY.md](docs/TESTING_STRATEGY.md) | Test layers and required properties |
| [docs/ROADMAP.md](docs/ROADMAP.md) | Phases and risk register |
| [docs/ENVIRONMENT.md](docs/ENVIRONMENT.md) | Dev environment and host constraints |
| [docs/decisions/](docs/decisions/README.md) | Architecture Decision Records |

## Repository layout

```
backend/    FastAPI app (app/graph, simulation, recovery, governance/rules = pure core), migrations, tests, Dockerfile
frontend/   Next.js app: console under app/(console); static product page in public/landing; Dockerfile
data/       Synthetic dataset, scenario definitions, generated JSON Schemas
docs/       Product, architecture, ADRs, reports, demo walkthrough
scripts/    init_env.py (secrets), perf_api.mjs (latency), db init SQL
.github/    CI workflow
```
