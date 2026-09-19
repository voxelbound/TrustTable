"""In-memory analysis orchestration (`API-01`, enabling slice, `WP-023`;
generalized to generic uploads, `WP-029`; extended with a context-
confirmation layer, `API-02` enabling slice, `WP-059`).

A pure-Python, framework-independent orchestration engine wiring together
every already-delivered package (`ING-02` CSV parsing, `PROF-03`
profiling, `DET-01`/`DET-02`/`DET-SEC-01` detectors via `run_detectors()`,
`RISK-01` scoring) into one deterministic create-then-run pipeline over
either the bundled demo dataset (`DEMO-01`, `create_analysis`) or an
uploaded CSV file (`create_analysis_from_upload`, `WP-029`). No
persistence or AI provider call exist yet — this module is the
"Application services"-layer engine `API-01`'s HTTP routes
(`api/v1/analyses.py`) expose (`docs/architecture.md` §3).

`run_analysis` is source-agnostic: it reads the bytes an analysis was
created with from `Analysis.content` rather than regenerating anything
itself (a `WP-029` refactor — previously it always regenerated the
bundled demo dataset internally, which happened to be correct only
because no other content source existed yet).

`AnalysisState` remains an 8-value documented subset of `docs/domain-
model.md` §5's 11-value `States` list (`inferring_context`/
`awaiting_confirmation`/`finalizing`/`deleted` still excluded) — a
**deliberate scoping decision, not an oversight**: `CTX-01`/`CTX-02`/
`CTX-03` now exist, but wiring `run_analysis` itself to pause at a new
confirmation gate before `COMPLETED` would regress the already-shipped,
milestone-complete `v0.1`/`v0.1.1` UI's poll-until-`COMPLETED` behavior,
which has no confirmation-gate UI to recover from a new pause. `API-02`
(`WP-059`) instead adds `get_or_infer_context`/`get_guided_questions`/
`confirm_context_fields`/`answer_guided_question`/`finalize_context` as
a strictly additive layer over an already-`COMPLETED` analysis —
`context`/`guided_questions`/`context_version`/`context_finalized` are
computed and mutated entirely independently of `state`, which continues
to reach `COMPLETED` exactly as it always has. Whether the pipeline
should ever actually pause for confirmation remains an open, later,
human-directed product decision. "State" and "current stage" remain
merged into one field, the same disclosed, reversible simplification as
before.

`cancel_analysis` is only effective while an analysis is `QUEUED`: true
mid-pipeline cancellation requires real bounded background execution
(`JOB-01`, not yet built) — `run_analysis` executes synchronously to
completion within one call, so no "active and cancellable" window exists
yet.

Every `Analysis.security_exposure` is fixed to the disabled/
no-transmission `SecurityExposureState` — no route or service function
in this module (including the new `API-02` context functions, which
deliberately never call `CTX-02`'s AI augmentation) actually invokes an
`AI-01`/`AI-02`/`AI-03` provider, matching `docs/product-requirements.md`
§5.7's "graceful AI-disabled operation" requirement structurally.

**This guarantee is scoped to this module only (`WP-065`, defect fix;
`docs/decision-log.md` D-038).** A separate, later, optional per-request
AI enrichment layer *does* exist and does invoke a real provider when
`Settings.llm_provider != "disabled"` — `api.v1.analyses.
get_analysis_finding_explanation` (`AI-05`/`UI-02`, `WP-061`/`WP-063`)
and `get_analysis_context`'s first-call augmentation (`UI-02` slice 2
revision, `WP-064`). Both live in the API route layer, deliberately not
here, and neither ever mutates `Analysis.security_exposure` or any
value this module computes — see those routes' own docstrings and
`docs/architecture.md` §6's two-phase model (D-037) for why the route
layer, not this service module, is the correct seam for that optional
call.

Framework-independent besides its `context_inference` seam (`CTX-01`'s
`infer_dataset_context`, `CTX-03`'s `generate_guided_questions` — both
themselves deterministic, no `ai_boundary`/`ai_provider` import in
either): no FastAPI/SQLAlchemy/pydantic import (this module deliberately
also avoids `version_info`/`config`, which would transitively pull in
pydantic `Settings` — a disclosed, conservative choice). Stdlib
otherwise (`dataclasses`, `enum`, `datetime`, `uuid`, `hashlib`). No
`eval`/`exec` anywhere in this module.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from enum import StrEnum

from ..context_inference.guided_questions import generate_guided_questions
from ..context_inference.heuristics import infer_dataset_context
from ..demo_data import SEED, generate
from ..detectors.catalogue import DETECTORS
from ..detectors.contract import FindingCandidate, SecurityExposureState
from ..detectors.engine import run_detectors
from ..domain.clarification import (
    ClarificationAnswer,
    ClarificationQuestion,
    QuestionAnsweredState,
)
from ..domain.context import ConfirmationState, ContextField, ContextFieldValue, DatasetContext
from ..domain.evidence import Evidence
from ..domain.parsing import Dataset, DatasetFormat, DatasetSourceType
from ..domain.row_context import RowContextEntry, RowContextWindow
from ..domain.value_objects import Provenance, RowReference
from ..parsers.csv_parser import parse_csv
from ..profiling.metrics import compute_dataset_profile
from ..profiling.schemas import DatasetProfile
from ..risk.scoring import (
    TrustAssessment,
    calculate_finding_priority_scores,
    calculate_trust_assessment,
)

#: Maximum rows returned on either side of the anchor row for
#: `get_finding_row_context` (`FIND-01`). CHG-001 Decision 6 left the exact
#: value implementation-owned; a request exceeding this is clamped, not
#: rejected — the response's own `requested_*`/`actual_*`/`truncated_at_*`
#: fields already model that distinction. Recorded in
#: `docs/api-specification.md` §10 once selected.
_MAX_ROW_CONTEXT_WINDOW_PER_SIDE = 25

_NO_EXPOSURE = SecurityExposureState(
    model_provider_enabled=False, sample_transmission_enabled=False
)
"""Every `Analysis` produced by `create_analysis` uses this fixed,
disabled exposure state — no AI/LLM provider exists yet (`AI-01`/
`AI-02`)."""

_DEMO_ORIGINAL_FILENAME = "sales_demo.csv"
_DEMO_STORAGE_LOCATION = "demo-data/sales_demo.csv"
"""References the real, committed demo dataset path/filename for
accuracy even though this module never reads it from disk — the
generated bytes are byte-identical to that file (`DEMO-01`'s own
drift-check precedent). A disclosed, forward-compatible choice for
whenever a real storage layer (`DB-01`) exists."""

_FAILURE_CODE = "analysis.pipeline_failed"
_FAILURE_MESSAGE = "Analysis pipeline raised an exception during execution"
"""Fixed, safe, non-leaking failure code/message — never includes raw
exception text, matching `DET-01` `engine.py`'s own safe-failure
precedent one layer more conservatively (no exception type name either)."""

_EDITABLE_CONTEXT_FIELDS = frozenset(
    {
        ContextField.PROBABLE_DOMAIN,
        ContextField.ROW_GRAIN,
        ContextField.PRIMARY_ENTITY,
        ContextField.CURRENCY_BEHAVIOR,
        ContextField.EXPECTED_BUSINESS_RULES,
    }
)
"""The five single-value `ContextField`s `confirm_context_fields`/
`answer_guided_question` (`API-02`) may write to — mirrors
`context_inference.guided_questions`'s own eligible-field set exactly
(the four "role" fields remain read-only in this package, a disclosed
limitation)."""


class AnalysisState(StrEnum):
    """An 8-value documented subset of `docs/domain-model.md` §5's
    11-value `States` list. `inferring_context`, `awaiting_confirmation`,
    and `finalizing` are deliberately excluded — see this module's own
    docstring for the full disclosed reasoning (`API-02`, `WP-059`:
    wiring the pipeline itself to pause for confirmation would regress
    the already-shipped `v0.1`/`v0.1.1` UI). `deleted` is excluded
    because no deletion package (`DEL-01`) exists yet. This module's own
    pipeline (`run_analysis`) goes directly from `DETECTING` to
    `COMPLETED`, unchanged by `API-02`'s additive context-confirmation
    layer.
    """

    QUEUED = "queued"
    VALIDATING = "validating"
    PARSING = "parsing"
    PROFILING = "profiling"
    DETECTING = "detecting"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class AnalysisFailure:
    """A safe, non-leaking failure description (`docs/domain-model.md`
    §5's "safe failure code and message" field), matching `DET-01`'s
    existing `SafeFailure` shape/precedent.
    """

    code: str
    message: str

    def __post_init__(self) -> None:
        if not self.code:
            raise ValueError("AnalysisFailure.code must not be empty")
        if not self.message:
            raise ValueError("AnalysisFailure.message must not be empty")


@dataclass(frozen=True, slots=True)
class Analysis:
    """One in-memory analysis record.

    Invariants tie every result field and terminal timestamp to `state`:
    `dataset_profile`/`findings`/`priority_scores`/`trust_assessment`/
    `evidence` are all empty/`None` unless `state == COMPLETED`;
    `completed_at` is set if and only if `state == COMPLETED`;
    `failure`/`failed_at` are set if and only if `state == FAILED`;
    `cancelled_at` is set if and only if `state == CANCELLED`;
    `priority_scores` is always 1:1 with `findings`.

    `evidence` (`WP-027`) holds every `Evidence` object every detector
    run produced for this analysis — captured by `run_analysis` from
    each `DetectorRunResult.evidence` (previously computed and then
    discarded before this package). `get_finding_evidence` resolves a
    finding's own `evidence_ids` against this collection.

    `content` (`WP-029`) is the immutable raw bytes this analysis was
    created from (either the generated demo CSV or an uploaded file) —
    an in-memory-only retention, not persistence (`DB-01` is not built
    yet, the same disclosed non-goal `AnalysisStore` itself already
    carries one layer up). Declared `repr=False` so it can never appear
    in an accidental log/repr of an `Analysis` instance.

    `context`/`guided_questions`/`context_version`/`context_finalized`
    (`API-02`, `WP-059`) are a strictly additive layer over an already-
    `COMPLETED` analysis: `context` and `guided_questions` are computed
    once, lazily, by `get_or_infer_context` (`CTX-01`'s
    `infer_dataset_context`/`CTX-03`'s `generate_guided_questions`, both
    deterministic — `CTX-02`'s AI augmentation is deliberately not
    invoked here, see this module's own scoping note above);
    `context_version` implements `docs/api-specification.md` §9's "PUT
    context... requires resource version" optimistic-concurrency check,
    starting at `0` (context not yet inferred) and incremented by every
    mutating function below. None of these four fields participate in
    `run_analysis`'s own state machine — they exist only once `state is
    COMPLETED`, exactly like `dataset_profile`/`findings`.
    """

    analysis_id: str
    dataset: Dataset
    content: bytes = field(repr=False)
    state: AnalysisState
    security_exposure: SecurityExposureState
    dataset_profile: DatasetProfile | None
    findings: tuple[FindingCandidate, ...]
    priority_scores: tuple[float, ...]
    evidence: tuple[Evidence, ...]
    trust_assessment: TrustAssessment | None
    failure: AnalysisFailure | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    failed_at: datetime | None
    cancelled_at: datetime | None
    context: DatasetContext | None = None
    guided_questions: tuple[ClarificationQuestion, ...] = ()
    context_version: int = 0
    context_finalized: bool = False

    def __post_init__(self) -> None:
        if not self.analysis_id:
            raise ValueError("Analysis.analysis_id must not be empty")
        if not self.content:
            raise ValueError("Analysis.content must not be empty")
        if len(self.priority_scores) != len(self.findings):
            raise ValueError("Analysis.priority_scores must be 1:1 with findings")

        is_completed = self.state is AnalysisState.COMPLETED
        if is_completed:
            if self.dataset_profile is None:
                raise ValueError("Analysis: dataset_profile is required when state is COMPLETED")
            if self.trust_assessment is None:
                raise ValueError("Analysis: trust_assessment is required when state is COMPLETED")
        else:
            if self.dataset_profile is not None:
                raise ValueError("Analysis: dataset_profile must be None unless state is COMPLETED")
            if self.findings:
                raise ValueError("Analysis: findings must be empty unless state is COMPLETED")
            if self.evidence:
                raise ValueError("Analysis: evidence must be empty unless state is COMPLETED")
            if self.trust_assessment is not None:
                raise ValueError(
                    "Analysis: trust_assessment must be None unless state is COMPLETED"
                )
            if self.context is not None:
                raise ValueError("Analysis: context must be None unless state is COMPLETED")
            if self.guided_questions:
                raise ValueError(
                    "Analysis: guided_questions must be empty unless state is COMPLETED"
                )
            if self.context_version != 0:
                raise ValueError("Analysis: context_version must be 0 unless state is COMPLETED")
            if self.context_finalized:
                raise ValueError(
                    "Analysis: context_finalized must be False unless state is COMPLETED"
                )
        if (self.completed_at is not None) != is_completed:
            raise ValueError("Analysis.completed_at must be set if and only if state is COMPLETED")

        if (self.context is None) != (self.context_version == 0):
            raise ValueError(
                "Analysis.context_version must be 0 if and only if context has not been inferred"
            )
        if self.context_finalized and self.context is None:
            raise ValueError("Analysis.context_finalized requires context to be inferred first")

        is_failed = self.state is AnalysisState.FAILED
        if (self.failure is not None) != is_failed:
            raise ValueError("Analysis.failure must be set if and only if state is FAILED")
        if (self.failed_at is not None) != is_failed:
            raise ValueError("Analysis.failed_at must be set if and only if state is FAILED")

        is_cancelled = self.state is AnalysisState.CANCELLED
        if (self.cancelled_at is not None) != is_cancelled:
            raise ValueError("Analysis.cancelled_at must be set if and only if state is CANCELLED")


class AnalysisNotFoundError(Exception):
    """Raised by every getter/mutator below for an unknown `analysis_id`."""

    def __init__(self, analysis_id: str) -> None:
        super().__init__(f"Analysis not found: {analysis_id}")
        self.analysis_id = analysis_id


class FindingNotFoundError(Exception):
    """Raised by `get_finding`/`get_finding_evidence` (`WP-027`) for an
    unknown, malformed, or out-of-range `finding_id` — including a known
    analysis that has not yet reached `COMPLETED` (its `findings` tuple
    is still empty, so every `finding_id` is currently out of range,
    reusing `get_findings`' existing "empty until completed" semantics
    rather than a separate state check).
    """

    def __init__(self, analysis_id: str, finding_id: str) -> None:
        super().__init__(f"Finding not found: {finding_id} (analysis {analysis_id})")
        self.analysis_id = analysis_id
        self.finding_id = finding_id


class RowNotInFindingError(Exception):
    """Raised by `get_finding_row_context` (`FIND-01`) when the requested
    `anchor_row` does not equal the `row_number` of any of the finding's
    own `affected_row_references` — including a finding with zero affected
    rows, matching `docs/domain-model.md` §13's "available only for
    findings with at least one row reference" invariant and
    `docs/api-specification.md` §10's documented capability boundary (this
    endpoint reads context around a finding, not arbitrary rows in the
    file).
    """

    def __init__(self, analysis_id: str, finding_id: str, anchor_row: int) -> None:
        super().__init__(
            f"Row {anchor_row} is not one of finding {finding_id}'s affected rows "
            f"(analysis {analysis_id})"
        )
        self.analysis_id = analysis_id
        self.finding_id = finding_id
        self.anchor_row = anchor_row


class AnalysisNotReadyError(Exception):
    """Raised by every context-confirmation function below (`API-02`,
    `WP-059`) for a known but not-yet-`COMPLETED` analysis — context can
    only be inferred/confirmed/answered/finalized once the deterministic
    pipeline itself has produced a `DatasetProfile` to build it from.
    """

    def __init__(self, analysis_id: str) -> None:
        super().__init__(f"Analysis not ready for context confirmation: {analysis_id}")
        self.analysis_id = analysis_id


class ContextVersionConflictError(Exception):
    """Raised by every context-mutating function below (`API-02`) when
    the caller's `expected_version` does not match
    `Analysis.context_version` — implements `docs/api-specification.md`
    §9's "PUT context... requires resource version" optimistic-
    concurrency check.
    """

    def __init__(self, analysis_id: str, expected_version: int, actual_version: int) -> None:
        super().__init__(
            f"Context version conflict for analysis {analysis_id}: "
            f"expected {expected_version}, actual {actual_version}"
        )
        self.analysis_id = analysis_id
        self.expected_version = expected_version
        self.actual_version = actual_version


class ContextFieldNotEditableError(Exception):
    """Raised by `confirm_context_fields` (`API-02`) for any of the four
    "role" `ContextField`s (`candidate_keys`/`business_dates`/
    `measure_roles`/`dimensions`) — a disclosed, reversible scoping
    limitation mirroring `CTX-03`'s own eligible-field set exactly.
    """

    def __init__(self, analysis_id: str, context_field: ContextField) -> None:
        super().__init__(
            f"Context field is not editable: {context_field.value} (analysis {analysis_id})"
        )
        self.analysis_id = analysis_id
        self.context_field = context_field


class QuestionNotFoundError(Exception):
    """Raised by `answer_guided_question` (`API-02`) for a `question_id`
    that does not match any of the analysis's own `guided_questions`.
    """

    def __init__(self, analysis_id: str, question_id: str) -> None:
        super().__init__(f"Guided question not found: {question_id} (analysis {analysis_id})")
        self.analysis_id = analysis_id
        self.question_id = question_id


class AnalysisStore:
    """A minimal in-memory dict-backed store. No persistence
    (`DB-01`, not yet built) and no concurrency safety — disclosed,
    matching this package's stated non-goals.
    """

    def __init__(self) -> None:
        self._analyses: dict[str, Analysis] = {}

    def add(self, analysis: Analysis) -> None:
        self._analyses[analysis.analysis_id] = analysis

    def get(self, analysis_id: str) -> Analysis | None:
        return self._analyses.get(analysis_id)

    def replace(self, analysis: Analysis) -> None:
        self._analyses[analysis.analysis_id] = analysis


def _generate_demo_content() -> bytes:
    """Generate the bundled demo dataset's CSV bytes in-memory —
    deterministic, byte-identical to the committed
    `demo-data/sales_demo.csv` (`DEMO-01`'s own drift-check precedent).
    No filesystem read occurs.
    """
    generated = generate(seed=SEED)
    return generated.to_csv_text().encode("utf-8")


def create_analysis(store: AnalysisStore) -> Analysis:
    """Create a new `QUEUED` analysis over the bundled demo dataset and
    store it. Does not run the pipeline — see `run_analysis`.
    """
    content = _generate_demo_content()
    content_hash = hashlib.sha256(content).hexdigest()
    byte_size = len(content)
    now = datetime.now(UTC)

    dataset = Dataset(
        dataset_id=str(uuid.uuid4()),
        original_filename=_DEMO_ORIGINAL_FILENAME,
        stored_filename=_DEMO_ORIGINAL_FILENAME,
        format=DatasetFormat.CSV,
        byte_size=byte_size,
        content_hash=content_hash,
        selected_worksheet=None,
        created_at=now,
        deleted_at=None,
        storage_location=_DEMO_STORAGE_LOCATION,
        source_type=DatasetSourceType.BUNDLED_DEMO,
    )
    analysis = Analysis(
        analysis_id=str(uuid.uuid4()),
        dataset=dataset,
        content=content,
        state=AnalysisState.QUEUED,
        security_exposure=_NO_EXPOSURE,
        dataset_profile=None,
        findings=(),
        priority_scores=(),
        evidence=(),
        trust_assessment=None,
        failure=None,
        created_at=now,
        started_at=None,
        completed_at=None,
        failed_at=None,
        cancelled_at=None,
    )
    store.add(analysis)
    return analysis


def create_analysis_from_upload(
    store: AnalysisStore, *, content: bytes, original_filename: str
) -> Analysis:
    """Create a new `QUEUED` analysis over an uploaded CSV file's raw
    bytes and store it (`UI-01`/`API-01`, extending, `WP-029`). Does not
    run the pipeline — see `run_analysis`.

    `content` must already have passed the caller's own extension/
    content-type/size validation (`api/v1/analyses.py`'s `POST
    /analyses` handler) — this function performs no validation of its
    own beyond `Analysis.__post_init__`'s non-empty-content check.
    `original_filename` must already be sanitized
    (`uploads.filename.sanitize_filename`) — this function does not
    sanitize it again.

    `stored_filename`/`storage_location` are generated from a fresh
    `dataset_id`, never derived from `original_filename`
    (`docs/security-threat-model.md` §3.6: "generated storage names").
    No filesystem write occurs — no real storage layer exists yet
    (`DB-01`), the same disclosed precedent `create_analysis` already
    established for the bundled demo dataset's own nominal, never-read
    `storage_location`.
    """
    content_hash = hashlib.sha256(content).hexdigest()
    byte_size = len(content)
    now = datetime.now(UTC)
    dataset_id = str(uuid.uuid4())
    stored_filename = f"{dataset_id}.csv"

    dataset = Dataset(
        dataset_id=dataset_id,
        original_filename=original_filename,
        stored_filename=stored_filename,
        format=DatasetFormat.CSV,
        byte_size=byte_size,
        content_hash=content_hash,
        selected_worksheet=None,
        created_at=now,
        deleted_at=None,
        storage_location=f"uploads/{dataset_id}/{stored_filename}",
        source_type=DatasetSourceType.UPLOAD,
    )
    analysis = Analysis(
        analysis_id=str(uuid.uuid4()),
        dataset=dataset,
        content=content,
        state=AnalysisState.QUEUED,
        security_exposure=_NO_EXPOSURE,
        dataset_profile=None,
        findings=(),
        priority_scores=(),
        evidence=(),
        trust_assessment=None,
        failure=None,
        created_at=now,
        started_at=None,
        completed_at=None,
        failed_at=None,
        cancelled_at=None,
    )
    store.add(analysis)
    return analysis


def run_analysis(
    store: AnalysisStore, analysis_id: str, *, now: datetime | None = None
) -> Analysis:
    """Run the full pipeline for a `QUEUED` analysis, transitioning it
    through `VALIDATING`/`PARSING`/`PROFILING`/`DETECTING` to `COMPLETED`.

    Idempotent: calling this on a non-`QUEUED` analysis returns the
    current `Analysis` unchanged without re-executing anything. Any
    exception raised while running the pipeline is isolated into a fixed,
    safe `FAILED` transition (never raising itself), matching `DET-01`
    `engine.py`'s own exception-isolation precedent.

    `now` is an optional injected reference instant (defaults to the real
    wall clock): both `compute_dataset_profile`'s `as_of` date and
    `run_detectors`' `analysis_timestamp` are derived from the same
    `now` value so a single call is internally consistent, and so tests
    can reproduce a fixed instant deterministically — the same
    reasoning `compute_dataset_profile` itself already documents for its
    own `as_of` parameter.

    Raises `AnalysisNotFoundError` for an unknown `analysis_id`.
    """
    analysis = store.get(analysis_id)
    if analysis is None:
        raise AnalysisNotFoundError(analysis_id)
    if analysis.state is not AnalysisState.QUEUED:
        return analysis

    effective_now = now if now is not None else datetime.now(UTC)
    started_at = datetime.now(UTC)

    try:
        parsed = parse_csv(analysis.content)
        columns = parsed.parsed_dataset.columns

        dataset_profile = compute_dataset_profile(
            columns,
            parsed.rows,
            parsed.parsed_dataset.sampling,
            as_of=effective_now.date(),
        )
        mapping_rows = tuple(
            {column.internal_key: row[column.ordinal] for column in columns} for row in parsed.rows
        )
        results = run_detectors(
            list(DETECTORS),
            dataset_profile=dataset_profile,
            rows=mapping_rows,
            row_references=parsed.parsed_dataset.row_references,
            confirmed_context=None,
            security_exposure=analysis.security_exposure,
            analysis_timestamp=effective_now,
        )
        findings = tuple(finding for result in results for finding in result.findings)
        evidence = tuple(item for result in results for item in result.evidence)
        priority_scores = calculate_finding_priority_scores(
            findings, dataset_profile=dataset_profile
        )
        trust_assessment = calculate_trust_assessment(
            findings, priority_scores, security_exposure=analysis.security_exposure
        )
    except Exception:  # noqa: BLE001 - isolated per DET-01 engine.py precedent
        failed_at = datetime.now(UTC)
        failed = replace(
            analysis,
            state=AnalysisState.FAILED,
            failure=AnalysisFailure(code=_FAILURE_CODE, message=_FAILURE_MESSAGE),
            started_at=started_at,
            failed_at=failed_at,
        )
        store.replace(failed)
        return failed

    completed_at = datetime.now(UTC)
    completed = replace(
        analysis,
        state=AnalysisState.COMPLETED,
        dataset_profile=dataset_profile,
        findings=findings,
        priority_scores=priority_scores,
        evidence=evidence,
        trust_assessment=trust_assessment,
        started_at=started_at,
        completed_at=completed_at,
    )
    store.replace(completed)
    return completed


def get_status(store: AnalysisStore, analysis_id: str) -> Analysis:
    """Return the current `Analysis` for `analysis_id`.

    Raises `AnalysisNotFoundError` for an unknown ID.
    """
    analysis = store.get(analysis_id)
    if analysis is None:
        raise AnalysisNotFoundError(analysis_id)
    return analysis


def get_profile(store: AnalysisStore, analysis_id: str) -> DatasetProfile | None:
    """Return the `DatasetProfile` for a `COMPLETED` analysis, `None` for
    a known but not-yet-`COMPLETED` analysis.

    Raises `AnalysisNotFoundError` for an unknown ID.
    """
    return get_status(store, analysis_id).dataset_profile


def get_findings(store: AnalysisStore, analysis_id: str) -> tuple[FindingCandidate, ...]:
    """Return the findings tuple for a `COMPLETED` analysis, an empty
    tuple for a known but not-yet-`COMPLETED` analysis.

    Raises `AnalysisNotFoundError` for an unknown ID.
    """
    return get_status(store, analysis_id).findings


def get_finding(store: AnalysisStore, analysis_id: str, finding_id: str) -> FindingCandidate:
    """Return one `FindingCandidate` by its `finding_id` (`WP-027`).

    `finding_id` is a stringified zero-based index into the analysis's
    own `findings` tuple — a disclosed, reversible interim scheme
    (`FindingCandidate`'s own docstring already anticipates "a later
    package assigns a finding ID" once persistence exists); stable only
    within one in-memory analysis's own findings, matching this
    package's in-memory-only, no-persistence scope.

    Raises `AnalysisNotFoundError` for an unknown `analysis_id` and
    `FindingNotFoundError` for a non-numeric, negative, or out-of-range
    `finding_id` (including a known analysis not yet `COMPLETED`, whose
    `findings` tuple is still empty).
    """
    analysis = get_status(store, analysis_id)
    try:
        index = int(finding_id)
    except ValueError:
        raise FindingNotFoundError(analysis_id, finding_id) from None
    if index < 0 or index >= len(analysis.findings):
        raise FindingNotFoundError(analysis_id, finding_id)
    return analysis.findings[index]


def get_finding_evidence(
    store: AnalysisStore, analysis_id: str, finding_id: str
) -> tuple[Evidence, ...]:
    """Return the `Evidence` objects referenced by one finding's own
    `evidence_ids` (`WP-027`), resolved against `Analysis.evidence`, in
    the same order as `evidence_ids`.

    Raises `AnalysisNotFoundError`/`FindingNotFoundError` with the same
    semantics as `get_finding`.
    """
    analysis = get_status(store, analysis_id)
    finding = get_finding(store, analysis_id, finding_id)
    evidence_by_id = {item.evidence_id: item for item in analysis.evidence}
    return tuple(
        evidence_by_id[evidence_id]
        for evidence_id in finding.evidence_ids
        if evidence_id in evidence_by_id
    )


def get_finding_row_context(
    store: AnalysisStore,
    analysis_id: str,
    finding_id: str,
    *,
    anchor_row: int,
    before: int = 3,
    after: int = 3,
) -> RowContextWindow:
    """Return a bounded physical-neighborhood window around one finding's
    affected row (`FIND-01`, `docs/domain-model.md` §13, `docs/
    api-specification.md` §10).

    Reconstructs the window from `Analysis.content` via the existing
    `parsers.csv_parser.parse_csv` path on every call — CHG-001 Decision 5's
    starting approach — rather than retaining a `ParsedDataset` as standing
    analysis state.

    Raises `AnalysisNotFoundError`/`FindingNotFoundError` with the same
    semantics as `get_finding`, and `RowNotInFindingError` when `anchor_row`
    does not equal the `row_number` of any of the finding's own
    `affected_row_references` (including a finding with zero affected rows).
    `before`/`after` are clamped to `[0, _MAX_ROW_CONTEXT_WINDOW_PER_SIDE]`
    and to the file's own start/end — never rejected — with
    `truncated_at_start`/`truncated_at_end` reporting whichever bound (or
    both) actually applied.
    """
    analysis = get_status(store, analysis_id)
    finding = get_finding(store, analysis_id, finding_id)

    affected_row_numbers = {reference.row_number for reference in finding.affected_row_references}
    if anchor_row not in affected_row_numbers:
        raise RowNotInFindingError(analysis_id, finding_id, anchor_row)

    parsed = parse_csv(analysis.content)
    columns = parsed.parsed_dataset.columns
    rows = parsed.rows
    row_count = parsed.parsed_dataset.row_count

    max_window = _MAX_ROW_CONTEXT_WINDOW_PER_SIDE
    bounded_before = max(0, before)
    bounded_after = max(0, after)

    actual_before = min(bounded_before, max_window, anchor_row)
    actual_after = min(bounded_after, max_window, row_count - 1 - anchor_row)

    start = anchor_row - actual_before
    end = anchor_row + actual_after

    entries = tuple(
        RowContextEntry(
            row_reference=RowReference(row_number=row_number),
            is_anchor=(row_number == anchor_row),
            is_affected_by_finding=(row_number in affected_row_numbers),
            values=rows[row_number],
        )
        for row_number in range(start, end + 1)
    )

    return RowContextWindow(
        columns=columns,
        requested_before=bounded_before,
        requested_after=bounded_after,
        actual_before=actual_before,
        actual_after=actual_after,
        truncated_at_start=actual_before < bounded_before,
        truncated_at_end=actual_after < bounded_after,
        max_window=max_window,
        rows=entries,
    )


def cancel_analysis(store: AnalysisStore, analysis_id: str) -> Analysis:
    """Cancel a `QUEUED` analysis, transitioning it to `CANCELLED`.

    For any other known state, returns the `Analysis` unchanged (no
    exception) — `cancel_analysis` is only effective while `QUEUED`; true
    mid-pipeline cancellation requires real bounded background execution
    (`JOB-01`, not yet built).

    Raises `AnalysisNotFoundError` for an unknown ID.
    """
    analysis = store.get(analysis_id)
    if analysis is None:
        raise AnalysisNotFoundError(analysis_id)
    if analysis.state is not AnalysisState.QUEUED:
        return analysis

    cancelled_at = datetime.now(UTC)
    cancelled = replace(analysis, state=AnalysisState.CANCELLED, cancelled_at=cancelled_at)
    store.replace(cancelled)
    return cancelled


def _require_completed(store: AnalysisStore, analysis_id: str) -> Analysis:
    analysis = get_status(store, analysis_id)
    if analysis.state is not AnalysisState.COMPLETED:
        raise AnalysisNotReadyError(analysis_id)
    return analysis


def get_or_infer_context(store: AnalysisStore, analysis_id: str) -> DatasetContext:
    """Return `analysis_id`'s `DatasetContext`, computing and caching it
    on first call for a `COMPLETED` analysis (`API-02`, `WP-059`).

    Deterministic only — uses `CTX-01`'s `infer_dataset_context` over the
    analysis's already-computed `dataset_profile` and `CTX-03`'s
    `generate_guided_questions`. `CTX-02`'s AI augmentation is
    deliberately not invoked (see this module's own docstring). Returns
    the same cached `DatasetContext` on every subsequent call without
    recomputing.

    Raises `AnalysisNotFoundError` for an unknown ID and
    `AnalysisNotReadyError` for a known but not-yet-`COMPLETED` analysis.
    """
    analysis = _require_completed(store, analysis_id)
    if analysis.context is not None:
        return analysis.context

    assert analysis.dataset_profile is not None  # guaranteed by COMPLETED invariant
    context = infer_dataset_context(analysis.dataset_profile)
    questions = generate_guided_questions(context)
    updated = replace(analysis, context=context, guided_questions=questions, context_version=1)
    store.replace(updated)
    return context


def apply_ai_context_augmentation(
    store: AnalysisStore, analysis_id: str, augmented_context: DatasetContext
) -> DatasetContext:
    """Persist an AI-augmented `DatasetContext` the caller already
    computed (`UI-02` slice 2 revision, `WP-064` r2; `docs/decision-log.md`
    D-037's "configured AI context inference can participate in the
    Context flow" requirement).

    This module never calls `CTX-02`/`ai_provider` itself (see this
    module's own docstring's structural guarantee) — the API route layer
    computes `augmented_context` (via `context_inference.ai_context`)
    and hands the finished value here purely for persistence, exactly
    mirroring `get_or_infer_context`'s own "compute once" first-inference
    snapshot. Does not increment `context_version` — this refines the
    same first-inference snapshot `get_or_infer_context` just produced,
    it is not a user edit (`confirm_context_fields`/`answer_guided_question`
    own that concern separately).

    Only valid immediately after `get_or_infer_context`'s first call
    (`context_version == 1`, `context_finalized is False`) — raises
    `ValueError` otherwise, refusing to silently overwrite a
    user-confirmed/corrected or already-finalized context.

    Raises `AnalysisNotFoundError` for an unknown ID.
    """
    analysis = get_status(store, analysis_id)
    if analysis.context_version != 1 or analysis.context_finalized:
        raise ValueError(
            "apply_ai_context_augmentation: only valid immediately after the first "
            "get_or_infer_context call (context_version == 1, not yet finalized) — "
            f"analysis {analysis_id} has context_version={analysis.context_version}, "
            f"context_finalized={analysis.context_finalized}"
        )
    updated = replace(analysis, context=augmented_context)
    store.replace(updated)
    return augmented_context


def get_guided_questions(
    store: AnalysisStore, analysis_id: str
) -> tuple[ClarificationQuestion, ...]:
    """Return `analysis_id`'s guided questions, inferring context first
    if not yet done (`API-02`, `WP-059`).

    Raises the same errors as `get_or_infer_context`.
    """
    get_or_infer_context(store, analysis_id)
    analysis = get_status(store, analysis_id)
    return analysis.guided_questions


def _confirmed_or_corrected(current_value: str, new_value: str) -> Provenance:
    return Provenance.USER_CONFIRMED if current_value == new_value else Provenance.USER_CORRECTED


def confirm_context_fields(
    store: AnalysisStore,
    analysis_id: str,
    edits: Mapping[ContextField, str],
    *,
    expected_version: int,
) -> DatasetContext:
    """Replace one or more editable `ContextField` values with
    user-supplied values in one version-checked call (`API-02`,
    `WP-059`, `docs/api-specification.md` §9's "PUT context").

    Only the five single-value fields in `_EDITABLE_CONTEXT_FIELDS` may
    be edited — the four "role" fields raise
    `ContextFieldNotEditableError`. Each edited field's `Provenance`/
    `ConfirmationState` become `USER_CONFIRMED`/`CONFIRMED` when the
    supplied value matches the field's current value, or
    `USER_CORRECTED`/`CORRECTED` otherwise. `context_version` is
    incremented by exactly `1` regardless of how many fields were
    edited.

    Raises `AnalysisNotFoundError`/`AnalysisNotReadyError` (via
    `get_or_infer_context`), `ContextVersionConflictError` when
    `expected_version` does not match the analysis's current
    `context_version`, and `ContextFieldNotEditableError` for a role
    field.
    """
    if not edits:
        raise ValueError("confirm_context_fields: edits must not be empty")

    get_or_infer_context(store, analysis_id)
    analysis = get_status(store, analysis_id)
    if analysis.context_version != expected_version:
        raise ContextVersionConflictError(analysis_id, expected_version, analysis.context_version)

    assert analysis.context is not None  # guaranteed by get_or_infer_context above
    context = analysis.context
    field_updates: dict[str, ContextFieldValue] = {}
    for context_field, new_value in edits.items():
        if context_field not in _EDITABLE_CONTEXT_FIELDS:
            raise ContextFieldNotEditableError(analysis_id, context_field)
        current = getattr(context, context_field.value)
        provenance = _confirmed_or_corrected(current.value, new_value)
        confirmation_state = (
            ConfirmationState.CONFIRMED
            if provenance is Provenance.USER_CONFIRMED
            else ConfirmationState.CORRECTED
        )
        field_updates[context_field.value] = ContextFieldValue(
            value=new_value,
            confidence=1.0,
            inference_source=provenance,
            confirmation_state=confirmation_state,
            evidence_ids=current.evidence_ids,
        )

    updated_context = replace(context, **field_updates)  # type: ignore[arg-type]
    updated_analysis = replace(
        analysis, context=updated_context, context_version=analysis.context_version + 1
    )
    store.replace(updated_analysis)
    return updated_context


def answer_guided_question(
    store: AnalysisStore,
    analysis_id: str,
    question_id: str,
    *,
    answer_text: str,
    expected_version: int,
) -> tuple[DatasetContext, ClarificationQuestion, ClarificationAnswer]:
    """Store an answer to one guided question and update the
    corresponding `ContextField` (`API-02`, `WP-059`,
    `docs/api-specification.md` §9's "stores an answer and resulting
    context updates").

    `answer_text` matching one of the question's own `suggested_answers`
    is recorded as `Provenance.USER_CONFIRMED`; any other value
    (including free text) is recorded as `Provenance.USER_CORRECTED`.
    Marks the question `answered_state = ANSWERED` and increments
    `context_version` by `1`.

    Raises `AnalysisNotFoundError`/`AnalysisNotReadyError` (via
    `get_or_infer_context`), `ContextVersionConflictError` on a version
    mismatch, and `QuestionNotFoundError` for an unknown `question_id`.
    """
    get_or_infer_context(store, analysis_id)
    analysis = get_status(store, analysis_id)
    if analysis.context_version != expected_version:
        raise ContextVersionConflictError(analysis_id, expected_version, analysis.context_version)

    question = next((q for q in analysis.guided_questions if q.question_id == question_id), None)
    if question is None:
        raise QuestionNotFoundError(analysis_id, question_id)

    assert analysis.context is not None  # guaranteed by get_or_infer_context above
    context = analysis.context
    current = getattr(context, question.context_field.value)
    provenance = (
        Provenance.USER_CONFIRMED
        if answer_text in question.suggested_answers
        else Provenance.USER_CORRECTED
    )
    confirmation_state = (
        ConfirmationState.CONFIRMED
        if provenance is Provenance.USER_CONFIRMED
        else ConfirmationState.CORRECTED
    )
    new_field_value = ContextFieldValue(
        value=answer_text,
        confidence=1.0,
        inference_source=provenance,
        confirmation_state=confirmation_state,
        evidence_ids=current.evidence_ids,
    )
    updated_context = replace(context, **{question.context_field.value: new_field_value})  # type: ignore[arg-type]

    updated_question = replace(question, answered_state=QuestionAnsweredState.ANSWERED)
    updated_questions = tuple(
        updated_question if q.question_id == question_id else q for q in analysis.guided_questions
    )

    answer = ClarificationAnswer(
        question_id=question_id,
        selected_answer_or_free_text=answer_text,
        answered_timestamp=datetime.now(UTC),
        resulting_context_changes=(question.context_field,),
        provenance=provenance,
    )

    updated_analysis = replace(
        analysis,
        context=updated_context,
        guided_questions=updated_questions,
        context_version=analysis.context_version + 1,
    )
    store.replace(updated_analysis)
    return updated_context, updated_question, answer


def finalize_context(store: AnalysisStore, analysis_id: str, *, expected_version: int) -> Analysis:
    """Mark `analysis_id`'s context finalized (`API-02`, `WP-059`,
    `docs/api-specification.md` §9's `POST .../finalize`).

    Honestly does not "trigger context-dependent analysis and optional
    AI interpretation" beyond setting `context_finalized = True` — no
    context-dependent detector exists anywhere in this codebase yet, and
    `CTX-02`'s AI augmentation is deliberately not invoked here (see this
    module's own docstring). Does not change `context`/
    `guided_questions`/`context_version`.

    Raises `AnalysisNotFoundError`/`AnalysisNotReadyError` (via
    `get_or_infer_context`) and `ContextVersionConflictError` on a
    version mismatch.
    """
    get_or_infer_context(store, analysis_id)
    analysis = get_status(store, analysis_id)
    if analysis.context_version != expected_version:
        raise ContextVersionConflictError(analysis_id, expected_version, analysis.context_version)

    finalized = replace(analysis, context_finalized=True)
    store.replace(finalized)
    return finalized
