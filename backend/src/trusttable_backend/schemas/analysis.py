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
    `stored_filename`/`storage_location`/`selected_worksheet`/
    `deleted_at`, none of which are meaningful yet for an in-memory,
    demo-only, never-deleted dataset (`API-01` non-goals: no generic
    upload, no deletion).
    """

    dataset_id: str
    original_filename: str
    format: str
    byte_size: int
    content_hash: str
    source_type: str
    created_at: datetime


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


class AnalysisStatusResponse(BaseModel):
    """Body for `GET /analyses/{analysis_id}/status` — a lightweight
    polling endpoint (`docs/api-specification.md` §6).

    `state` now reflects real, persisted stage progression
    (`queued`/`parsing`/`profiling`/`detecting`/terminal — `JOB-01`,
    `WP-075`: a bounded worker pool runs the pipeline in the background
    instead of synchronously inside the request). `poll_interval_ms`
    stays a fixed constant regardless (no adaptive backoff has been
    built). `retryable`/a numeric `progress_percentage` remain
    deliberately omitted: no retry endpoint exists yet, and there is no
    meaningful sub-stage partial-progress signal within one stage
    either — both a disclosed, separate follow-up slice.
    """

    analysis_id: str
    state: str
    message: str
    cancellable: bool
    poll_interval_ms: int


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
    identifier exists yet. No review-state field: the full `Finding`
    aggregate's review state (`docs/domain-model.md` §12) does not exist
    yet (`REV-01`, a later package). `affected_row_count` and
    `evidence_count` are bounded counts, not the raw row-reference/
    evidence-ID lists — matching this repository's established
    "bounded, not raw" list-response convention (`PROF-03`'s profile
    endpoint precedent above).
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
    affected columns/rows, evidence count, technical metadata, and
    security exposure. Deliberately omits possible business impact,
    remediation, proposed validation rules, and review state — no
    package computes any of those yet (`REM-01`, `RULE-01`, `REV-01` are
    all later, unimplemented backlog items); a placeholder field would
    misrepresent "not built yet" as "computed but empty".

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
    remediation: list[str]
    validation_rule: ProposedValidationRuleResponse | None


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
