"""API schemas for Local AI readiness and the connection test (`UX-09`).

Closed vocabularies and fixed wording only. Nothing here carries a base URL, host,
port, filesystem path, exception text, provider detail or dataset content.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel


class ReadinessCheckResponse(BaseModel):
    key: Literal[
        "assistance_on",
        "runtime_configured",
        "runtime_on_this_machine",
        "runtime_answers",
        "model_named",
    ]
    title: str
    state: Literal["done", "todo", "attention", "not_checked"]
    detail: str


class AiReadinessResponse(BaseModel):
    ready: bool
    model_label: str | None
    runtime_label: str | None
    checks: list[ReadinessCheckResponse]


class AiConnectionTestResponse(BaseModel):
    outcome: Literal[
        "reachable",
        "not_reachable",
        "assistance_off",
        "no_runtime",
        "not_local",
        "busy",
        "too_soon",
    ]
    tested: bool
    message: str
    retry_after_seconds: int | None
