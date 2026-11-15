# Development Environment Assessment (Phase 0)

Inspected: 2026-11-15

## Repository state

`E:\aftermath` was empty and not a git repository. No existing work had to be preserved.

## Host

| Item | Found | Implication |
|---|---|---|
| OS | Windows 11 Home (10.0.26300) | Use POSIX-agnostic scripts. Write all scripts in Python or as cross-platform `pnpm`/`uv` tasks rather than bash-only. |
| CPU | Intel i3-1005G1, 4 logical cores | Builds are slow. Avoid heavy toolchains and run as few containers as possible during development. |
| RAM | 11.7 GB total, ~2.5 GB free at inspection | **Main constraint.** Docker Desktop (WSL2 VM) plus `next dev` plus Postgres plus an IDE fills it quickly. |
| Disk (E:) | 716 GB, 680 GB free | No constraint. |
| Python | 3.14.6 (`py`, `python`); `python3` is the Store alias stub | We pin the project to **3.13** through `uv` for wheel stability (asyncpg/psycopg/shapely/langgraph). 3.14 compatibility gets checked in CI later. |
| uv / poetry | not installed | Install `uv`. It is a single binary that manages the Python version, venv and lockfile. |
| Node | 24.16.0 | Fine for Next.js. |
| npm / pnpm | 11.13.0 / 12.3.4 | Use **pnpm** for the frontend (disk- and memory-efficient). |
| Docker | 29.8.0, Compose v5.5.1 | **Daemon not running** at inspection. Start Docker Desktop before Phase 1. |
| psql | not installed | Not needed. Use `docker compose exec db psql`. |
| git | 2.54.0 | Repository not yet initialised. |

## Recommended development topology

Because of the RAM limit, development runs in **hybrid mode**:

- PostgreSQL runs in Docker, with a memory limit of about 512 MB.
- The backend (uvicorn with `--reload`) and frontend (`next dev`) run natively on the host.
- The full three-container `docker compose up` is used for demos, end-to-end tests and CI. It is not the inner dev loop.

See [ADR-0012](decisions/ADR-0012-local-dev-topology.md).
