"""Operational health endpoints: `/health/live` and `/health/ready`."""

from __future__ import annotations

from fastapi import APIRouter, Response, status

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


def _run_readiness_checks() -> list[HealthCheck]:
    """Run all registered readiness checks.

    FND-01 registers only the `process` check, which always reports
    `"ok"`. Later backlog items (`FND-02` configuration, `DB-01`
    storage/migrations, `JOB-01` worker_pool) append further checks here
    without changing the response shape.
    """
    return [HealthCheck(name="process", status="ok", detail=None)]


@router.get("/health/ready", response_model=ReadinessResponse)
def get_readiness(response: Response) -> ReadinessResponse:
    """Report readiness. HTTP 200 when ready, HTTP 503 when not ready."""
    checks = _run_readiness_checks()
    is_ready = all(check.status == "ok" for check in checks)
    response.status_code = status.HTTP_200_OK if is_ready else status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadinessResponse(status="ready" if is_ready else "not_ready", checks=checks)
