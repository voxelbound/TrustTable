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

A durable `SqlAnalysisStore` (`DB-01`) is held on
`app.state.analysis_store`, created once per `FastAPI` application
instance in `main.create_app()` — every route below reaches it only
through `AnalysisStoreProtocol`, never the concrete class, so this
module is unaffected by which store implementation is actually wired in.

A bounded `JobPool` (`JOB-01`, `WP-075`) is held on
`app.state.job_pool`. `POST /demo/sales` and `POST /analyses` create the
analysis and submit it to the pool, returning immediately with
`state=queued` — the real pipeline runs on a background worker thread,
genuinely honoring the already-documented `202 Accepted`/poll-`status_url`
contract (`docs/api-specification.md` §5/§6) for the first time.
`POST .../cancel` requests cooperative cancellation for any non-terminal
analysis, not only `queued` — see `get_job_pool`/`post_analysis_cancel`
below and `jobs/pool.py`'s own race-avoidance disclosure. The retry
endpoint (`docs/api-specification.md`'s `POST .../retry`) remains a
disclosed, separate follow-up (`JOB-01` is not yet fully delivered).
"""

from __future__ import annotations

from fastapi import APIRouter, Query, Request, UploadFile

from trusttable_backend.ai_provider.display import describe_provenance, sanitize_model_identifier
from trusttable_backend.ai_provider.factory import create_provider
from trusttable_backend.analysis import (
    Analysis,
    AnalysisFailure,
    AnalysisNotFoundError,
    AnalysisNotReadyError,
    AnalysisState,
    AnalysisStoreProtocol,
    ContextFieldNotEditableError,
    ContextVersionConflictError,
    FindingNotFoundError,
    QuestionNotFoundError,
    RowNotInFindingError,
    answer_guided_question,
    apply_ai_context_augmentation,
    confirm_context_fields,
    create_analysis,
    create_analysis_from_upload,
    finalize_context,
    get_finding,
    get_finding_evidence,
    get_finding_row_context,
    get_guided_questions,
    get_or_infer_context,
    get_status,
)
from trusttable_backend.config import get_settings
from trusttable_backend.context_inference.ai_context import (
    build_context_inference_envelope,
    combine_hypotheses,
    run_context_inference,
)
from trusttable_backend.context_inference.heuristics import (
    consolidate_dataset_context,
    infer_context_hypotheses,
)
from trusttable_backend.detectors.contract import FindingCandidate, SecurityExposureState
from trusttable_backend.domain.clarification import ClarificationAnswer, ClarificationQuestion
from trusttable_backend.domain.context import ContextField, ContextFieldValue, DatasetContext
from trusttable_backend.domain.evidence import Evidence
from trusttable_backend.domain.explanation import FindingExplanation
from trusttable_backend.domain.parsing import Dataset
from trusttable_backend.domain.row_context import RowContextWindow
from trusttable_backend.domain.value_objects import ColumnReference
from trusttable_backend.errors import AppError
from trusttable_backend.explanation.ai_explanation import (
    build_finding_explanation_envelope,
    confirmed_context_for_finding_analysis,
    run_finding_explanation,
)
from trusttable_backend.explanation.deterministic import build_deterministic_explanation
from trusttable_backend.jobs import JobPool
from trusttable_backend.profiling.schemas import ColumnProfile, DatasetProfile, ProfilingWarning
from trusttable_backend.risk.scoring import TrustAssessment
from trusttable_backend.schemas.analysis import (
    AiProvenanceResponse,
    AnalysisFailureResponse,
    AnalysisProfileResponse,
    AnalysisResource,
    AnalysisStatusResponse,
    AnswerGuidedQuestionRequest,
    AnswerGuidedQuestionResponse,
    BusinessImpactStatementResponse,
    ClarificationAnswerResponse,
    ClarificationQuestionListResponse,
    ClarificationQuestionResponse,
    ColumnProfileResponse,
    ColumnReferenceResponse,
    ConfirmContextFieldsRequest,
    ContextFieldValueResponse,
    ContextResponse,
    DatasetSummaryResponse,
    DemoAnalysisResponse,
    FinalizeContextRequest,
    FindingDetailResponse,
    FindingEvidenceItem,
    FindingEvidenceListResponse,
    FindingExplanationResponse,
    FindingItem,
    FindingsListResponse,
    ProfilingTimingResponse,
    ProposedValidationRuleResponse,
    RowContextEntryResponse,
    RowContextResponse,
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


def get_analysis_store(request: Request) -> AnalysisStoreProtocol:
    """Return the current app's durable `SqlAnalysisStore`
    (`main.create_app` creates exactly one per application instance).
    """
    store: AnalysisStoreProtocol = request.app.state.analysis_store
    return store


def get_job_pool(request: Request) -> JobPool:
    """Return the current app's bounded `JobPool` (`JOB-01`, `WP-075`;
    `main.create_app` creates exactly one per application instance).
    """
    job_pool: JobPool = request.app.state.job_pool
    return job_pool


def _not_found(analysis_id: str) -> AppError:
    return AppError(
        "ANALYSIS_NOT_FOUND",
        "The requested analysis was not found.",
        status_code=404,
        details={"analysis_id": analysis_id},
    )


def _get_or_404(store: AnalysisStoreProtocol, analysis_id: str) -> Analysis:
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
    store: AnalysisStoreProtocol, analysis_id: str, finding_id: str
) -> FindingCandidate:
    try:
        return get_finding(store, analysis_id, finding_id)
    except AnalysisNotFoundError as exc:
        raise _not_found(analysis_id) from exc
    except FindingNotFoundError as exc:
        raise _finding_not_found(analysis_id, finding_id) from exc


def _row_not_in_finding(analysis_id: str, finding_id: str, anchor_row: int) -> AppError:
    return AppError(
        "ROW_NOT_IN_FINDING",
        "The requested row is not one of this finding's own affected rows.",
        status_code=404,
        details={"analysis_id": analysis_id, "finding_id": finding_id, "anchor_row": anchor_row},
    )


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


#: Every state `run_analysis` (`JOB-01`, `WP-075`) can still transition
#: out of — cooperative cancellation is meaningful for any of these, not
#: only `queued` (widened from the pre-`JOB-01` queued-only behavior).
_NON_TERMINAL_STATES = frozenset(
    {
        AnalysisState.QUEUED,
        AnalysisState.VALIDATING,
        AnalysisState.PARSING,
        AnalysisState.PROFILING,
        AnalysisState.DETECTING,
    }
)


def _analysis_status(analysis: Analysis) -> AnalysisStatusResponse:
    return AnalysisStatusResponse(
        analysis_id=analysis.analysis_id,
        state=analysis.state.value,
        message=_STATUS_MESSAGES[analysis.state],
        cancellable=analysis.state in _NON_TERMINAL_STATES,
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
        affected_row_numbers=sorted(
            reference.row_number for reference in finding.affected_row_references
        ),
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


def _row_context_response(window: RowContextWindow) -> RowContextResponse:
    return RowContextResponse(
        columns=[_column_reference(column) for column in window.columns],
        requested_before=window.requested_before,
        requested_after=window.requested_after,
        actual_before=window.actual_before,
        actual_after=window.actual_after,
        truncated_at_start=window.truncated_at_start,
        truncated_at_end=window.truncated_at_end,
        max_window=window.max_window,
        rows=[
            RowContextEntryResponse(
                row_number=entry.row_reference.row_number,
                is_anchor=entry.is_anchor,
                is_affected_by_finding=entry.is_affected_by_finding,
                values=list(entry.values),
            )
            for entry in window.rows
        ],
    )


def _finding_explanation_response(
    finding_id: str,
    explanation: FindingExplanation,
    *,
    ai_call_status: str,
    evidence_sent_to_model: bool,
    confirmed_context_sent_to_model: bool,
) -> FindingExplanationResponse:
    ai_provenance: AiProvenanceResponse | None = None
    if explanation.provider_name is not None:
        display = describe_provenance(explanation.provider_name, explanation.model_identifier)
        ai_provenance = AiProvenanceResponse(
            deployment_label=display.deployment_label,
            runtime_label=display.runtime_label,
            model_label=display.model_label,
            quantization=display.quantization,
            model_identifier=display.model_identifier,
        )
    rule = explanation.validation_rule
    return FindingExplanationResponse(
        finding_id=finding_id,
        narrative=explanation.narrative,
        provenance=explanation.provenance.value,
        provider_name=explanation.provider_name,
        # `AI-08`: the raw configured value (often an absolute model path)
        # never leaves the backend; only the sanitized identifier does.
        model_identifier=sanitize_model_identifier(explanation.model_identifier),
        ai_provenance=ai_provenance,
        ai_call_status=ai_call_status,
        evidence_sent_to_model=evidence_sent_to_model,
        confirmed_context_sent_to_model=confirmed_context_sent_to_model,
        referenced_evidence_ids=list(explanation.referenced_evidence_ids),
        referenced_columns=[_column_reference(column) for column in explanation.referenced_columns],
        business_impact=[
            BusinessImpactStatementResponse(
                statement=item.statement,
                basis=item.basis.value,
                evidence_ids=list(item.evidence_ids),
                context_fields=list(item.context_fields),
                assumption=item.assumption,
            )
            for item in explanation.business_impact
        ],
        remediation=list(explanation.remediation),
        validation_rule=(
            ProposedValidationRuleResponse(
                rule_type=rule.rule_type.value,
                columns=[_column_reference(column) for column in rule.columns],
                description=rule.description,
                status="proposed",
            )
            if rule is not None
            else None
        ),
    )


@router.get(
    "/analyses/{analysis_id}/findings/{finding_id}/explanation",
    response_model=FindingExplanationResponse,
)
def get_analysis_finding_explanation(
    analysis_id: str, finding_id: str, request: Request
) -> FindingExplanationResponse:
    """Return one finding's grounded explanation (`UI-02` slice 1,
    `WP-063`; confirmed-context grounding added `UI-02` slice 2 revision,
    `WP-064` r2; `docs/decision-log.md` D-037).

    Always computes `AI-05`'s deterministic explanation first (no
    provider call, always available — `docs/product-requirements.md`
    §5.7). When `Settings.llm_provider != "disabled"` (the default
    remains `"disabled"`, so this is a zero-behavior-change addition for
    any deployment that has not explicitly configured a provider),
    additionally attempts the validated AI path through the real
    provider factory; the deterministic explanation is returned
    unchanged on rejection or provider error — the same graceful-
    degradation contract `AI-05`'s own tests already proved, now applied
    to a real HTTP response.

    When the analysis's context has been finalized (`Analysis.
    context_finalized`, via `POST .../finalize`), the fields the user
    *confirmed or corrected* are serialized into the AI envelope's
    `confirmed_context` field, grounding the analysis in confirmed
    business facts (domain, row grain, currency behavior, etc.) in
    addition to the finding's own evidence — D-037's "confirmed/
    finalized context available to the explanation/enrichment path"
    requirement. **`AI-08`:** inferred and unknown fields are never sent,
    so an inferred value cannot reach the model — or the user — labelled
    as confirmed. Deliberately gated on `context_finalized` rather than
    merely `context is not None`: this is what makes `POST .../finalize`
    a meaningful, observable action rather than a no-op flag flip.
    Before finalize, this route's behavior is unchanged from `WP-063`
    (evidence-grounded only).

    **`AI-08` — the four sections.** The response always carries an
    explanation, business impact, remediation and a proposed validation
    rule. With AI disabled, rejected or failing they come from the
    deterministic built-in guidance (`explanation.guidance`); an accepted
    structured AI response replaces all four together. The response never
    carries the raw configured model value — only a sanitized identifier
    and human-readable `ai_provenance` labels (`ai_provider.display`).

    Also returns `ai_call_status` (`WP-065`, defect fix), this
    request's own independent AI-call disclosure — deliberately
    distinct from `provenance` alone (which cannot distinguish "no
    provider configured" from "a provider was tried and failed") and
    from `Analysis.security_exposure` (the deterministic pipeline's own,
    unrelated, permanently-`False` raw-sample-exposure posture; see
    `docs/decision-log.md` D-038).

    Also returns `evidence_sent_to_model`/`confirmed_context_sent_to_model`
    (`WP-065` r4, closing a semantic-review `FAIL`) — D-038's axis 5
    ("finding/evidence/context metadata exposure"), independent of
    `ai_call_status` (axes 1-3) and `Analysis.security_exposure`
    (axis 4, raw dataset-sample exposure — never carried here regardless
    of these two fields' values).

    Same `ANALYSIS_NOT_FOUND`/`FINDING_NOT_FOUND` semantics as the
    sibling finding routes.
    """
    store = get_analysis_store(request)
    analysis = _get_or_404(store, analysis_id)
    finding = _get_finding_or_404(store, analysis_id, finding_id)
    evidence = get_finding_evidence(store, analysis_id, finding_id)
    explanation = build_deterministic_explanation(finding)
    ai_call_status = "not_configured"
    evidence_sent_to_model = False
    confirmed_context_sent_to_model = False

    settings = get_settings()
    if settings.llm_provider != "disabled":
        # `AI-08`: only user-confirmed/corrected fields, and only once the
        # context is finalized. Inferred or unknown fields are never sent.
        confirmed_context = confirmed_context_for_finding_analysis(
            analysis.context, finalized=analysis.context_finalized
        )
        # The AI path is an optional enrichment: whatever goes wrong on it —
        # a misconfigured provider (an empty `LLM_MODEL`, a malformed base
        # URL) or anything unexpected — the deterministic four sections are
        # still returned with a truthful status, never a 500 that removes
        # them. Nothing about the failure is echoed or logged.
        ai_call_status = "attempted_provider_error"
        try:
            provider = create_provider(
                settings.llm_provider,
                base_url=settings.llm_base_url,
                model_identifier=settings.llm_model,
                timeout_seconds=float(settings.llm_timeout_seconds),
            )
            envelope = build_finding_explanation_envelope(
                finding, evidence, confirmed_context=confirmed_context
            )
        except Exception:
            # Nothing was built or sent.
            pass
        else:
            # Conservative from here on: a request may have been made.
            evidence_sent_to_model = True
            confirmed_context_sent_to_model = confirmed_context is not None
            try:
                result = run_finding_explanation(provider, envelope, evidence)
            except Exception:
                pass
            else:
                if result.accepted and result.explanation is not None:
                    explanation = result.explanation
                    ai_call_status = "attempted_accepted"
                elif result.provider_error is not None:
                    ai_call_status = "attempted_provider_error"
                else:
                    ai_call_status = "attempted_rejected"

    return _finding_explanation_response(
        finding_id,
        explanation,
        ai_call_status=ai_call_status,
        evidence_sent_to_model=evidence_sent_to_model,
        confirmed_context_sent_to_model=confirmed_context_sent_to_model,
    )


# --- Context confirmation (`API-02`, `UI-02` slice 2, `WP-064`) --------


def _analysis_not_ready(analysis_id: str, state: AnalysisState) -> AppError:
    return AppError(
        "INVALID_ANALYSIS_STATE",
        "Context is not available for this analysis in its current state.",
        status_code=409,
        details={"analysis_id": analysis_id, "state": state.value},
    )


def _context_version_conflict(exc: ContextVersionConflictError) -> AppError:
    return AppError(
        "CONTEXT_VERSION_CONFLICT",
        "The supplied context version is out of date.",
        status_code=409,
        details={
            "analysis_id": exc.analysis_id,
            "expected_version": exc.expected_version,
            "actual_version": exc.actual_version,
        },
    )


def _invalid_context(analysis_id: str, message: str, *, field: str | None = None) -> AppError:
    details: dict[str, object] = {"analysis_id": analysis_id}
    if field is not None:
        details["context_field"] = field
    return AppError("INVALID_CONTEXT", message, status_code=422, details=details)


def _question_not_found(analysis_id: str, question_id: str) -> AppError:
    return AppError(
        "QUESTION_NOT_FOUND",
        "The requested guided question was not found.",
        status_code=404,
        details={"analysis_id": analysis_id, "question_id": question_id},
    )


def _context_field_value(field_value: ContextFieldValue) -> ContextFieldValueResponse:
    value = field_value.value
    return ContextFieldValueResponse(
        value=list(value) if isinstance(value, tuple) else value,
        confidence=field_value.confidence,
        inference_source=field_value.inference_source.value,
        confirmation_state=field_value.confirmation_state.value,
        evidence_ids=list(field_value.evidence_ids),
    )


def _context_response(context_version: int, context: DatasetContext) -> ContextResponse:
    return ContextResponse(
        context_version=context_version,
        schema_version=context.schema_version,
        probable_domain=_context_field_value(context.probable_domain),
        row_grain=_context_field_value(context.row_grain),
        primary_entity=_context_field_value(context.primary_entity),
        candidate_keys=_context_field_value(context.candidate_keys),
        business_dates=_context_field_value(context.business_dates),
        measure_roles=_context_field_value(context.measure_roles),
        dimensions=_context_field_value(context.dimensions),
        currency_behavior=_context_field_value(context.currency_behavior),
        expected_business_rules=_context_field_value(context.expected_business_rules),
    )


def _clarification_question(question: ClarificationQuestion) -> ClarificationQuestionResponse:
    return ClarificationQuestionResponse(
        question_id=question.question_id,
        context_field=question.context_field.value,
        concise_text=question.concise_text,
        explanation=question.explanation,
        suggested_answers=list(question.suggested_answers),
        inferred_default=question.inferred_default,
        affected_assumptions=list(question.affected_assumptions),
        free_text_allowed=question.free_text_allowed,
        answered_state=question.answered_state.value,
    )


def _clarification_answer(answer: ClarificationAnswer) -> ClarificationAnswerResponse:
    return ClarificationAnswerResponse(
        question_id=answer.question_id,
        selected_answer_or_free_text=answer.selected_answer_or_free_text,
        answered_timestamp=answer.answered_timestamp,
        resulting_context_changes=[field.value for field in answer.resulting_context_changes],
        provenance=answer.provenance.value,
    )


@router.get("/analyses/{analysis_id}/context", response_model=ContextResponse)
def get_analysis_context(analysis_id: str, request: Request) -> ContextResponse:
    """Return `analysis_id`'s dataset context, inferring it on first
    call (`API-02`, `UI-02` slice 2; `docs/api-specification.md` §9's
    `GET .../context`).

    CTX-02 wiring (`UI-02` slice 2 revision, `WP-064` r2; `docs/
    decision-log.md` D-037's "configured AI context inference can
    participate in the Context flow" requirement): only when this
    analysis's context did not exist yet **before** this call
    (`analysis.context is None`, captured before `get_or_infer_context`
    runs — the true "very first call" signal, not `context_version`,
    which never changes again once augmented) and only when
    `Settings.llm_provider != "disabled"`, additionally calls the real
    provider through `context_inference.ai_context.
    run_context_inference`, combines an accepted AI-sourced
    `probable_domain` hypothesis with the deterministic hypothesis set
    via `combine_hypotheses`/`consolidate_dataset_context` (the same
    consolidation `CTX-02`'s own tests already proved), and persists the
    augmented context via `apply_ai_context_augmentation` — never
    incrementing `context_version` (this refines the first-inference
    snapshot, it is not a user edit). On rejection or provider error,
    the deterministic-only context from `get_or_infer_context` is
    returned unchanged — the same graceful-degradation contract used
    throughout this codebase. Every subsequent call for the same
    analysis (context already existed before this call) skips the AI
    call entirely and returns the already-cached context — a real
    provider is never called more than once per analysis by this route.

    Raises `ANALYSIS_NOT_FOUND` (404) for an unknown ID and
    `INVALID_ANALYSIS_STATE` (409) for a known but not-yet-`completed`
    analysis.
    """
    store = get_analysis_store(request)
    analysis = _get_or_404(store, analysis_id)
    is_first_inference = analysis.context is None
    try:
        context = get_or_infer_context(store, analysis_id)
    except AnalysisNotReadyError as exc:
        raise _analysis_not_ready(analysis_id, analysis.state) from exc
    updated = get_status(store, analysis_id)

    settings = get_settings()
    if settings.llm_provider != "disabled" and is_first_inference:
        assert updated.dataset_profile is not None  # guaranteed by COMPLETED invariant
        # Optional enrichment: a misconfigured or misbehaving provider must
        # leave the deterministic context in place, never fail the request.
        try:
            provider = create_provider(
                settings.llm_provider,
                base_url=settings.llm_base_url,
                model_identifier=settings.llm_model,
                timeout_seconds=float(settings.llm_timeout_seconds),
            )
            envelope = build_context_inference_envelope(context, evidence=updated.evidence)
            ai_result = run_context_inference(provider, envelope)
        except Exception:
            ai_result = None
        if ai_result is not None and ai_result.accepted and ai_result.hypothesis is not None:
            deterministic_hypotheses = infer_context_hypotheses(updated.dataset_profile)
            combined = combine_hypotheses(deterministic_hypotheses, ai_result)
            context = consolidate_dataset_context(combined)
            apply_ai_context_augmentation(store, analysis_id, context)
            updated = get_status(store, analysis_id)

    return _context_response(updated.context_version, context)


@router.put("/analyses/{analysis_id}/context", response_model=ContextResponse)
def put_analysis_context(
    analysis_id: str, body: ConfirmContextFieldsRequest, request: Request
) -> ContextResponse:
    """Replace one or more editable context field values
    (`API-02`, `UI-02` slice 2; `docs/api-specification.md` §9's
    `PUT .../context`, "requires resource version").

    Raises `ANALYSIS_NOT_FOUND`/`INVALID_ANALYSIS_STATE` (via
    `GET .../context`'s own semantics), `CONTEXT_VERSION_CONFLICT`
    (409) on a stale `expected_version`, and `INVALID_CONTEXT` (422)
    for an unknown field name or a non-editable role field.
    """
    store = get_analysis_store(request)
    analysis = _get_or_404(store, analysis_id)
    edits: dict[ContextField, str] = {}
    for key, value in body.edits.items():
        try:
            edits[ContextField(key)] = value
        except ValueError as exc:
            raise _invalid_context(
                analysis_id, f"Unknown context field: {key!r}", field=key
            ) from exc
    if not edits:
        raise _invalid_context(analysis_id, "At least one context field edit is required.")
    try:
        context = confirm_context_fields(
            store, analysis_id, edits, expected_version=body.expected_version
        )
    except AnalysisNotReadyError as exc:
        raise _analysis_not_ready(analysis_id, analysis.state) from exc
    except ContextVersionConflictError as exc:
        raise _context_version_conflict(exc) from exc
    except ContextFieldNotEditableError as exc:
        raise _invalid_context(
            analysis_id,
            f"Context field is not editable: {exc.context_field.value}",
            field=exc.context_field.value,
        ) from exc
    updated = get_status(store, analysis_id)
    return _context_response(updated.context_version, context)


@router.get("/analyses/{analysis_id}/questions", response_model=ClarificationQuestionListResponse)
def get_analysis_questions(analysis_id: str, request: Request) -> ClarificationQuestionListResponse:
    """Return `analysis_id`'s active guided questions (`API-02`, `UI-02`
    slice 2; `docs/api-specification.md` §9's `GET .../questions`).

    Same `ANALYSIS_NOT_FOUND`/`INVALID_ANALYSIS_STATE` semantics as
    `GET .../context`.
    """
    store = get_analysis_store(request)
    analysis = _get_or_404(store, analysis_id)
    try:
        questions = get_guided_questions(store, analysis_id)
    except AnalysisNotReadyError as exc:
        raise _analysis_not_ready(analysis_id, analysis.state) from exc
    items = [_clarification_question(question) for question in questions]
    return ClarificationQuestionListResponse(items=items, total_items=len(items))


@router.post(
    "/analyses/{analysis_id}/questions/{question_id}/answer",
    response_model=AnswerGuidedQuestionResponse,
)
def post_analysis_question_answer(
    analysis_id: str, question_id: str, body: AnswerGuidedQuestionRequest, request: Request
) -> AnswerGuidedQuestionResponse:
    """Store an answer to one guided question (`API-02`, `UI-02` slice 2;
    `docs/api-specification.md` §9's "stores an answer and resulting
    context updates").

    Raises `ANALYSIS_NOT_FOUND`/`INVALID_ANALYSIS_STATE` (via
    `GET .../context`'s own semantics), `CONTEXT_VERSION_CONFLICT`
    (409) on a stale `expected_version`, and `QUESTION_NOT_FOUND` (404)
    for an unknown `question_id`.
    """
    store = get_analysis_store(request)
    analysis = _get_or_404(store, analysis_id)
    try:
        context, question, answer = answer_guided_question(
            store,
            analysis_id,
            question_id,
            answer_text=body.answer_text,
            expected_version=body.expected_version,
        )
    except AnalysisNotReadyError as exc:
        raise _analysis_not_ready(analysis_id, analysis.state) from exc
    except ContextVersionConflictError as exc:
        raise _context_version_conflict(exc) from exc
    except QuestionNotFoundError as exc:
        raise _question_not_found(analysis_id, question_id) from exc
    updated = get_status(store, analysis_id)
    return AnswerGuidedQuestionResponse(
        context=_context_response(updated.context_version, context),
        question=_clarification_question(question),
        answer=_clarification_answer(answer),
    )


@router.post("/analyses/{analysis_id}/finalize", response_model=AnalysisResource, status_code=202)
def post_analysis_finalize(
    analysis_id: str, body: FinalizeContextRequest, request: Request
) -> AnalysisResource:
    """Mark `analysis_id`'s context finalized (`API-02`, `UI-02` slice 2;
    `docs/api-specification.md` §9's `POST .../finalize`).

    Does not change `context`/`guided_questions`/`context_version` or
    trigger any AI call — matches `analysis.service.finalize_context`'s
    own documented behavior exactly (`docs/decision-log.md` D-037: the
    reachable enrichment capability is the already-shipped on-demand
    explanation endpoint, not a forced side effect of finalize itself).

    Raises `ANALYSIS_NOT_FOUND`/`INVALID_ANALYSIS_STATE` (via
    `GET .../context`'s own semantics) and `CONTEXT_VERSION_CONFLICT`
    (409) on a stale `expected_version`.
    """
    store = get_analysis_store(request)
    analysis = _get_or_404(store, analysis_id)
    try:
        finalized = finalize_context(store, analysis_id, expected_version=body.expected_version)
    except AnalysisNotReadyError as exc:
        raise _analysis_not_ready(analysis_id, analysis.state) from exc
    except ContextVersionConflictError as exc:
        raise _context_version_conflict(exc) from exc
    return _analysis_resource(finalized)


@router.post("/analyses", response_model=UploadAnalysisResponse, status_code=202)
async def post_analysis_upload(file: UploadFile, request: Request) -> UploadAnalysisResponse:
    """Create an analysis from an uploaded CSV file and submit it to the
    background worker pool (`docs/api-specification.md` §6, disclosed
    CSV-only subset — `WP-029`; async submission, `JOB-01` `WP-075`).

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
    get_job_pool(request).submit(analysis.analysis_id)
    status_url = f"/api/v1/analyses/{analysis.analysis_id}/status"
    return UploadAnalysisResponse(analysis=_analysis_resource(analysis), status_url=status_url)


@router.post("/demo/sales", response_model=DemoAnalysisResponse, status_code=202)
def post_demo_sales(request: Request) -> DemoAnalysisResponse:
    """Create an analysis over the bundled demo dataset and submit it to
    the background worker pool (`docs/api-specification.md` §5, `JOB-01`
    `WP-075`). Returns immediately with `state=queued` — poll
    `status_url` (`GET .../status`) for progress.
    """
    store = get_analysis_store(request)
    analysis = create_analysis(store)
    get_job_pool(request).submit(analysis.analysis_id)
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


@router.get(
    "/analyses/{analysis_id}/findings/{finding_id}/row-context",
    response_model=RowContextResponse,
)
def get_analysis_finding_row_context(
    analysis_id: str,
    finding_id: str,
    request: Request,
    anchor_row: int = Query(...),
    before: int = Query(3, ge=0),
    after: int = Query(3, ge=0),
) -> RowContextResponse:
    """Return a bounded physical-neighborhood window around a finding's
    affected row (`FIND-01`, `WP-038`; `docs/api-specification.md` §10).

    Same `ANALYSIS_NOT_FOUND`/`FINDING_NOT_FOUND` semantics as
    `get_analysis_finding`. Raises `ROW_NOT_IN_FINDING` (404) when
    `anchor_row` is not one of the finding's own affected rows (including
    a finding with zero affected rows) — this endpoint reads context
    around a finding, not arbitrary rows in the file. `before`/`after`
    beyond the server's bounded maximum, or beyond the file's own start/
    end, are clamped rather than rejected — see the response's own
    `requested_*`/`actual_*`/`truncated_at_*` fields.
    """
    store = get_analysis_store(request)
    _get_finding_or_404(store, analysis_id, finding_id)
    try:
        window = get_finding_row_context(
            store, analysis_id, finding_id, anchor_row=anchor_row, before=before, after=after
        )
    except AnalysisNotFoundError as exc:
        raise _not_found(analysis_id) from exc
    except FindingNotFoundError as exc:
        raise _finding_not_found(analysis_id, finding_id) from exc
    except RowNotInFindingError as exc:
        raise _row_not_in_finding(analysis_id, finding_id, anchor_row) from exc
    return _row_context_response(window)


@router.post("/analyses/{analysis_id}/cancel", response_model=AnalysisResource)
def post_analysis_cancel(analysis_id: str, request: Request) -> AnalysisResource:
    """Request cancellation of a queued or actively-running analysis
    (`docs/api-specification.md` §6; real mid-pipeline cancellation,
    `JOB-01` `WP-075`).

    Cooperative, not synchronous: for any non-terminal analysis, this
    only ever sets a flag `JobPool`'s own worker thread observes at its
    next stage checkpoint (never a direct store write from this route —
    see `jobs/pool.py`'s own race-avoidance disclosure). The response
    reflects the analysis's *current* state, which may still be
    non-terminal; poll `GET .../status` for the eventual `cancelled`
    outcome. A known but already-terminal analysis is returned
    unchanged, not an error.
    """
    store = get_analysis_store(request)
    analysis = _get_or_404(store, analysis_id)
    if analysis.state in _NON_TERMINAL_STATES:
        get_job_pool(request).request_cancel(analysis_id)
    return _analysis_resource(analysis)
