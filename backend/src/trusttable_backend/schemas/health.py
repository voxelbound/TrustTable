"""Pydantic schemas for the operational health endpoints.

Contracts are pinned exactly to WP-001's "Exact API contracts": field
names, types, nullability, and the extensibility of the readiness
`checks` array must not change shape when later backlog items add checks.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

LivenessStatus = Literal["alive"]
ReadinessStatus = Literal["ready", "not_ready"]
CheckStatus = Literal["ok", "failing", "not_configured"]


class LivenessResponse(BaseModel):
    """Body for `GET /api/v1/health/live`."""

    status: LivenessStatus = "alive"


class HealthCheck(BaseModel):
    """A single named readiness check entry."""

    name: str
    status: CheckStatus
    detail: str | None = None


class ReadinessResponse(BaseModel):
    """Body for `GET /api/v1/health/ready`.

    `status` is `"ready"` iff every entry in `checks` has `status: "ok"`.
    """

    status: ReadinessStatus
    checks: list[HealthCheck]
