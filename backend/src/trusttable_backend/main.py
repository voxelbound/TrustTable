"""FastAPI application factory.

Registers operational endpoints (`FND-01`) and the `API-01` analysis
routes (`api.v1.analyses`), backed by a durable `SqlAnalysisStore`
(`DB-01`) built from `Settings.database_url`/`data_directory` — the first
real consumer of those two settings (`FND-02`). No AI boundary is wired
into the HTTP surface yet (`AI-01`, not yet built). `FND-04` adds the
cross-cutting structured-error/request-ID layer that every route
inherits automatically.

`create_app()` is a factory, not a module-level singleton: the real
process boots it via Uvicorn's `--factory` flag
(`trusttable_backend.main:create_app`, see `Dockerfile`'s `CMD` and
`docs/local-development.md`/`docs/installation-linux.md`) rather than an
eagerly-constructed `app = create_app()` module attribute. A real engine
build + Alembic migration run now has a genuine, non-trivial side effect
(creating/migrating a file on disk) that must never happen merely because
some other module imports a name from this one (for example
`export_openapi.py`, or any test importing `create_app` itself without
calling it) — every test that does call `create_app()` supplies its own
isolated `DATABASE_URL`/`DATA_DIRECTORY` (`backend/tests/conftest.py`'s
`_hermetic_settings` fixture).
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from trusttable_backend.api.v1.router import router as api_v1_router
from trusttable_backend.config import get_settings
from trusttable_backend.errors import AppError
from trusttable_backend.jobs import JobPool
from trusttable_backend.persistence import (
    SqlAnalysisStore,
    build_engine,
    reconcile_interrupted_analyses,
    run_migrations,
)
from trusttable_backend.request_context import (
    REQUEST_ID_HEADER,
    RequestIdMiddleware,
    get_request_id,
)
from trusttable_backend.schemas.errors import ErrorDetail, ErrorResponse
from trusttable_backend.version_info import get_application_version

logger = logging.getLogger(__name__)

#: HTTP status codes with no specific documented error code
#: (`docs/api-specification.md` §14) fall back to one of these two by
#: status-code class, rather than leaving the response shape undefined.
_FALLBACK_CLIENT_ERROR_CODE = "INVALID_REQUEST"
_FALLBACK_SERVER_ERROR_CODE = "INTERNAL_ERROR"
_GENERIC_INTERNAL_ERROR_MESSAGE = "An internal server error occurred."


def _error_response(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> JSONResponse:
    request_id = get_request_id(request)
    body = ErrorResponse(
        error=ErrorDetail(
            code=code,
            message=message,
            details=details or {},
            request_id=request_id,
        )
    )
    response = JSONResponse(status_code=status_code, content=body.model_dump())
    # Set directly here, not only relying on `RequestIdMiddleware`: a
    # response built by the `Exception`/500 handler is sent by Starlette's
    # `ServerErrorMiddleware`, which sits *outside* our middleware in the
    # stack, so `RequestIdMiddleware`'s post-`call_next` header assignment
    # never runs for that path. Every error response is self-sufficient.
    response.headers[REQUEST_ID_HEADER] = request_id
    return response


def register_exception_handlers(app: FastAPI) -> None:
    """Register the structured-error handlers shared by the real app and tests.

    Exported so `backend/tests/api/test_errors.py` can build an isolated
    test app from the exact same handlers `create_app` uses, instead of a
    parallel reimplementation.
    """

    @app.exception_handler(AppError)
    async def _handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        return _error_response(
            request,
            status_code=exc.status_code,
            code=exc.code,
            message=exc.message,
            details=exc.details,
        )

    @app.exception_handler(RequestValidationError)
    async def _handle_validation_error(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        # Deliberately no per-field breakdown in `details`: FastAPI/Pydantic's
        # own `errors()` includes the raw submitted `input` value, which must
        # never reach a response body (untrusted-input posture, WP-002 AC-10
        # precedent). A generic, safe message is enough at this stage; no
        # endpoint with user-facing field-level validation UX exists yet.
        return _error_response(
            request,
            status_code=422,
            code="INVALID_REQUEST",
            message="The request could not be validated.",
        )

    @app.exception_handler(StarletteHTTPException)
    async def _handle_http_exception(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        # Covers FastAPI's own default errors (e.g. 404 on an undefined
        # route, 405) with the same structured envelope instead of the
        # framework's default `{"detail": ...}` shape. `exc.detail` here is
        # always a framework-generated or application-authored safe string,
        # never raw exception internals.
        fallback = (
            _FALLBACK_SERVER_ERROR_CODE if exc.status_code >= 500 else _FALLBACK_CLIENT_ERROR_CODE
        )
        return _error_response(
            request, status_code=exc.status_code, code=fallback, message=str(exc.detail)
        )

    @app.exception_handler(Exception)
    async def _handle_unhandled_exception(request: Request, exc: Exception) -> JSONResponse:
        # Never `str(exc)` in the response body (API security requirement,
        # docs/api-specification.md §15 "no raw stack traces"). Logged
        # server-side only, keyed by the same request ID as the response.
        logger.exception("unhandled exception", extra={"request_id": get_request_id(request)})
        return _error_response(
            request,
            status_code=500,
            code=_FALLBACK_SERVER_ERROR_CODE,
            message=_GENERIC_INTERNAL_ERROR_MESSAGE,
        )


def create_app() -> FastAPI:
    """Build and return the FastAPI application instance.

    Loads and validates `Settings` first (FND-02): an invalid environment
    value raises here, before the app object exists, so the process fails
    to start rather than serving traffic with unvalidated configuration.

    `DB-01`: builds the SQLAlchemy engine, runs Alembic migrations to
    `head`, reconciles any analysis a prior process restart left
    non-terminal, and wires the real `SqlAnalysisStore` into
    `app.state.analysis_store` — the one production construction point
    that makes this package's persistence real rather than merely
    available (see `persistence/reconciliation.py`'s own docstring on
    the false positive of building this and never actually wiring it
    in). `app.state.analysis_engine` is also kept for
    `api.v1.health`'s `storage` readiness check.

    `JOB-01` (`WP-075`): wires `app.state.job_pool`, a bounded
    `JobPool` sized from `Settings.background_worker_count` — the real
    production construction point that makes `POST /demo/sales`/`POST
    /analyses` submit to a background worker instead of running the
    pipeline inside the request (see `jobs/pool.py`'s own false-positive
    disclosure). The `lifespan` context manager's shutdown half ensures
    no worker thread outlives this app instance.
    """
    settings = get_settings()
    engine = build_engine(settings)
    run_migrations(settings)
    store = SqlAnalysisStore(engine)
    reconcile_interrupted_analyses(store)
    job_pool = JobPool(store, settings.background_worker_count)

    @asynccontextmanager
    async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        job_pool.shutdown(wait=True)

    app = FastAPI(
        title="TrustTable API",
        version=get_application_version(),
        lifespan=_lifespan,
    )
    app.add_middleware(RequestIdMiddleware)
    register_exception_handlers(app)
    app.include_router(api_v1_router)
    app.state.analysis_engine = engine
    app.state.analysis_store = store
    app.state.job_pool = job_pool
    return app
