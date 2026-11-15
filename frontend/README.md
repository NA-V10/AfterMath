# AFTERMATH frontend

Next.js 16 (App Router, Turbopack) · React 19 · TypeScript · Tailwind CSS 4 · MapLibre GL · React Flow + ELK · TanStack Query.

> SIMULATION ENVIRONMENT — NOT CONNECTED TO LIVE INFRASTRUCTURE.

## Run

```powershell
pnpm install
pnpm dev                 # http://localhost:3000 (expects the API at http://localhost:8000)
```

Set `NEXT_PUBLIC_API_ORIGIN` (e.g. in `frontend/.env.local`) to point at a different backend.

## Checks

```powershell
pnpm typecheck           # tsc
pnpm lint                # eslint
pnpm test                # vitest unit tests
pnpm test:e2e            # Playwright against the real backend; uses the installed Edge (PW_CHANNEL=msedge)
pnpm build               # production build
```

## API types

`types/api.d.ts` is generated from the backend's OpenAPI contract and must not be edited by hand:

```powershell
cd ../backend; uv run python -m app.cli export-openapi   # writes frontend/types/openapi.json
cd ../frontend; pnpm gen:api                              # writes types/api.d.ts
```

## Layout

| Path | Contents |
|---|---|
| `app/` | Routes: `/` Command Center, `/twin`, `/lab`, `/recovery`, `/agents`, `/audit` |
| `components/` | Shell (banner, navigation) and UI primitives |
| `features/` | Screen-level features (`twin/`, `command-center/`, `audit/`) |
| `lib/` | Typed API client, query hooks, presentation metadata |
| `types/` | Generated OpenAPI types |
| `e2e/` | Playwright journeys |

Screens whose backend capability does not exist yet show a phase notice, never placeholder data.
