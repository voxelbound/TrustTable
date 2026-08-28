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

### Generating the typed API client (`FND-05`)

```sh
cd frontend
npm run generate:api-types
```

Regenerates `frontend/src/api/` (TypeScript types, typed SDK functions, and
a single configured `@hey-api/client-fetch` client instance, relative
`baseUrl: "/api/v1"`) directly from the backend's OpenAPI schema
(`backend/src/trusttable_backend/export_openapi.py` — no live server or
database required; requires a synced backend `uv` environment, since the
generator shells out to it). The output is generated-only — never hand-edit
files under `frontend/src/api/`; re-run this command instead. The CI
`contract` job fails if the committed output differs from a fresh
regeneration.

## Exercising the deterministic profiling pipeline directly

As of `PROF-03`, secure CSV parsing (`ING-02`), type inference (`PROF-02`),
and core profiling metrics (`PROF-03`) exist as backend library code, but
**no API endpoint or UI route exposes them yet** (`API-01`/`UI-01`, both
future backlog items). Until that wiring exists, the shortest way to
exercise the pipeline is to call it directly against the bundled
deterministic demo dataset (`demo-data/sales_demo.csv`, `DEMO-01`):

```sh
cd backend
uv run python -c "
from pathlib import Path
from datetime import date
from trusttable_backend.parsers.csv_parser import parse_csv
from trusttable_backend.profiling.metrics import compute_dataset_profile

content = Path('../demo-data/sales_demo.csv').read_bytes()
result = parse_csv(content)
profile = compute_dataset_profile(
    result.parsed_dataset.columns, result.rows, result.parsed_dataset.sampling,
    as_of=date(2026, 8, 24),
)
print(profile.dataset_metrics)
for cp in profile.column_profiles:
    print(cp.column.original_name, cp.inferred_type)
"
```

`as_of` is fixed to `2026-08-24` — `DEMO-01`'s own dataset-generation
`REFERENCE_DATE` — rather than `date.today()`, so the output is
reproducible and does not depend on when the command is run. Against the
committed dataset, this deterministically prints
`{'row_count': 300, 'column_count': 15, 'memory_estimate_bytes': 31875,
'duplicate_row_count': 1, 'empty_row_count': 0, 'empty_column_count': 1}`
for `dataset_metrics`, and each column's inferred type (`order_date` ->
`date`, with `future_date_count: 2` for the two rows `DEMO-01`
deliberately dates after the reference date; five numeric measure
columns -> `numeric`; `customer_name`/`product`/`category`/`region`/
`status`/`constant_col` -> `categorical`; `order_id`/`notes` -> `text`;
`empty_col` -> `unknown`).

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

## Continuous integration (`FND-03`)

`.github/workflows/ci.yml` runs on every pull request targeting `main` and
every push to `main`. All four jobs are gating (the workflow fails on any
violation); none are advisory-only.

| Job (workflow file id) | Check name shown on GitHub | Runs |
|---|---|---|
| `backend` | `Backend (formatting, lint, types, tests, dependency scan)` | `ruff format --check src tests`, `ruff check src tests`, `mypy .` (strict), `pytest tests -v`, `pip-audit` (via `uvx`, against the exported `uv.lock` dependency set) |
| `frontend` | `Frontend (formatting, lint, types, tests, dependency scan)` | `prettier --check` (`npm run format:check`), `oxlint` (`npm run lint`), `tsc -b --noEmit` (`npm run typecheck`), `vitest run` (`npm run test`), `npm audit --audit-level=high` |
| `contract` | `OpenAPI contract drift check` | Regenerates `frontend/src/api/` from the backend's OpenAPI schema (`npm run generate:api-types`) and fails if the committed output differs (`git diff --exit-code`) — see "Generating the typed API client" above |
| `integration` | `Docker Compose integration smoke tests` | `pytest tests/integration -v` — builds both Docker images and exercises the full Compose stack (see "Running the tests" above); satisfies the backlog's "Docker build" check via real integration coverage rather than a bare build-only step |

**Not yet in CI** (deliberately deferred, tracked separately):

- All browser/accessibility (Playwright/axe) tests — release-candidate
  scope only, not a PR gate, per `docs/testing-strategy.md` §8.
- SBOM generation, container scan, license check, performance benchmark
  review — release-candidate scope only, per `docs/testing-strategy.md` §8.

These exact job/check names are required to configure GitHub branch
protection's required status checks — a separate, explicitly authorized
repository-settings change, not performed by this workflow's addition
alone.
