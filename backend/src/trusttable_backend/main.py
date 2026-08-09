"""FastAPI application factory.

Repository-foundation stage (FND-01): only operational endpoints are
registered. No product routes, persistence, or AI boundary exist yet.
`FND-04` adds the cross-cutting structured-error/request-ID layer that
every future route inherits automatically.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from trusttable_backend.api.v1.router import router as api_v1_router
from trusttable_backend.config import get_settings
from trusttable_backend.errors import AppError
from trusttable_backend.request_context import RequestIdMiddleware, get_request_id
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
    body = ErrorResponse(
        error=ErrorDetail(
            code=code,
            message=message,
            details=details or {},
            request_id=get_request_id(request),
        )
    )
    return JSONResponse(status_code=status_code, content=body.model_dump())


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
    """
    get_settings()
    app = FastAPI(
        title="TrustTable API",
        version=get_application_version(),
    )
    app.add_middleware(RequestIdMiddleware)
    register_exception_handlers(app)
    app.include_router(api_v1_router)
    return app


app = create_app()
