"""Analysis HTTP routes (`API-01`), exposing `analysis.service`'s
in-memory orchestration engine (`WP-023` enabling slice) over `/api/v1`.
Extended with generic CSV upload (`POST /analyses`, `WP-029`).

Implements the six behaviors `docs/implementation-backlog.md#API-01`
names: create analysis, load demo (`POST /demo/sales`), status
(`GET .../status`), profile (`GET .../profile`), findings
(`GET .../findings`), and cancel (`POST .../cancel`) — plus generic
file-upload analysis creation (`POST /analyses`, CSV only). Route
handlers do not call any deterministic/AI logic directly — every request
delegates to `trusttable_backend.analysis.service`'s existing,
already-tested public functions (`docs/architecture.md` §3: "API routes
-> Application services").

The `AnalysisStore` is held on `app.state.analysis_store`, created once
per `FastAPI` application instance in `main.create_app()` — in-memory,
lost on process restart, no concurrency safety (`DB-01`/`JOB-01`, not yet
built; the same disclosed non-goal `WP-023` already recorded for the
store itself). Both `POST /demo/sales` and `POST /analyses` create *and*
run the pipeline synchronously within the same request-response cycle —
there is no background worker yet, so the returned analysis is typically
already `completed` (or `failed`) by the time the response is sent, not
`queued`. Still documented and returned as `202 Accepted` per
`docs/api-specification.md` §5/§6's response shape, since the
client-facing contract (poll `status_url`) remains forward-compatible
with a future real background-execution package.
"""

from __future__ import annotations

from fastapi import APIRouter, Request, UploadFile

from trusttable_backend.analysis import (
    Analysis,
    AnalysisFailure,
    AnalysisNotFoundError,
    AnalysisState,
    AnalysisStore,
    FindingNotFoundError,
    cancel_analysis,
    create_analysis,
    create_analysis_from_upload,
    get_finding,
    get_finding_evidence,
    get_status,
    run_analysis,
)
from trusttable_backend.config import get_settings
from trusttable_backend.detectors.contract import FindingCandidate, SecurityExposureState
from trusttable_backend.domain.evidence import Evidence
from trusttable_backend.domain.parsing import Dataset
from trusttable_backend.domain.value_objects import ColumnReference
from trusttable_backend.errors import AppError
from trusttable_backend.profiling.schemas import ColumnProfile, DatasetProfile, ProfilingWarning
from trusttable_backend.risk.scoring import TrustAssessment
from trusttable_backend.schemas.analysis import (
    AnalysisFailureResponse,
    AnalysisProfileResponse,
    AnalysisResource,
    AnalysisStatusResponse,
    ColumnProfileResponse,
    ColumnReferenceResponse,
    DatasetSummaryResponse,
    DemoAnalysisResponse,
    FindingDetailResponse,
    FindingEvidenceItem,
    FindingEvidenceListResponse,
    FindingItem,
    FindingsListResponse,
    ProfilingTimingResponse,
    SampleMetadataResponse,
    SecurityExposureResponse,
    TrustAssessmentResponse,
    UploadAnalysisResponse,
    WarningResponse,
)
from trusttable_backend.uploads import sanitize_filename

router = APIRouter(tags=["analyses"])

#: The only format this route accepts today (`docs/implementation-backlog.md`
#: splits XLSX out to `ING-03`, not yet built).
_SUPPORTED_UPLOAD_EXTENSION = ".csv"

#: Fixed, safe per-state polling message (`docs/api-specification.md` §6's
#: "current message"). Never derived from dataset content.
_STATUS_MESSAGES: dict[AnalysisState, str] = {
    AnalysisState.QUEUED: "Analysis is queued.",
    AnalysisState.VALIDATING: "Validating dataset.",
    AnalysisState.PARSING: "Parsing dataset.",
    AnalysisState.PROFILING: "Profiling dataset.",
    AnalysisState.DETECTING: "Running detectors.",
    AnalysisState.COMPLETED: "Analysis completed.",
    AnalysisState.FAILED: "Analysis failed.",
    AnalysisState.CANCELLED: "Analysis was cancelled.",
}
_POLL_INTERVAL_MS = 500


def get_analysis_store(request: Request) -> AnalysisStore:
    """Return the current app's in-memory `AnalysisStore`
    (`main.create_app` creates exactly one per application instance).
    """
    store: AnalysisStore = request.app.state.analysis_store
    return store


def _not_found(analysis_id: str) -> AppError:
    return AppError(
        "ANALYSIS_NOT_FOUND",
        "The requested analysis was not found.",
        status_code=404,
        details={"analysis_id": analysis_id},
    )


def _get_or_404(store: AnalysisStore, analysis_id: str) -> Analysis:
    try:
        return get_status(store, analysis_id)
    except AnalysisNotFoundError as exc:
        raise _not_found(analysis_id) from exc


def _finding_not_found(analysis_id: str, finding_id: str) -> AppError:
    return AppError(
        "FINDING_NOT_FOUND",
        "The requested finding was not found.",
        status_code=404,
        details={"analysis_id": analysis_id, "finding_id": finding_id},
    )


def _get_finding_or_404(
    store: AnalysisStore, analysis_id: str, finding_id: str
) -> FindingCandidate:
    try:
        return get_finding(store, analysis_id, finding_id)
    except AnalysisNotFoundError as exc:
        raise _not_found(analysis_id) from exc
    except FindingNotFoundError as exc:
        raise _finding_not_found(analysis_id, finding_id) from exc


def _column_reference(reference: ColumnReference) -> ColumnReferenceResponse:
    return ColumnReferenceResponse(
        original_name=reference.original_name,
        internal_key=reference.internal_key,
        ordinal=reference.ordinal,
    )


def _warning(warning: ProfilingWarning) -> WarningResponse:
    return WarningResponse(
        code=warning.code,
        message=warning.message,
        column=_column_reference(warning.column) if warning.column is not None else None,
    )


def _dataset_summary(dataset: Dataset) -> DatasetSummaryResponse:
    return DatasetSummaryResponse(
        dataset_id=dataset.dataset_id,
        original_filename=dataset.original_filename,
        format=dataset.format.value,
        byte_size=dataset.byte_size,
        content_hash=dataset.content_hash,
        source_type=dataset.source_type.value,
        created_at=dataset.created_at,
    )


def _security_exposure(exposure: SecurityExposureState) -> SecurityExposureResponse:
    return SecurityExposureResponse(
        model_provider_enabled=exposure.model_provider_enabled,
        sample_transmission_enabled=exposure.sample_transmission_enabled,
    )


def _trust_assessment(assessment: TrustAssessment | None) -> TrustAssessmentResponse | None:
    if assessment is None:
        return None
    return TrustAssessmentResponse(
        label=assessment.label.value,
        score=assessment.score,
        finding_count=assessment.finding_count,
        highest_priority_score=assessment.highest_priority_score,
    )


def _failure(failure: AnalysisFailure | None) -> AnalysisFailureResponse | None:
    if failure is None:
        return None
    return AnalysisFailureResponse(code=failure.code, message=failure.message)


def _analysis_resource(analysis: Analysis) -> AnalysisResource:
    return AnalysisResource(
        analysis_id=analysis.analysis_id,
        state=analysis.state.value,
        dataset=_dataset_summary(analysis.dataset),
        security_exposure=_security_exposure(analysis.security_exposure),
        trust_assessment=_trust_assessment(analysis.trust_assessment),
        finding_count=len(analysis.findings),
        failure=_failure(analysis.failure),
        created_at=analysis.created_at,
        started_at=analysis.started_at,
        completed_at=analysis.completed_at,
        failed_at=analysis.failed_at,
        cancelled_at=analysis.cancelled_at,
    )


def _analysis_status(analysis: Analysis) -> AnalysisStatusResponse:
    return AnalysisStatusResponse(
        analysis_id=analysis.analysis_id,
        state=analysis.state.value,
        message=_STATUS_MESSAGES[analysis.state],
        cancellable=analysis.state is AnalysisState.QUEUED,
        poll_interval_ms=_POLL_INTERVAL_MS,
    )


def _column_profile(profile: ColumnProfile) -> ColumnProfileResponse:
    return ColumnProfileResponse(
        column=_column_reference(profile.column),
        inferred_type=profile.inferred_type.value,
        null_count=profile.null_count,
        distinct_count=profile.distinct_count,
        metrics=dict(profile.metrics),
        warnings=[_warning(warning) for warning in profile.warnings],
    )


def _profile_response(profile: DatasetProfile) -> AnalysisProfileResponse:
    return AnalysisProfileResponse(
        schema_version=profile.schema_version,
        dataset_metrics=dict(profile.dataset_metrics),
        column_profiles=[_column_profile(entry) for entry in profile.column_profiles],
        sampling=SampleMetadataResponse(
            scope=profile.sampling.scope.value,
            population_size=profile.sampling.population_size,
            sample_size=profile.sampling.sample_size,
            method=profile.sampling.method,
        ),
        warnings=[_warning(warning) for warning in profile.warnings],
        timing=ProfilingTimingResponse(
            started_at=profile.timing.started_at,
            completed_at=profile.timing.completed_at,
            duration_ms=profile.timing.duration_ms,
        ),
    )


def _finding_item(finding: FindingCandidate, priority_score: float, finding_id: str) -> FindingItem:
    return FindingItem(
        finding_id=finding_id,
        detector_id=finding.detector_id,
        detector_version=finding.detector_version,
        category=finding.category.value,
        severity=finding.severity.value,
        confidence=finding.confidence,
        priority_score=priority_score,
        calculated_observation=finding.calculated_observation,
        affected_columns=[_column_reference(column) for column in finding.affected_columns],
        affected_row_count=len(finding.affected_row_references),
        evidence_count=len(finding.evidence_ids),
    )


def _finding_detail(
    finding: FindingCandidate,
    priority_score: float,
    finding_id: str,
    exposure: SecurityExposureState,
) -> FindingDetailResponse:
    return FindingDetailResponse(
        finding_id=finding_id,
        detector_id=finding.detector_id,
        detector_version=finding.detector_version,
        category=finding.category.value,
        severity=finding.severity.value,
        confidence=finding.confidence,
        priority_score=priority_score,
        calculated_observation=finding.calculated_observation,
        affected_columns=[_column_reference(column) for column in finding.affected_columns],
        affected_row_count=len(finding.affected_row_references),
        evidence_count=len(finding.evidence_ids),
        security_exposure=_security_exposure(exposure),
    )


def _evidence_item(evidence: Evidence) -> FindingEvidenceItem:
    return FindingEvidenceItem(
        evidence_id=evidence.evidence_id,
        evidence_type=evidence.evidence_type.value,
        display_safe_summary=evidence.display_safe_summary,
        affected_columns=[_column_reference(column) for column in evidence.affected_columns],
        affected_row_count=len(evidence.affected_row_references),
        scope=evidence.scope.value,
    )


@router.post("/analyses", response_model=UploadAnalysisResponse, status_code=202)
async def post_analysis_upload(file: UploadFile, request: Request) -> UploadAnalysisResponse:
    """Create an analysis from an uploaded CSV file and run it to
    completion (`docs/api-specification.md` §6, disclosed CSV-only
    subset — `WP-029`).

    Follows `docs/product-requirements.md` §8.2's ordered validation
    steps: filename required, `.csv` extension required, size bounded
    before full content is read, then filename sanitized before the
    analysis is created. `file: UploadFile` takes no `= File(...)`
    default — FastAPI already treats a required `UploadFile` annotation
    as a file-upload parameter, avoiding the `ruff` `B008`
    function-call-in-default-argument pattern `WP-024` already found and
    avoided for `Depends`.
    """
    original_name = file.filename
    if not original_name:
        # Defense in depth: `UploadFile.filename` is typed `str | None` and
        # can in principle be an empty string or `None` even when a `file`
        # part is present (a `Content-Disposition` with no/blank `filename`
        # parameter). A request with no `file` part at all never reaches
        # here — FastAPI's own required-parameter validation rejects it
        # first, via the app's existing `RequestValidationError` -> `422
        # INVALID_REQUEST` global handler (`FND-04`).
        raise AppError(
            "INVALID_REQUEST",
            "A filename is required.",
            status_code=400,
            details={},
        )
    if not original_name.lower().endswith(_SUPPORTED_UPLOAD_EXTENSION):
        raise AppError(
            "UNSUPPORTED_FILE_TYPE",
            "Only .csv files are currently supported.",
            status_code=415,
            details={
                "filename": sanitize_filename(original_name),
                "supported_extensions": [_SUPPORTED_UPLOAD_EXTENSION],
            },
        )

    max_bytes = get_settings().max_file_size_mb * 1024 * 1024
    # Bound the read itself so an oversized upload never fully enters
    # memory before being rejected (`docs/security-threat-model.md`
    # §3.1 "resource exhaustion").
    content = await file.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise AppError(
            "FILE_TOO_LARGE",
            "The uploaded file exceeds the maximum allowed size.",
            status_code=413,
            details={"max_bytes": max_bytes},
        )
    if not content:
        raise AppError(
            "INVALID_REQUEST",
            "The uploaded file is empty.",
            status_code=400,
            details={},
        )

    store = get_analysis_store(request)
    analysis = create_analysis_from_upload(
        store, content=content, original_filename=sanitize_filename(original_name)
    )
    analysis = run_analysis(store, analysis.analysis_id)
    status_url = f"/api/v1/analyses/{analysis.analysis_id}/status"
    return UploadAnalysisResponse(analysis=_analysis_resource(analysis), status_url=status_url)


@router.post("/demo/sales", response_model=DemoAnalysisResponse, status_code=202)
def post_demo_sales(request: Request) -> DemoAnalysisResponse:
    """Create an analysis over the bundled demo dataset and run it to
    completion (`docs/api-specification.md` §5).
    """
    store = get_analysis_store(request)
    analysis = create_analysis(store)
    analysis = run_analysis(store, analysis.analysis_id)
    status_url = f"/api/v1/analyses/{analysis.analysis_id}/status"
    return DemoAnalysisResponse(analysis=_analysis_resource(analysis), status_url=status_url)


@router.get("/analyses/{analysis_id}", response_model=AnalysisResource)
def get_analysis(analysis_id: str, request: Request) -> AnalysisResource:
    """Return the full analysis resource (`docs/api-specification.md` §6)."""
    analysis = _get_or_404(get_analysis_store(request), analysis_id)
    return _analysis_resource(analysis)


@router.get("/analyses/{analysis_id}/status", response_model=AnalysisStatusResponse)
def get_analysis_status(analysis_id: str, request: Request) -> AnalysisStatusResponse:
    """Lightweight polling endpoint (`docs/api-specification.md` §6)."""
    analysis = _get_or_404(get_analysis_store(request), analysis_id)
    return _analysis_status(analysis)


@router.get("/analyses/{analysis_id}/profile", response_model=AnalysisProfileResponse)
def get_analysis_profile(analysis_id: str, request: Request) -> AnalysisProfileResponse:
    """Return the dataset profile (`docs/api-specification.md` §8).

    Raises `INVALID_ANALYSIS_STATE` (`409`) when the analysis has not
    reached `completed` — matching `analysis.service.get_profile`'s own
    documented `None`-for-not-completed behavior, translated into an
    explicit HTTP error rather than a silently empty/null body.
    """
    analysis = _get_or_404(get_analysis_store(request), analysis_id)
    if analysis.dataset_profile is None:
        raise AppError(
            "INVALID_ANALYSIS_STATE",
            "The profile is not available for this analysis in its current state.",
            status_code=409,
            details={"analysis_id": analysis_id, "state": analysis.state.value},
        )
    return _profile_response(analysis.dataset_profile)


@router.get("/analyses/{analysis_id}/findings", response_model=FindingsListResponse)
def get_analysis_findings(analysis_id: str, request: Request) -> FindingsListResponse:
    """Return the findings list (`docs/api-specification.md` §10).

    Returns an empty `items` list (not an error) for a known,
    not-yet-`completed` analysis — matching
    `analysis.service.get_findings`'s own documented behavior exactly.
    """
    analysis = _get_or_404(get_analysis_store(request), analysis_id)
    items = [
        _finding_item(finding, priority_score, str(index))
        for index, (finding, priority_score) in enumerate(
            zip(analysis.findings, analysis.priority_scores, strict=True)
        )
    ]
    return FindingsListResponse(items=items, total_items=len(items))


@router.get("/analyses/{analysis_id}/findings/{finding_id}", response_model=FindingDetailResponse)
def get_analysis_finding(
    analysis_id: str, finding_id: str, request: Request
) -> FindingDetailResponse:
    """Return one finding's detail (`WP-027`, a disclosed bounded subset
    of `docs/api-specification.md` §10's full documented finding-detail
    shape — see `FindingDetailResponse`'s own docstring).

    Raises `ANALYSIS_NOT_FOUND` (404) for an unknown `analysis_id` and
    `FINDING_NOT_FOUND` (404) for an unknown/out-of-range `finding_id`,
    including a known analysis that has not yet reached `completed`.
    """
    store = get_analysis_store(request)
    analysis = _get_or_404(store, analysis_id)
    finding = _get_finding_or_404(store, analysis_id, finding_id)
    priority_score = analysis.priority_scores[int(finding_id)]
    return _finding_detail(finding, priority_score, finding_id, analysis.security_exposure)


@router.get(
    "/analyses/{analysis_id}/findings/{finding_id}/evidence",
    response_model=FindingEvidenceListResponse,
)
def get_analysis_finding_evidence(
    analysis_id: str, finding_id: str, request: Request
) -> FindingEvidenceListResponse:
    """Return one finding's bounded evidence (`WP-027`), each item's
    `display_safe_summary` only — never the raw `structured_payload`
    (see `FindingEvidenceItem`'s own docstring).

    Same not-found semantics as `get_analysis_finding`.
    """
    store = get_analysis_store(request)
    _get_finding_or_404(store, analysis_id, finding_id)
    evidence = get_finding_evidence(store, analysis_id, finding_id)
    items = [_evidence_item(item) for item in evidence]
    return FindingEvidenceListResponse(items=items, total_items=len(items))


@router.post("/analyses/{analysis_id}/cancel", response_model=AnalysisResource)
def post_analysis_cancel(analysis_id: str, request: Request) -> AnalysisResource:
    """Cancel a queued analysis (`docs/api-specification.md` §6).

    Only effective while `queued` — `analysis.service.cancel_analysis`'s
    own documented behavior (no true mid-pipeline cancellation yet,
    `JOB-01`); any other known state is returned unchanged, not an error.
    """
    store = get_analysis_store(request)
    try:
        analysis = cancel_analysis(store, analysis_id)
    except AnalysisNotFoundError as exc:
        raise _not_found(analysis_id) from exc
    return _analysis_resource(analysis)
