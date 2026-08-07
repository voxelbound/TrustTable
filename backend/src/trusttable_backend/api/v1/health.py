"""Operational health endpoints: `/health/live` and `/health/ready`."""

from __future__ import annotations

from fastapi import APIRouter, Response, status

from trusttable_backend.config import get_settings
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


def _run_readiness_checks() -> list[HealthCheck]:
    """Run all registered readiness checks.

    FND-01 registered only `process` (always `"ok"`). `FND-02` appends
    `configuration`. Later backlog items (`DB-01` storage/migrations,
    `JOB-01` worker_pool) append further checks without changing the
    response shape.
    """
    return [
        HealthCheck(name="process", status="ok", detail=None),
        _configuration_check(),
    ]


@router.get("/health/ready", response_model=ReadinessResponse)
def get_readiness(response: Response) -> ReadinessResponse:
    """Report readiness. HTTP 200 when ready, HTTP 503 when not ready."""
    checks = _run_readiness_checks()
    is_ready = all(check.status == "ok" for check in checks)
    response.status_code = status.HTTP_200_OK if is_ready else status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(status="ready" if is_ready else "not_ready", checks=checks)
