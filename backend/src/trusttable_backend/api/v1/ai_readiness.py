"""`GET /ai/readiness` and `POST /ai/connection-test` (`UX-09`, D-066 item 10).

Thin routes over `trusttable_backend.ai_readiness`. Neither accepts any input: the
test has no body, query parameter or header that selects a target, so a forged request
can only ask the server to check the runtime it is already configured to use, and
that is rate-limited. No download, installation or runtime control exists here.
"""

from __future__ import annotations

import threading

from fastapi import APIRouter, Request, Response
from starlette.concurrency import run_in_threadpool

from trusttable_backend.ai_readiness import (
    ConnectionTestGate,
    compute_readiness,
    run_connection_test,
)
from trusttable_backend.ai_status import compute_ai_status
from trusttable_backend.effective_settings import resolve_for_request
from trusttable_backend.schemas.ai_readiness import (
    AiConnectionTestResponse,
    AiReadinessResponse,
    ReadinessCheckResponse,
)

router = APIRouter(tags=["ai"])

_GATE_LOCK = threading.Lock()


def _gate_for(request: Request) -> ConnectionTestGate:
    """The one gate for the app serving `request`, created on first use."""
    with _GATE_LOCK:
        gate: ConnectionTestGate | None = getattr(request.app.state, "ai_connection_gate", None)
        if gate is None:
            gate = ConnectionTestGate()
            request.app.state.ai_connection_gate = gate
        return gate


@router.get("/ai/readiness", response_model=AiReadinessResponse)
async def get_ai_readiness(request: Request, response: Response) -> AiReadinessResponse:
    """The Local AI setup checklist for the effective AI assistance setting."""
    response.headers["Cache-Control"] = "no-store"
    resolution = resolve_for_request(request)
    status = await run_in_threadpool(
        compute_ai_status,
        resolution.settings,
        assistance_requested=resolution.enabled and not resolution.runtime_configured,
        unavailable_reason=resolution.unavailable_reason,
    )
    readiness = compute_readiness(resolution, status)
    return AiReadinessResponse(
        ready=readiness.ready,
        model_label=readiness.model_label,
        runtime_label=readiness.runtime_label,
        checks=[
            ReadinessCheckResponse(
                key=check.key, title=check.title, state=check.state, detail=check.detail
            )
            for check in readiness.checks
        ],
    )


@router.post("/ai/connection-test", response_model=AiConnectionTestResponse)
async def post_ai_connection_test(request: Request, response: Response) -> AiConnectionTestResponse:
    """Check once whether the configured local runtime answers; takes no input."""
    response.headers["Cache-Control"] = "no-store"
    resolution = resolve_for_request(request)
    result = await run_in_threadpool(run_connection_test, resolution, gate=_gate_for(request))
    return AiConnectionTestResponse(
        outcome=result.outcome,
        tested=result.tested,
        message=result.message,
        retry_after_seconds=result.retry_after_seconds,
    )
