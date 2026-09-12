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
from typing import Any

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
    """Mirrors `detectors.contract.SecurityExposureState`. Always
    reports the disabled/no-transmission state today — no AI/LLM
    provider exists yet (`AI-01`/`AI-02`).
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

    `poll_interval_ms` is a fixed constant: `run_analysis` executes
    synchronously to completion within one call (`API-01` enabling
    slice, `WP-023`), so there is no real progress signal to derive a
    dynamic recommendation from yet (`JOB-01`, not yet built).
    `retryable`/a numeric `progress_percentage` are deliberately omitted:
    no retry endpoint exists yet, and synchronous execution has no
    meaningful partial-progress signal either.
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
