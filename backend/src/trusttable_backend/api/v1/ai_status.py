"""`GET /ai/status` (`docs/api-specification.md` §4; built by `UX-02`, D-068).

A thin route over `trusttable_backend.ai_status`: one bounded liveness probe at
most, no model completion, no dataset content, no address or path in the
response. It reports the *effective* AI assistance (`UX-08a`): an explicit
deployment override, else the stored product setting, else off.
"""

from __future__ import annotations

from fastapi import APIRouter, Request, Response
from starlette.concurrency import run_in_threadpool

from trusttable_backend.ai_status import compute_ai_status
from trusttable_backend.effective_settings import resolve_for_request
from trusttable_backend.schemas.staging import AiStatusResponse

router = APIRouter(tags=["ai"])


@router.get("/ai/status", response_model=AiStatusResponse)
async def get_ai_status(request: Request, response: Response) -> AiStatusResponse:
    """The honest Local AI status for the effective AI assistance setting."""
    response.headers["Cache-Control"] = "no-store"
    resolution = resolve_for_request(request)
    status = await run_in_threadpool(
        compute_ai_status,
        resolution.settings,
        assistance_requested=resolution.enabled and not resolution.runtime_configured,
        unavailable_reason=resolution.unavailable_reason,
    )
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
