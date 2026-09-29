"""Report routes (`EXP-01` slice 3, `docs/api-specification.md` §12).

A report is rendered once, at `POST` time, and stored. `GET` and
`download` serve the stored snapshot; nothing here re-renders from live
analysis state, so a report never changes after creation.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Request, Response

from trusttable_backend.analysis import AnalysisState
from trusttable_backend.api.v1.analyses import (
    _analysis_not_ready,
    _get_or_404,
    _not_found,
    get_analysis_store,
)
from trusttable_backend.errors import AppError
from trusttable_backend.exports.report_service import ReportStoreProtocol, create_report_snapshot
from trusttable_backend.exports.report_snapshot import ReportOptions, ReportSnapshot
from trusttable_backend.schemas.report import (
    CreateReportRequest,
    ReportListResponse,
    ReportOptionsModel,
    ReportResponse,
)
from trusttable_backend.version_info import get_application_version

router = APIRouter(tags=["reports"])


def get_report_store(request: Request) -> ReportStoreProtocol:
    """Return the current app's durable `SqlReportStore`."""
    store: ReportStoreProtocol = request.app.state.report_store
    return store


def _report_not_found(analysis_id: str, report_id: str) -> AppError:
    return AppError(
        "REPORT_NOT_FOUND",
        "The requested report was not found.",
        status_code=404,
        details={"analysis_id": analysis_id, "report_id": report_id},
    )


def _response(snapshot: ReportSnapshot) -> ReportResponse:
    return ReportResponse(
        report_id=snapshot.report_id,
        analysis_id=snapshot.analysis_id,
        generated_at=snapshot.generated_at,
        options=ReportOptionsModel(
            include_dismissed=snapshot.options.include_dismissed,
            include_technical_appendix=snapshot.options.include_technical_appendix,
            include_bounded_examples=snapshot.options.include_bounded_examples,
        ),
        schema_version=snapshot.schema_version,
        content_sha256=snapshot.content_sha256,
    )


def _stored_or_404(request: Request, analysis_id: str, report_id: str) -> ReportSnapshot:
    _get_or_404(get_analysis_store(request), analysis_id)
    snapshot = get_report_store(request).get(analysis_id, report_id)
    if snapshot is None:
        raise _report_not_found(analysis_id, report_id)
    return snapshot


@router.post("/analyses/{analysis_id}/reports", status_code=201, response_model=ReportResponse)
def create_report(
    analysis_id: str, request: Request, body: CreateReportRequest | None = None
) -> ReportResponse:
    """Generate and store an immutable Markdown report snapshot.

    Raises `ANALYSIS_NOT_FOUND` (404) and `INVALID_ANALYSIS_STATE` (409)
    for an analysis that is not `COMPLETED`.
    """
    analysis = _get_or_404(get_analysis_store(request), analysis_id)
    if analysis.state is not AnalysisState.COMPLETED:
        raise _analysis_not_ready(analysis_id, analysis.state)
    chosen = (body or CreateReportRequest()).options
    snapshot = create_report_snapshot(
        analysis,
        options=ReportOptions(
            include_dismissed=chosen.include_dismissed,
            include_technical_appendix=chosen.include_technical_appendix,
            include_bounded_examples=chosen.include_bounded_examples,
        ),
        application_version=get_application_version(),
        report_id=uuid.uuid4().hex,
        generated_at=datetime.now(UTC),
    )
    if not get_report_store(request).add(snapshot):
        # Deleted between the check above and the insert (`DEL-01`).
        raise _not_found(analysis_id)
    return _response(snapshot)


@router.get("/analyses/{analysis_id}/reports", response_model=ReportListResponse)
def list_reports(analysis_id: str, request: Request) -> ReportListResponse:
    """List the analysis's generated reports in creation order."""
    _get_or_404(get_analysis_store(request), analysis_id)
    snapshots = get_report_store(request).list_for_analysis(analysis_id)
    return ReportListResponse(reports=[_response(snapshot) for snapshot in snapshots])


@router.get("/analyses/{analysis_id}/reports/{report_id}", response_model=ReportResponse)
def get_report(analysis_id: str, report_id: str, request: Request) -> ReportResponse:
    """Return one report's metadata."""
    return _response(_stored_or_404(request, analysis_id, report_id))


@router.get("/analyses/{analysis_id}/reports/{report_id}/download")
def download_report(analysis_id: str, report_id: str, request: Request) -> Response:
    """Download the stored Markdown exactly as it was rendered."""
    snapshot = _stored_or_404(request, analysis_id, report_id)
    return Response(
        content=snapshot.markdown.encode("utf-8"),
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="report-{analysis_id}-{report_id}.md"'
        },
    )
