"""Export download routes (`EXP-01` slice 1): validated rules as JSON or
YAML (`docs/api-specification.md` §12)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request, Response

from trusttable_backend.analysis import AnalysisState
from trusttable_backend.api.v1.analyses import (
    _analysis_not_ready,
    _get_or_404,
    get_analysis_store,
)
from trusttable_backend.exports.rules_export import (
    build_rules_export,
    render_json,
    render_yaml,
)

router = APIRouter()


def _document(analysis_id: str, request: Request) -> dict[str, Any]:
    analysis = _get_or_404(get_analysis_store(request), analysis_id)
    if analysis.state is not AnalysisState.COMPLETED:
        raise _analysis_not_ready(analysis_id, analysis.state)
    return build_rules_export(analysis_id, tuple(analysis.rules))


def _download(body: str, media_type: str, filename: str) -> Response:
    return Response(
        content=body,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/analyses/{analysis_id}/exports/rules.json")
def get_rules_export_json(analysis_id: str, request: Request) -> Response:
    """Download the analysis's validated rules as JSON.

    Raises `ANALYSIS_NOT_FOUND` (404) and `INVALID_ANALYSIS_STATE` (409)
    for an analysis that is not `COMPLETED`.
    """
    document = _document(analysis_id, request)
    return _download(render_json(document), "application/json", f"rules-{analysis_id}.json")


@router.get("/analyses/{analysis_id}/exports/rules.yaml")
def get_rules_export_yaml(analysis_id: str, request: Request) -> Response:
    """Download the analysis's validated rules as YAML (same document as
    the JSON export).

    Raises `ANALYSIS_NOT_FOUND` (404) and `INVALID_ANALYSIS_STATE` (409)
    for an analysis that is not `COMPLETED`.
    """
    document = _document(analysis_id, request)
    return _download(render_yaml(document), "application/yaml", f"rules-{analysis_id}.yaml")
