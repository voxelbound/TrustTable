"""Pydantic response schemas for the analysis HTTP surface (`API-01`).

Covers the six behaviors `docs/implementation-backlog.md#API-01` names:
create analysis (`POST /demo/sales`), load demo (same endpoint), status
(`GET .../status`), profile (`GET .../profile`), findings
(`GET .../findings`), and cancel (`POST .../cancel`).

Deliberately narrower than `docs/api-specification.md`'s full documented
`/api/v1` surface (context, rules, reports, generic file upload,
pagination/filtering, the broader "AI status" resource) — that full
surface is the v1 target across many later, separate backlog items
(`CTX-*`, `RULE-*`, `EXP-*`, `DB-01`, `JOB-01`). This module's shapes are
an intentional, disclosed subset matching exactly the six behaviors
listed above, built directly on `trusttable_backend.analysis.service`'s
already-existing, already-tested dataclasses (`API-01` enabling slice,
`WP-023`).

Mapping from `analysis.service`'s frozen dataclasses to these response
models is done with explicit field-by-field constructor calls in
`api.v1.analyses` (not `model_validate(..., from_attributes=True)`) —
keeps the HTTP response shape decoupled from the internal dataclass shape
and avoids relying on Pydantic's nested-attribute-inference behavior.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel


class ColumnReferenceResponse(BaseModel):
    """Mirrors `domain.value_objects.ColumnReference`."""

    original_name: str
    internal_key: str
    ordinal: int


class WarningResponse(BaseModel):
    """Mirrors the shared shape of `domain.parsing.ParsingWarning`,
    `profiling.schemas.ProfilingWarning`, and `detectors.contract.DetectorWarning`
    (namespaced `code`, `message`, optional column reference).
    """

    code: str
    message: str
    column: ColumnReferenceResponse | None = None


class DatasetSummaryResponse(BaseModel):
    """A bounded summary of `domain.parsing.Dataset` — omits
    `stored_filename`/`storage_location`/`deleted_at`, which are
    internal storage facts. `selected_worksheet` (`ING-03`) is the name of
    the worksheet an `xlsx` analysis was run over, and is `None` for CSV.
    """

    dataset_id: str
    original_filename: str
    format: str
    byte_size: int
    content_hash: str
    source_type: str
    created_at: datetime
    selected_worksheet: str | None = None


class SecurityExposureResponse(BaseModel):
    """Mirrors `detectors.contract.SecurityExposureState` exactly —
    see that class's own docstring for the full scope boundary
    (`WP-065`, defect fix; `docs/decision-log.md` D-038). Always reports
    the disabled/no-transmission state today: not because no AI/LLM
    provider exists (`AI-01`/`AI-02`/`AI-03` are all real and can be
    configured), but because this field describes only the
    deterministic detection pipeline's own raw-sample-exposure posture,
    which never sends dataset content to a model. It is deliberately
    independent of, and must never be conflated with, a separate,
    optional, per-request AI enrichment call's own status (see
    `FindingExplanationResponse.ai_call_status`).
    """

    model_provider_enabled: bool
    sample_transmission_enabled: bool


class AnalysisFailureResponse(BaseModel):
    """Mirrors `analysis.service.AnalysisFailure` — a fixed, safe,
    non-leaking failure description. Never contains raw exception text.
    """

    code: str
    message: str


class TrustAssessmentResponse(BaseModel):
    """Mirrors `risk.scoring.TrustAssessment`."""

    label: str
    score: float
    finding_count: int
    highest_priority_score: float | None


class AnalysisResource(BaseModel):
    """Body for `GET /analyses/{analysis_id}`, `POST .../cancel`, and the
    `analysis` field of `POST /demo/sales`'s response
    (`docs/api-specification.md` §6's documented "metadata, state,
    dataset summary, timestamps, failure details" shape, narrowed to
    what `API-01`'s in-memory engine actually tracks).

    `finding_count` is a convenience summary count; the full findings
    list is served separately by `GET .../findings` (`docs/
    api-specification.md`'s own list-endpoint-separation convention).
    """

    analysis_id: str
    state: str
    dataset: DatasetSummaryResponse
    security_exposure: SecurityExposureResponse
    trust_assessment: TrustAssessmentResponse | None
    finding_count: int
    failure: AnalysisFailureResponse | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    failed_at: datetime | None
    cancelled_at: datetime | None
    retry_source_analysis_id: str | None = None


class DemoAnalysisResponse(BaseModel):
    """Body for `POST /demo/sales` (`docs/api-specification.md` §5:
    "analysis resource" + "status URL").
    """

    analysis: AnalysisResource
    status_url: str


class UploadAnalysisResponse(BaseModel):
    """Body for `POST /analyses` (`WP-029`; `docs/api-specification.md`
    §6's disclosed subset: "analysis resource" + "status URL" — the
    same shape as `DemoAnalysisResponse`, kept as its own type for a
    distinct generated client function name).
    """

    analysis: AnalysisResource
    status_url: str


class RetryAnalysisResponse(BaseModel):
    """Body for `POST /analyses/{analysis_id}/retry` (`JOB-01` slice 2,
    `WP-076`; `docs/api-specification.md` §6: "202 Accepted, new attempt
    ID or updated attempt resource"), resolved as a new, independent
    `Analysis` — `analysis.analysis_id` is the "new attempt ID";
    `retry_source_analysis_id` echoes the original analysis that was
    retried, for a client that only has the response body (also visible
    via `AnalysisResource.retry_source_analysis_id` on any later `GET`).
    """

    analysis: AnalysisResource
    status_url: str
    retry_source_analysis_id: str


class AnalysisStatusResponse(BaseModel):
    """Body for `GET /analyses/{analysis_id}/status` — a lightweight
    polling endpoint (`docs/api-specification.md` §6).

    `state` now reflects real, persisted stage progression
    (`queued`/`parsing`/`profiling`/`detecting`/terminal — `JOB-01`,
    `WP-075`: a bounded worker pool runs the pipeline in the background
    instead of synchronously inside the request). `poll_interval_ms`
    stays a fixed constant regardless (no adaptive backoff has been
    built). `retryable` is `true` if and only if `state` is `failed`
    (`JOB-01` slice 2, `WP-076`: `POST .../retry` exists now, restricted
    to `FAILED` per `docs/product-requirements.md`'s "retry failed
    work"). A numeric `progress_percentage` remains deliberately
    omitted: there is no meaningful sub-stage partial-progress signal
    within one stage — a disclosed, permanent non-goal, not a follow-up
    slice.
    """

    analysis_id: str
    state: str
    message: str
    cancellable: bool
    retryable: bool
    poll_interval_ms: int


class CompletenessResponse(BaseModel):
    """Missing values across the profiled cells (`UX-04`, D-070).

    `scope` is `"full"` or `"sampled"` as the profile recorded it, so the
    interface never states a sampled figure as if it covered every row.
    `missing_share` is `null` when there are no cells to measure.
    """

    scope: Literal["full", "sampled"]
    population_size: int
    sample_size: int
    cells_total: int
    cells_missing: int
    missing_share: float | None


class AnalysisSummaryResponse(BaseModel):
    """Body for `GET /analyses/{analysis_id}/summary` (`UX-04`, D-070).

    Counts only: no cell value, no row-number list and no content hash.
    `rows_affected` is the number of *distinct* rows that at least one finding
    points at; `findings_without_row_detail` is how many findings name no row
    (for example a whole-column finding), so rows affected is never read as
    "every other row is clean".
    """

    analysis_id: str
    row_count: int
    column_count: int
    rows_affected: int
    findings_total: int
    findings_without_row_detail: int
    completeness: CompletenessResponse


class SampleMetadataResponse(BaseModel):
    """Mirrors `domain.parsing.SampleMetadata`."""

    scope: str
    population_size: int
    sample_size: int
    method: str | None


class ProfilingTimingResponse(BaseModel):
    """Mirrors `profiling.schemas.ProfilingTiming`."""

    started_at: datetime
    completed_at: datetime
    duration_ms: int


class ColumnProfileResponse(BaseModel):
    """Mirrors `profiling.schemas.ColumnProfile`.

    `metrics` values are already JSON-safe primitives (str/int/float/
    bool/None; e.g. date metrics are pre-formatted `.isoformat()`
    strings) — `PROF-03`'s own established convention, reused unchanged.
    """

    column: ColumnReferenceResponse
    inferred_type: str
    null_count: int
    distinct_count: int
    metrics: dict[str, Any]
    warnings: list[WarningResponse]


class AnalysisProfileResponse(BaseModel):
    """Body for `GET /analyses/{analysis_id}/profile`, mirroring
    `profiling.schemas.DatasetProfile` (`docs/api-specification.md` §8).

    Deliberately omits §8's documented "include technical metrics" /
    column paging / column-filter query options and the large
    representative-value payload exclusion — this package returns the
    full profile every time; filtering/paging is deferred to a later,
    separate package once a real need is demonstrated (disclosed
    Non-goal, not a silent omission).
    """

    schema_version: str
    dataset_metrics: dict[str, Any]
    column_profiles: list[ColumnProfileResponse]
    sampling: SampleMetadataResponse
    warnings: list[WarningResponse]
    timing: ProfilingTimingResponse


class FindingItem(BaseModel):
    """One entry in `GET /analyses/{analysis_id}/findings`'s response
    (`docs/api-specification.md` §10's documented list-item shape,
    narrowed to what `API-01`'s `FindingCandidate` actually carries).

    `finding_id` (`WP-027`) is a stringified zero-based index into the
    analysis's own findings tuple — a disclosed, reversible interim
    scheme (see `analysis.service.get_finding`); no full persisted
    identifier exists yet. `review_state`/`note`/`dismissal_reason`/
    `reviewed_at` (`REV-01`, `WP-083`) default to `"unreviewed"`/`null`/
    `null`/`null` for a finding with no recorded review.
    `affected_row_count` and `evidence_count` are bounded counts, not the
    raw row-reference/evidence-ID lists — matching this repository's
    established "bounded, not raw" list-response convention (`PROF-03`'s
    profile endpoint precedent above).
    """

    finding_id: str
    detector_id: str
    detector_version: str
    category: str
    severity: str
    confidence: float
    priority_score: float
    calculated_observation: str
    affected_columns: list[ColumnReferenceResponse]
    affected_row_count: int
    evidence_count: int
    review_state: str
    note: str | None
    dismissal_reason: str | None
    reviewed_at: datetime | None


class FindingsListResponse(BaseModel):
    """Body for `GET /analyses/{analysis_id}/findings`. Returns an empty
    `items` list (not an error) for a known, not-yet-`COMPLETED`
    analysis — matching `analysis.service.get_findings`'s own documented
    behavior exactly.
    """

    items: list[FindingItem]
    total_items: int


class FindingDetailResponse(BaseModel):
    """Body for `GET /analyses/{analysis_id}/findings/{finding_id}`
    (`WP-027`, a disclosed bounded subset of `docs/api-specification.md`
    §10's full documented finding-detail shape and
    `docs/ui-specification.md` §4.7's "Finding detail" screen sections).

    Exposes exactly what is genuinely computable today: observation,
    affected columns/rows, evidence count, technical metadata, security
    exposure, and (`REV-01`, `WP-083`) review state. Deliberately omits
    possible business impact, remediation, and proposed validation
    rules, which live in their own dedicated endpoints
    (`GET .../explanation`, `GET .../rule-proposal`), not this body.
    `review_state`/`note`/`dismissal_reason`/`reviewed_at` default to
    `"unreviewed"`/`null`/`null`/`null` for a finding with no recorded
    review.

    `affected_row_numbers` (`FIND-01`, `WP-038`, extending) is a small,
    disclosed addition: the finding's own affected `RowReference.row_number`
    values, ascending. Needed by the Finding Detail UI's row-context
    Prev/Next jump list (`docs/decision-log.md` D-025,
    `project-ops/changes/CHG-001-investigation-ux-row-context.md` §3),
    which cannot be built from `affected_row_count` alone. Every other
    field is unchanged from `WP-027`.
    """

    finding_id: str
    detector_id: str
    detector_version: str
    category: str
    severity: str
    confidence: float
    priority_score: float
    calculated_observation: str
    affected_columns: list[ColumnReferenceResponse]
    affected_row_count: int
    affected_row_numbers: list[int]
    evidence_count: int
    security_exposure: SecurityExposureResponse
    review_state: str
    note: str | None
    dismissal_reason: str | None
    reviewed_at: datetime | None


class FindingReviewRequest(BaseModel):
    """Body for `PUT /analyses/{analysis_id}/findings/{finding_id}/review`
    (`REV-01`, `WP-083`). `dismissal_reason` is required (and must be
    non-empty) when `state` is `"dismissed"`, and must be omitted/`null`
    otherwise — `422 REVIEW_INVALID` on either violation."""

    state: str
    note: str | None = None
    dismissal_reason: str | None = None


class FindingReviewResponse(BaseModel):
    """Body for `PUT .../review`'s response, and the shape
    `FindingItem`/`FindingDetailResponse`'s own review fields mirror."""

    finding_id: str
    review_state: str
    note: str | None
    dismissal_reason: str | None
    reviewed_at: datetime


class FindingEvidenceItem(BaseModel):
    """One entry in `GET .../findings/{finding_id}/evidence`'s response
    (`WP-027`). Mirrors `domain.evidence.Evidence`, deliberately
    excluding `structured_payload`: `docs/domain-model.md` §13's own
    invariants ("report references use display-safe summaries"; raw
    sensitive values are not embedded unless explicitly allowed, a
    redaction guarantee not yet mechanically enforced pending `PRIV-01`)
    both argue against exposing the open-ended raw payload through any
    API response before that redaction package exists.
    `affected_row_count` is a bounded count, matching `FindingItem`'s
    established convention and `docs/domain-model.md` §13's "row
    evidence is bounded for display" invariant — not the raw row
    reference list.
    """

    evidence_id: str
    evidence_type: str
    display_safe_summary: str
    affected_columns: list[ColumnReferenceResponse]
    affected_row_count: int
    scope: str


class FindingEvidenceListResponse(BaseModel):
    """Body for `GET /analyses/{analysis_id}/findings/{finding_id}/evidence`.
    Returns an empty `items` list (not an error) if a valid finding
    happens to have no resolvable evidence entries — defensive, matching
    `FindingsListResponse`'s existing empty-list-not-an-error convention.
    """

    items: list[FindingEvidenceItem]
    total_items: int


class ObservationItem(BaseModel):
    """One neutral observation in `GET /analyses/{analysis_id}/observations`
    (`DET-03` closure package 2, `WP-109`; provisional API).

    Mirrors `domain.observation.Observation`. It deliberately has **no**
    severity, confidence, priority or review field: an observation is not a
    finding and never affects the trust score or priority. `structured_payload`
    is excluded, like `FindingEvidenceItem`'s, so no open-ended raw payload is
    exposed; `summary` already states the counts. `affected_row_numbers` are
    the bounded example row numbers (at most 20), never cell values.
    `kind` is the closed kind name (`value_evidence` is the only one today); a
    later kind is added, never a change to this one.
    """

    observation_id: str
    kind: str
    producer_detector_id: str
    summary: str
    affected_columns: list[ColumnReferenceResponse]
    affected_row_numbers: list[int]
    scope: str


class ObservationsListResponse(BaseModel):
    """Body for `GET /analyses/{analysis_id}/observations`. Read-only. Returns
    an empty `items` list (not an error) for a known analysis that is not
    `COMPLETED` or that has no observations, matching
    `FindingsListResponse`'s convention."""

    items: list[ObservationItem]
    total_items: int


class RowContextEntryResponse(BaseModel):
    """One row in a `RowContextResponse` window (`FIND-01`, `WP-038`).
    Mirrors `domain.row_context.RowContextEntry`. `values` is positional,
    aligned by index with the owning response's `columns` list — not a
    mapping, matching the domain type's own alignment convention.
    `source_line_number`/`fingerprint` are omitted: `parsers.csv_parser`
    never sets either on the `RowReference`s it produces today, so
    exposing them would only ever be `null` — a disclosed, reversible
    scoping choice, not a contract gap.
    """

    row_number: int
    is_anchor: bool
    is_affected_by_finding: bool
    values: list[str | None]


class RowContextResponse(BaseModel):
    """Body for `GET /analyses/{analysis_id}/findings/{finding_id}/row-context`
    (`FIND-01`, `WP-038`; `docs/api-specification.md` §10; `docs/domain-model.md`
    §13's "Row context (non-Evidence)" subsection). Mirrors
    `domain.row_context.RowContextWindow` exactly.
    """

    columns: list[ColumnReferenceResponse]
    requested_before: int
    requested_after: int
    actual_before: int
    actual_after: int
    truncated_at_start: bool
    truncated_at_end: bool
    max_window: int
    rows: list[RowContextEntryResponse]


class BusinessImpactStatementResponse(BaseModel):
    """One *potential* business implication of a finding (`AI-08`),
    mirroring `domain.explanation.BusinessImpactStatement`.

    `basis` is derived by TrustTable and says how a client must present the
    statement: `"confirmed_context"` (it cites context the user confirmed or
    corrected, so show it as *informed by* that context) or `"assumption"`
    (only a possible consequence). Either way it is a potential impact shown
    together with its `assumption` (the condition under which it would
    hold), never as a fact — there is deliberately no "evidence" basis,
    because the deterministic evidence establishes what was found in the
    data, not what it costs a business.
    """

    statement: str
    basis: Literal["confirmed_context", "assumption"]
    evidence_ids: list[str]
    context_fields: list[str]
    assumption: str


class RemediationOptionResponse(BaseModel):
    """One structured remediation recommendation (`REM-01`), mirroring
    `domain.explanation.RemediationOption`.

    `risk_warning` is always populated (never `null`/empty) — a documented
    simplification of `docs/domain-model.md` §16's conditional "destructive
    actions include risk warnings" invariant, avoiding fragile keyword-based
    destructiveness classification. `technical_example` is `null` when no
    concrete example applies. Advisory only — TrustTable never changes
    uploaded data; nothing here claims that it did.
    """

    remediation_id: str
    action_summary: str
    responsible_role: str
    urgency: str
    historical_correction_guidance: str
    source_system_prevention_guidance: str
    risk_warning: str
    verification_step: str
    technical_example: str | None
    evidence_ids: list[str]


class ProposedValidationRuleResponse(BaseModel):
    """A validation rule *proposal* (`AI-08`), mirroring
    `domain.explanation.ProposedValidationRule`.

    `status` is always `"proposed"`: nothing in the application runs,
    enforces or exports this rule (the rule engine is `RULE-01`, a later
    item), so a client must never present it as active or authoritative.
    `rule_type` is one of the `docs/product-requirements.md` §13 types.
    """

    rule_type: str
    columns: list[ColumnReferenceResponse]
    description: str
    status: Literal["proposed"]


class AiProvenanceResponse(BaseModel):
    """Human-readable provenance of an accepted AI interpretation
    (`AI-08`), derived by `ai_provider.display`.

    Only display labels and a sanitized identifier: never a filesystem
    path (the raw configured model value never leaves the backend).
    `model_identifier` is the final path segment only, bounded, kept for
    diagnostics.
    """

    deployment_label: str
    runtime_label: str
    model_label: str | None
    quantization: str | None
    model_identifier: str | None


class FindingExplanationResponse(BaseModel):
    """Body for `GET /analyses/{analysis_id}/findings/{finding_id}/explanation`
    (`UI-02` slice 1, `WP-063`; four-section analysis `AI-08`). Mirrors
    `domain.explanation.FindingExplanation` exactly, plus `ai_call_status`
    (`WP-065`, defect fix) and the human-readable `ai_provenance`.
    `provenance` is the `Provenance` enum's string value
    (`"deterministic_fallback"` or `"ai_interpretation"` only —
    `FindingExplanation`'s own closed set, `AI-05`).
    `provider_name`/`model_identifier` are both `null` for a
    deterministic-fallback explanation (no provider was used — the
    default, AI-disabled behavior) and populated for an accepted
    AI-interpretation explanation. **`AI-08`:** `model_identifier` is the
    *sanitized* identifier (final path segment only); the raw configured
    value never leaves the backend, and `ai_provenance` carries the labels
    a UI should show.

    **`AI-08` — the four sections.** `narrative` (the explanation),
    `business_impact`, `remediation` and `validation_rule` are always
    present. When `provenance == "ai_interpretation"` they come from one
    validated, structurally constrained AI response; otherwise from
    TrustTable's deterministic built-in guidance, so they are useful with
    AI disabled, rejected or failing. `business_impact` statements carry
    their `basis`; `remediation` is advisory only (TrustTable never
    changes an uploaded file); `validation_rule.status` is always
    `"proposed"`.

    `ai_call_status` (`WP-065`) discloses this specific request's own AI
    call lifecycle independently of `provenance`/`provider_name`, closing
    a real gap `provenance` alone cannot express: `provenance ==
    "deterministic_fallback"` is ambiguous between "no provider is
    configured" and "a provider was tried and failed/was rejected".
    Exactly one of:

    - `"not_configured"` — `Settings.llm_provider == "disabled"`; no AI
      call was attempted for this request.
    - `"not_attempted"` (`UX-05b`) — a provider is configured but no AI
      enrichment of this finding is current: none was requested, it is
      still preparing, or the saved one is stale. This route never calls a
      model; it overlays only a *current* saved enrichment
      (`POST`/`GET .../ai-enrichment` start and report it).
    - `"attempted_accepted"` — a provider was called and its output was
      accepted; `provenance == "ai_interpretation"`.
    - `"attempted_rejected"` — a provider was called, its output (and
      any bounded retries) failed `ai_boundary.validation.
      validate_model_output`; the deterministic explanation was returned
      instead (`provenance == "deterministic_fallback"`).
    - `"attempted_provider_error"` — a provider was called and raised a
      `ProviderError` (connection/timeout/malformed response); the
      deterministic explanation was returned instead (`provenance ==
      "deterministic_fallback"`).

    Deliberately independent of `Analysis.security_exposure` (`GET
    .../findings/{finding_id}`'s own `security_exposure` field), which
    describes only the deterministic detection pipeline's own,
    permanently-`False` raw-sample-exposure posture — never this
    per-request enrichment call. See `docs/architecture.md` §6/§7 and
    `docs/decision-log.md` D-037/D-038.

    `evidence_sent_to_model`/`confirmed_context_sent_to_model`
    (`WP-065` r4 — closes a real semantic-review `FAIL`: `ai_call_status`
    alone discloses axes 1-3/6 of D-038's six-axis model but never
    axis 5, "finding/evidence/context metadata exposure") disclose
    exactly what bounded metadata this specific request actually sent
    to a model, independent of whether that attempt was accepted.
    `evidence_sent_to_model` is `True` whenever `ai_call_status` is any
    `attempted_*` value (this finding's own captured `Evidence` is
    always the envelope's `computed_evidence` on every attempt).
    `confirmed_context_sent_to_model` is `True` only when an attempt was
    made *and* `Analysis.context_finalized` was already `True` at call
    time (the same gate `confirmed_context` itself uses). Both are
    `False` whenever `ai_call_status == "not_configured"`. Neither ever
    reflects raw dataset sample content — only this route's own bounded
    `Evidence`/`DatasetContext` inputs, matching `AI-05`/`CTX-02`'s
    existing zero-raw-sample-sending design.
    """

    finding_id: str
    narrative: str
    provenance: str
    provider_name: str | None
    model_identifier: str | None
    ai_provenance: AiProvenanceResponse | None
    ai_call_status: str
    evidence_sent_to_model: bool
    confirmed_context_sent_to_model: bool
    referenced_evidence_ids: list[str]
    referenced_columns: list[ColumnReferenceResponse]
    business_impact: list[BusinessImpactStatementResponse]
    remediation: list[RemediationOptionResponse]
    validation_rule: ProposedValidationRuleResponse | None


class FindingAiEnrichmentResponse(BaseModel):
    """Body for `GET`/`POST /analyses/{analysis_id}/findings/{finding_id}/
    ai-enrichment` (`UX-05b`, D-066 item 7): the state of one finding's
    persisted, non-blocking AI enrichment. It never carries the model's
    output (that is read through `.../explanation` only while current) and
    never a model path, address or prompt.

    `state` is exactly one of `unavailable` (no model is configured),
    `not_requested`, `preparing`, `ready`, `failed` or `stale` (the saved
    result was produced under a different finding/context/model/prompt
    binding and is not shown as current). `reason` explains a `failed`
    state (`interrupted`, `provider_error`, `rejected`, `superseded`,
    `unreadable`) and is `null` otherwise. `poll_interval_ms` is set only
    while `preparing`.
    """

    finding_id: str
    state: str
    reason: str | None
    poll_interval_ms: int | None


class ContextFieldValueResponse(BaseModel):
    """Mirrors `domain.context.ContextFieldValue` (`UI-02` slice 2,
    `WP-064`). `value` is a plain `str` for the five single-value
    `ContextField`s and a `list[str]` of column original names for the
    four column-role fields — mirroring the domain type's own disclosed
    open-typed shape exactly (see its docstring).
    """

    value: str | list[str]
    confidence: float
    inference_source: str
    confirmation_state: str
    evidence_ids: list[str]


class ContextResponse(BaseModel):
    """Body for `GET`/`PUT /analyses/{analysis_id}/context` (`UI-02`
    slice 2, `WP-064`; `docs/api-specification.md` §9).

    `context_version` is not part of `domain.context.DatasetContext`
    itself (`Analysis.context_version` is separate) — included here as
    a disclosed, minimal API-shape addition the client needs for the
    optimistic-concurrency contract §9 already specifies ("requires
    resource version"). Every other field mirrors `DatasetContext`
    exactly.
    """

    context_version: int
    schema_version: str
    probable_domain: ContextFieldValueResponse
    row_grain: ContextFieldValueResponse
    primary_entity: ContextFieldValueResponse
    candidate_keys: ContextFieldValueResponse
    business_dates: ContextFieldValueResponse
    measure_roles: ContextFieldValueResponse
    dimensions: ContextFieldValueResponse
    currency_behavior: ContextFieldValueResponse
    expected_business_rules: ContextFieldValueResponse


class ClarificationQuestionResponse(BaseModel):
    """Mirrors `domain.clarification.ClarificationQuestion` (`UI-02`
    slice 2, `WP-064`)."""

    question_id: str
    context_field: str
    concise_text: str
    explanation: str
    suggested_answers: list[str]
    inferred_default: str | None
    affected_assumptions: list[str]
    free_text_allowed: bool
    answered_state: str


class ClarificationQuestionListResponse(BaseModel):
    """Body for `GET /analyses/{analysis_id}/questions` (`UI-02`
    slice 2, `WP-064`)."""

    items: list[ClarificationQuestionResponse]
    total_items: int


class ClarificationAnswerResponse(BaseModel):
    """Mirrors `domain.clarification.ClarificationAnswer` (`UI-02`
    slice 2, `WP-064`)."""

    question_id: str
    selected_answer_or_free_text: str
    answered_timestamp: datetime
    resulting_context_changes: list[str]
    provenance: str


class AnswerGuidedQuestionResponse(BaseModel):
    """Body for `POST /analyses/{analysis_id}/questions/{question_id}/answer`
    (`UI-02` slice 2, `WP-064`; `docs/api-specification.md` §9's "stores
    an answer and resulting context updates")."""

    context: ContextResponse
    question: ClarificationQuestionResponse
    answer: ClarificationAnswerResponse


class ConfirmContextFieldsRequest(BaseModel):
    """Request body for `PUT /analyses/{analysis_id}/context` (`UI-02`
    slice 2, `WP-064`). `edits` keys are `ContextField` string values
    (e.g. `"probable_domain"`); an unknown key or a role-field key both
    resolve to `INVALID_CONTEXT` (422)."""

    edits: dict[str, str]
    expected_version: int


class AnswerGuidedQuestionRequest(BaseModel):
    """Request body for `POST .../questions/{question_id}/answer`
    (`UI-02` slice 2, `WP-064`)."""

    answer_text: str
    expected_version: int


class FinalizeContextRequest(BaseModel):
    """Request body for `POST /analyses/{analysis_id}/finalize` (`UI-02`
    slice 2, `WP-064`)."""

    expected_version: int


# ---------------------------------------------------------------------------
# RULE-01 slice 1: validation rules
# ---------------------------------------------------------------------------


class RuleFailureExampleResponse(BaseModel):
    """Mirrors `domain.rules.RuleFailureExample` — one bounded example of
    a row that failed a rule (`RULE-01` slice 1)."""

    row_number: int
    reason: str


class RuleExecutionResultResponse(BaseModel):
    """Mirrors `domain.rules.RuleExecutionResult` (`RULE-01` slice 1,
    `docs/domain-model.md` §19). `MAX_MISSING_PERCENTAGE`/
    `MAX_DUPLICATE_PERCENTAGE` report the raw incident count per row —
    compare `fail_count / (pass_count + fail_count)` against the rule's
    own `threshold_percentage` for the intended pass/fail interpretation.
    """

    executed_at: datetime
    pass_count: int
    fail_count: int
    skipped_count: int
    example_failures: list[RuleFailureExampleResponse]
    duration_ms: float
    error: str | None


class ValidationRuleResponse(BaseModel):
    """Mirrors `domain.rules.ValidationRule` (`RULE-01`, all 11 rule
    types as of slice 2, `WP-079`; `docs/domain-model.md` §18). Every
    parameter field not used by `rule_type` is `null` — the same shape
    `ValidationRule.__post_init__` itself enforces."""

    rule_id: str
    schema_version: str
    name: str
    description: str
    severity: str
    rule_type: str
    columns: list[ColumnReferenceResponse]
    null_handling: str
    enabled: bool
    scope: str
    accepted_values: list[str] | None
    minimum: float | None
    maximum: float | None
    minimum_date: str | None
    maximum_date: str | None
    pattern: str | None
    threshold_percentage: float | None
    tolerance: float | None
    comparison_operator: str | None
    comparison_value: float | None
    condition_operator: str | None
    condition_value: float | None
    source_finding_ids: list[str]
    provenance: str
    last_result: RuleExecutionResultResponse | None


class ValidationRulesListResponse(BaseModel):
    """Body for `GET /analyses/{analysis_id}/rules` (`RULE-01`)."""

    items: list[ValidationRuleResponse]
    total_items: int


class CreateValidationRuleRequest(BaseModel):
    """Request body for `POST /analyses/{analysis_id}/rules` (`RULE-01`,
    all 11 rule types as of slice 2, `WP-079`). `column_names` are
    matched against the dataset's real `original_name` values; an
    unknown name is rejected with `UNKNOWN_RULE_COLUMN` (422) before any
    execution. Every parameter field not required by `rule_type`
    (`docs/domain-model.md` §18's table, mirrored in
    `domain.rules.ValidationRule`'s own docstring) must be left `null` —
    a mismatch is rejected with `INVALID_RULE_PARAMETERS` (422).
    `comparison_operator`/`condition_operator` are one of
    `domain.rules.ComparisonOperator`'s closed string values.
    `source_finding_id` (`RULE-02` slice 1, `WP-080`) is optional: when
    given, the finding must exist on this analysis (`FINDING_NOT_FOUND`,
    404, otherwise) and the persisted rule records
    `provenance="detector_generated"` with `source_finding_ids` set —
    accepting a `GET .../rule-proposal` offer. Omitted (the default)
    means `provenance="user_authored"`, unchanged from `RULE-01`."""

    name: str
    description: str
    severity: str
    rule_type: str
    column_names: list[str]
    null_handling: str = "skip"
    accepted_values: list[str] | None = None
    minimum: float | None = None
    maximum: float | None = None
    minimum_date: str | None = None
    maximum_date: str | None = None
    pattern: str | None = None
    threshold_percentage: float | None = None
    tolerance: float | None = None
    comparison_operator: str | None = None
    comparison_value: float | None = None
    condition_operator: str | None = None
    condition_value: float | None = None
    source_finding_id: str | None = None


# ---------------------------------------------------------------------------
# RULE-02 slice 1: deterministic rule generation
# ---------------------------------------------------------------------------


class RuleProposalResponse(BaseModel):
    """Body for `GET /analyses/{analysis_id}/findings/{finding_id}/
    rule-proposal` (`RULE-02` slice 1, `WP-080`; AI-assisted extension,
    slice 2, `WP-081`). `available=False` means no safe proposal exists
    for this finding's detector (`reason` states why); `rule`/`result`
    are then both `null`. `available=True` means `rule` is an
    already-executed candidate, never persisted by this route —
    `rule.rule_id` is a fresh, disposable id, not a stored identity.
    Accepting the offer is a separate `POST .../rules` call with
    `source_finding_id` set; `rule.provenance` distinguishes
    `"detector_generated"` (slice 1, no AI involved) from
    `"ai_assisted"` (slice 2, this response's own AI attempt was
    accepted).

    `ai_call_status`/`evidence_sent_to_model` (`WP-081`) mirror
    `FindingExplanationResponse`'s own established disclosure fields
    exactly, scoped to this specific request's AI-assisted attempt (for
    `consistency.inconsistent_capitalization` only, and only once slice
    1's deterministic mapping already reported unavailable):

    - `"not_configured"` — no AI-assisted attempt was made for this
      request, either because `Settings.llm_provider == "disabled"` or
      because this finding's detector is not AI-assistable (including
      every case where slice 1 already found a deterministic mapping).
    - `"attempted_accepted"` — a provider was called and its chosen
      value was accepted; `rule.provenance == "ai_assisted"`.
    - `"attempted_rejected"` — a provider was called, but its output
      failed `ai_boundary.rule_generation.validate_rule_generation_output`;
      falls back to slice 1's identical `available=False` response.
    - `"attempted_provider_error"` — a provider was called and raised a
      `ProviderError`; falls back to slice 1's identical
      `available=False` response.

    `evidence_sent_to_model` is `True` whenever `ai_call_status` is any
    `attempted_*` value (this finding's own evidence is always the
    envelope's `computed_evidence` on every attempt); `False` otherwise.
    Never reflects raw dataset sample content — this contract sends
    zero dataset samples regardless.
    """

    available: bool
    reason: str | None
    rule: ValidationRuleResponse | None
    result: RuleExecutionResultResponse | None
    ai_call_status: str
    evidence_sent_to_model: bool
