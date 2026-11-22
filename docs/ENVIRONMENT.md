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

## Findings during Phase 1 (2026-11-15)

**Windows Application Control (Smart App Control) is active.** It blocks some unsigned native binaries:

| Blocked | Workaround |
|---|---|
| `psycopg-binary`'s bundled `libpq` DLL | Switched the DB driver to **asyncpg** (loads fine). See the ARCHITECTURE stack table. |
| `.venv/Scripts/*.exe` console-script shims (`pytest.exe`, `alembic.exe`) | Run tools as `uv run python -m <tool>`. `uv run alembic` works. |
| Hypothesis's native extension | Blocked on first load only, then allowed (a reputation check). Monitor this. |

Not blocked: pydantic-core, shapely, asyncpg, Next.js SWC, lightningcss, Microsoft Edge (used by Playwright via `channel: msedge`, so no browser download is needed).

**Phase 3 risk:** `langgraph-checkpoint-postgres` requires psycopg 3. On this host that means either psycopg's pure-Python mode with a signed `libpq` from a PostgreSQL install, running the backend in Docker, or a custom asyncpg-based checkpointer. To be decided at the start of Phase 3.

**Other changes:** `uv` was installed with `pip install --user uv` (winget was not used). Python 3.13.16 is managed by uv. Docker Desktop's VM reports about 6 GB of memory. The Postgres container is capped at 512 MB.

## Findings during Phase 2 (2026-11-21)

- Application Control started blocking the **uv-created venv launcher** (`.venv/Scripts/python.exe`), including a freshly created one, and the `alembic.exe` shim. The uv-managed base interpreter is still allowed. **Workaround:** create the venv with the standard library from that base interpreter, then let uv sync into it:
  ```powershell
  & "$env:APPDATA\uv\python\cpython-3.13-windows-x86_64-none\python.exe" -m venv .venv
  python -m uv sync
  ```
  Run tools as modules: `python -m uv run --no-sync python -m pytest | alembic | app.cli`.
- The venv is disposable; nothing project-specific lives in it.

## Phase 3 note (2026-11-21)

The LangGraph checkpointer question is resolved with a custom asyncpg saver (ADR-0013); psycopg is not needed. The `anthropic` SDK and LangGraph's native dependencies (orjson, ormsgpack) load under Application Control.

## Phase 4–5 notes (2026-11-22)

**import-linter is blocked.**
- Application Control now blocks import-linter's native module (`grimp._rustgrimp`): "DLL load failed … Application Control policy".
- Until that is resolved, the three import contracts are checked with an equivalent pure-Python check. It builds an AST import graph and applies the forbidden and layers rules transitively.
- That script is not yet in the repo. Phase 7 should either add it as a fallback or run import-linter in CI on Linux.

**Long test runs can stall in PowerShell.**
- Full pytest runs whose output was piped through PowerShell (`| Select-Object` or `*>`) twice stalled for over 20 minutes at 100% CPU.
- The same run writing to a file with `> file 2>&1` completes in about 3½ minutes, and each property test passes in seconds on its own.
- The cause is not diagnosed. Redirect long runs to a file.

**Authentication settings (Phase 5).**
- The repo `.env` holds a random `JWT_SECRET` and `DEMO_PASSWORD`, generated locally and git-ignored.
- `python -m app.cli seed-users` creates the viewer, operator, approver and admin accounts with that password.
- The E2E suite reads `DEMO_PASSWORD` from the environment or from `.env`.

**New dependency:** PyJWT (pure Python). Password hashing uses the standard library's scrypt (ADR-0014).