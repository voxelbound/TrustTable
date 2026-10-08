"""`GET /ai/status` (`docs/api-specification.md` §4; built by `UX-02`, D-068).

A thin route over `trusttable_backend.ai_status`: one bounded liveness probe at
most, no model completion, no dataset content, no address or path in the
response.
"""

from __future__ import annotations

from fastapi import APIRouter, Response
from starlette.concurrency import run_in_threadpool

from trusttable_backend.ai_status import compute_ai_status
from trusttable_backend.config import get_settings
from trusttable_backend.schemas.staging import AiStatusResponse

router = APIRouter(tags=["ai"])


@router.get("/ai/status", response_model=AiStatusResponse)
async def get_ai_status(response: Response) -> AiStatusResponse:
    """The honest Local AI status for the current deployment configuration."""
    response.headers["Cache-Control"] = "no-store"
    status = await run_in_threadpool(compute_ai_status, get_settings())
    return AiStatusResponse(
        assistance=status.assistance,
        state=status.state,
        location=status.location,
        provider_label=status.provider_label,
        runtime_label=status.runtime_label,
        model_label=status.model_label,
        sample_values_sent=status.sample_values_sent,
        summary=status.summary,
    )
