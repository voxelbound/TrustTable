"""Operational health endpoints: `/health/live` and `/health/ready`."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response, status

from trusttable_backend.config import get_settings
from trusttable_backend.persistence import is_schema_ready
from trusttable_backend.schemas.health import (
    HealthCheck,
    LivenessResponse,
    ReadinessResponse,
)

router = APIRouter(tags=["health"])


@router.get("/health/live", response_model=LivenessResponse)
def get_liveness() -> LivenessResponse:
    """Confirm the process is running. No readiness semantics apply here."""
    return LivenessResponse()


def _configuration_check() -> HealthCheck:
    """Report whether typed `Settings` are loaded and valid.

    `create_app` already calls `get_settings()` at startup, so an invalid
    configuration prevents the process from starting at all (WP-002
    AC-04) — this check can only observe "ok" once the app is serving
    requests. It stays a real, defensive check (not a constant) so a
    future in-process reconfiguration path cannot silently go unchecked.
    """
    try:
        get_settings()
    except Exception:  # noqa: BLE001 - deliberately broad; never re-raised
        # Detail is deliberately generic, not `str(exc)`: a Pydantic
        # ValidationError's text can include the invalid field's raw
        # value, which must never reach an HTTP response (WP-002 AC-10).
        return HealthCheck(
            name="configuration",
            status="failing",
            detail="configuration failed validation at startup",
        )
    return HealthCheck(name="configuration", status="ok", detail=None)


def _storage_check(request: Request) -> HealthCheck:
    """Report whether the database schema is migrated to head (`DB-01`).

    `request.app.state.analysis_engine` is set by `main.create_app()` on
    every real application instance. `main.create_app()` already runs
    migrations to head before the app starts serving, so this check can
    only observe "failing" if the schema was altered/rolled back after
    startup, or if the database has become unreachable — the same
    "startup already enforced this, this stays a real defensive check"
    reasoning `_configuration_check` above already documents for
    `configuration`.
    """
    engine = getattr(request.app.state, "analysis_engine", None)
    if engine is None:
        return HealthCheck(name="storage", status="not_configured", detail=None)
    if is_schema_ready(engine):
        return HealthCheck(name="storage", status="ok", detail=None)
    return HealthCheck(
        name="storage",
        status="failing",
        detail="database schema is not migrated to the current head",
    )


def _run_readiness_checks(request: Request) -> list[HealthCheck]:
    """Run all registered readiness checks.

    FND-01 registered only `process` (always `"ok"`). `FND-02` appends
    `configuration`. `DB-01` appends `storage`. `JOB-01` (not yet built)
    will append further checks without changing the response shape.
    """
    return [
        HealthCheck(name="process", status="ok", detail=None),
        _configuration_check(),
        _storage_check(request),
    ]


@router.get("/health/ready", response_model=ReadinessResponse)
def get_readiness(request: Request, response: Response) -> ReadinessResponse:
    """Report readiness. HTTP 200 when ready, HTTP 503 when not ready."""
    checks = _run_readiness_checks(request)
    is_ready = all(check.status == "ok" for check in checks)
    response.status_code = status.HTTP_200_OK if is_ready else status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(status="ready" if is_ready else "not_ready", checks=checks)
