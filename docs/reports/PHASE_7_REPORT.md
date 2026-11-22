# Phase 7 Report: Hardening & Deployment

**Date:** 2026-11-22 · **Status:** complete. This is the last phase on the roadmap.

## Delivered

### Containers

- **Images.**
  - `backend/Dockerfile` has a `runtime` target (Python 3.13 slim, uv, non-root, health check) and a `test` target (dev dependencies and tests).
  - `frontend/Dockerfile` builds Next's standalone server (Node 24 slim, non-root, health check).
- **`docker compose --profile full`** runs four services:

  | Service | Role |
  |---|---|
  | `db` | Postgres |
  | `migrate` | One-shot: migrations, seed data, demo accounts |
  | `api` | The API |
  | `web` | The web app |

  Each service waits for the one before it to be healthy or to finish.
- **Hardened containers:**
  - read-only root filesystems with tmpfs;
  - `no-new-privileges` and all capabilities dropped;
  - ports on localhost only;
  - memory limits;
  - production mode by default.
- **`scripts/init_env.py`** writes `.env` with random secrets. `.dockerignore` keeps `.env` and `.git` out of the images.

### CI

`.github/workflows/ci.yml` has four jobs:

| Job | What it runs |
|---|---|
| **Backend** | Postgres service; ruff and format; mypy strict; import-linter and the fallback check; pytest; pip-audit; `alembic check` |
| **Frontend** | tsc, ESLint, Vitest, build, `pnpm audit --audit-level high` |
| **E2E** | The full compose stack with throwaway secrets, Playwright in Chromium, logs and traces on failure |
| **Secrets** | gitleaks |

The workflow passes `actionlint`. **It has not run on GitHub**: the repository has no remote.

### Security hardening ([SECURITY.md §10](../SECURITY.md))

- **Response headers.**
  - API: `nosniff`, `DENY` framing, `no-referrer`, `no-store`, and a deny-all CSP on JSON responses.
  - Web app: a CSP (same-origin only, the API as the only `connect-src`, no framing, no objects), plus `nosniff`, `DENY`, `no-referrer` and a `Permissions-Policy`.
- **Failed sign-ins:** after 5 failures in 15 minutes for one username from one address, the API answers 429 with `Retry-After`. Other users at the same address are unaffected.
- **Dependencies:**
  - **Critical fix:** MapLibre GL JS upgraded from 5.24.1 to 6.19.0 for a critical XSS sanitizer bypass, GHSA-jrc7-96c5-q579. The map popup no longer parses HTML at all.
  - **Moderate fix:** minimatch overridden to a patched version (lint toolchain only).
  - **Results:** `pip-audit --strict` and `pnpm audit` both report no known vulnerabilities.
- **Secrets:** a scan of the whole git history found only the old `.env.example` placeholder.

### Other additions

- **Import contracts:** `backend/scripts/check_imports.py` is committed. It is a native-free check of the three contracts, read from `pyproject.toml`.
- **Performance:** `scripts/perf_api.mjs` measures API latency against a running stack.
- **Documentation:**
  - [DEMO.md](../DEMO.md), a ten-minute guided walkthrough;
  - a rewritten README: containers first, roles, tests and checks;
  - SECURITY §10 and ENVIRONMENT notes.

## Defects found and fixed

- **Agent Activity crashed** ("Cannot read properties of undefined (reading 'length')").
  - Cause: STRATEGIST records one grounding result per strategy, and the detail view expected a single result. It surfaced when a grounding check failed.
  - Fix: the view now folds both shapes into one (`foldGrounding`, unit-tested).
- **STRATEGIST's own deterministic text failed its grounding check** when a figure was a whole float, for example risk 60.0.
  - Cause: the allowed variants of 60.0 were only "60", never "60.0".
  - Fix: whole floats now also match their one-decimal form. Regression tests added.
- **MapLibre 6 worker failed to load** in production builds. MapLibre 6 looks for its worker next to its own module, and the bundler doesn't emit that file. The worker is now copied to `public/vendor` before dev and build, and `setWorkerUrl` points at it.
- **The recovery E2E depended on test order.** Executions consume stock, so the spec now restocks the seeded inventory first.
- **ESLint scanned vendored and generated files** (the kit, the MapLibre worker, the checker's browser profiles). They are now ignored.

## Results (actual, final runs)

| Suite | Where | Result |
|---|---|---|
| Backend: ruff, ruff format, mypy (strict, 91 files) | Linux test image | clean |
| Import contracts: real `lint-imports` and `check_imports.py` | Linux test image | 3 kept / 3 kept |
| Backend pytest (unit, property, integration, stateful) | Linux test image, against a fresh Postgres | **213 passed** |
| Frontend: tsc, ESLint, Vitest | host | clean / clean / **19 passed** |
| `next build` | host and the web image | success |
| Playwright E2E (Edge) | against the **production container stack** with CSP on | **17 passed** |
| `pip-audit --strict` / `pnpm audit` | host | no known vulnerabilities |
| `actionlint` | Docker | clean |
| Cache-free image build, then start with health waits | Docker Desktop, this machine | **144 s + 24 s.** Base-image pulls (python, node, postgres, uv) not included. |

**Clean-machine check.** A fresh compose project, with an empty Postgres volume, new secrets from `init_env.py` and nothing pre-seeded, ran:
1. migrate through 0005;
2. seed the district and demo accounts;
3. start healthy.

The full E2E suite then passed against it.

### API latency on that stack (`scripts/perf_api.mjs`)

| Operation | Median | Max |
|---|---|---|
| `GET /infrastructure/graph` | 24 ms | 30 ms |
| `GET /operational-picture` | 33 ms | 120 ms |
| `POST /simulations` (severe storm, 72 h) | 90 ms | 170 ms |
| `POST /incidents` | 28 ms | 35 ms |
| **`POST /recovery/strategies`** (3 schedules and checks) | **1,253 ms** | **2,005 ms** |
| `POST …/approve` | 35 ms | 52 ms |
| `POST …/execute` (revalidate, replay, verify) | 183 ms | 191 ms |
| `GET /audit/verify-chain` | 27 ms | 34 ms |

Planning is the only operation near a second, which is acceptable for an interactive decision step. Everything else stays under about 200 ms.

## Open items / known gaps

- **The native backend no longer runs on this development host.** During this phase Windows Application Control started blocking `xxhash`'s DLL, which LangGraph imports through `langsmith`. Use the containers (README); the hybrid dev loop works on unrestricted machines.
- **CI has never run on GitHub** (no remote). It was linted, and its steps were exercised locally: the same images, compose `--wait` and Playwright against the stack.
- **CSP still allows inline scripts** (`'unsafe-inline'`). Next's bootstrap and the static product page need them; a nonce-based CSP is the next step.
- **Single process.** The rate limiter, SSE bus and workflow runner are in-process (ADR-0006): one API replica.
- **E2E journey 5** (misconfigured LLM provider shown in the browser) remains covered by backend tests only.
- **Taste-skill rhythm findings** at 768 and 390 px on the product page, from Phase 6, were not re-checked.
- **The live LLM providers have never been exercised** against a real API. That needs a key, and your approval for paid calls.
