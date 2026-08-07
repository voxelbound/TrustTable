# Local development

Repository-foundation stage (`FND-01`): only operational endpoints and a
placeholder frontend route exist. No product features are implemented yet.
This document covers running the backend and frontend natively, running the
full stack with Docker Compose, and running the test suites — nothing more.

## Prerequisites

- **Python 3.14** and [`uv`](https://docs.astral.sh/uv/) (backend dependency
  management; `uv.lock` is committed).
- **Node.js 24 (Active LTS)** and npm (frontend; `package-lock.json` is
  committed).
- **Docker** with Compose v2 (`docker compose ...`, not the standalone
  `docker-compose` binary) — required for the full-stack Compose run and the
  Docker Compose integration smoke test.

## Backend — native

```sh
cd backend
uv sync
uv run uvicorn trusttable_backend.main:app --reload --port 8000
```

- `GET http://127.0.0.1:8000/api/v1/health/live`
- `GET http://127.0.0.1:8000/api/v1/health/ready`
- `GET http://127.0.0.1:8000/api/v1/version`

Configuration is validated at startup and works with no setup at all —
see [`docs/configuration.md`](configuration.md) for every setting, its
default, and effect. To override a default, copy `.env.example` to `.env`
at the repository root (read automatically, native and Docker) or export
environment variables directly; an invalid value stops startup with a
clear error instead of running with bad configuration.

## Frontend — native

```sh
cd frontend
npm install
npm run dev
```

Opens the Vite dev server (default `http://127.0.0.1:5173`). The placeholder
route renders without a running backend — its query resolves a local value
only, so no proxy is configured in dev mode.

## Full stack — Docker Compose

```sh
docker compose up --build
```

- Frontend (Nginx-served production build): `http://127.0.0.1:8080`
- Backend (direct, for diagnostics): `http://127.0.0.1:8000`
- The frontend proxies `/api/v1/*` to the backend and falls back to
  `index.html` for unknown routes (SPA fallback).

Stop and remove the stack:

```sh
docker compose down
```

Only ports `8000` and `8080` are published. No database, debug ports, or
production hardening (SBOM/dependency/container scanning) exist at this
stage — that is `SEC-01`/`REL-01` scope.

## Running the tests

| Suite | Command | Notes |
|---|---|---|
| Backend unit/API (pytest) | `uv run --project backend pytest backend/tests -v` | Ruff/mypy: `uv run --project backend ruff check backend` / `uv run --project backend mypy backend` |
| Frontend component (Vitest) | `npm --prefix frontend run test` | |
| Frontend lint/types | `npm --prefix frontend run lint` / `npx --prefix frontend tsc -b frontend --noEmit` | |
| Docker Compose integration smoke test (pytest) | `uv run --project backend pytest tests/integration -v` | Builds images and runs a full `docker compose up`/`down` cycle against a real Docker daemon; not part of the default backend test suite |
| Playwright browser/accessibility smoke test | `npm --prefix frontend run test:e2e` | Brings the Compose stack up itself (`playwright.config.ts` `webServer`); requires Chromium's OS shared library dependencies to be installed on the host (see below) |

### Playwright browser dependency

Playwright's browser binary is installed with:

```sh
npx --prefix frontend playwright install chromium
```

On a minimal Linux host, the downloaded Chromium/headless-shell binary may
still fail to launch with an error such as `libnspr4.so: cannot open shared
object file`. That indicates missing OS-level shared libraries (NSPR/NSS),
not an application or test defect. Installing them (for example via
`playwright install-deps chromium`, or an equivalent explicit package list)
requires OS package manager access (`apt`/`sudo` on Debian-based images) and
is a deliberate, separately authorized step — it is not run automatically.

**Known limitation:** in some environments, Playwright's `webServer` does not
reliably stop the `docker compose up` process it starts once the test run
finishes, leaving the stack running. If `docker compose ps` (run from the
repository root) still shows `trusttable-backend-1`/`trusttable-frontend-1`
after `npm run test:e2e`, stop them manually with `docker compose down`.
