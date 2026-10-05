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
import threading
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Protocol

from ..context_inference.guided_questions import generate_guided_questions
from ..context_inference.heuristics import infer_dataset_context
from ..demo_data import SEED, generate
from ..detectors.catalogue import DETECTORS
from ..detectors.contract import FindingCandidate, SecurityExposureState
from ..detectors.engine import run_detectors
from ..domain.ai_enrichment import (
    AiEnrichmentRecord,
    EnrichmentModelLocation,
    EnrichmentOutcome,
)
from ..domain.clarification import (
    ClarificationAnswer,
    ClarificationQuestion,
    QuestionAnsweredState,
)
from ..domain.context import ConfirmationState, ContextField, ContextFieldValue, DatasetContext
from ..domain.evidence import Evidence
from ..domain.explanation import ValidationRuleType
from ..domain.ingest_facts import project_ingest_facts
from ..domain.parsing import Dataset, DatasetFormat, DatasetSourceType
from ..domain.review import FindingReview, FindingReviewState
from ..domain.row_context import RowContextEntry, RowContextWindow
from ..domain.rules import (
    ComparisonOperator,
    NullHandling,
    RuleExecutionResult,
    RuleProvenance,
    ValidationRule,
)
from ..domain.value_objects import ColumnReference, Provenance, RowReference, Severity
from ..parsers.csv_parser import CsvParseResult, parse_csv
from ..parsers.xlsx_parser import XlsxParseResult, parse_xlsx
from ..profiling.metrics import compute_dataset_profile
from ..profiling.schemas import DatasetProfile
from ..risk.scoring import (
    TrustAssessment,
    calculate_finding_priority_scores,
    calculate_trust_assessment,
)
from ..rules import generation as rule_generation
from ..rules.engine import execute_rule as _execute_rule
from .parse_limits import csv_parse_limits, xlsx_parse_limits

#: Schema version stamped on every newly created `ValidationRule`
#: (`RULE-01` slice 1) — mirrors `ai_boundary.finding_analysis`'s own
#: `FINDING_ANALYSIS_SCHEMA_VERSION` convention for future evolution.
RULE_SCHEMA_VERSION = "validation_rule_v1"

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
    rules: tuple[ValidationRule, ...] = ()
    """User-defined validation rules (`RULE-01` slice 1) — a strictly
    additive layer over an already-`COMPLETED` analysis, exactly like
    `context`/`guided_questions` above: computed and mutated entirely
    independently of `state`. Empty unless `state is COMPLETED`."""
    finding_reviews: Mapping[str, FindingReview] = MappingProxyType({})
    """Per-finding review state (`REV-01`, `WP-083`), keyed by the same
    stringified `finding_id` `get_finding` already uses — a strictly
    additive layer, exactly like `rules` above. A finding with no entry
    here is implicitly unreviewed with no note; this mapping never
    stores that default explicitly. `FindingCandidate` itself
    (`self.findings`) is never mutated by a review."""
    retry_source_analysis_id: str | None = None
    """The originating `analysis_id` when this analysis is itself a retry
    (`JOB-01` slice 2: retry creates a new, independent `Analysis`, never
    a versioned attempt reusing the same `analysis_id`). `None` for every
    analysis that is not a retry — every prior caller of `create_analysis`/
    `create_analysis_from_upload`/this dataclass's own constructor is
    unaffected (defaults to `None`). Set exactly once, at construction,
    by `retry_analysis` below; never mutated afterward."""
    ai_enrichment: AiEnrichmentRecord | None = AiEnrichmentRecord()
    """Counters of optional AI enrichment calls (`EXP-01` slice 4). A new
    analysis starts with the zero record; `None` means the analysis was
    persisted before recording existed, i.e. *not recorded* (never *no
    calls*). Updated only by `record_ai_enrichment_call`."""

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
            if self.rules:
                raise ValueError("Analysis: rules must be empty unless state is COMPLETED")
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

        if self.retry_source_analysis_id == self.analysis_id:
            raise ValueError("Analysis.retry_source_analysis_id must not equal its own analysis_id")


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


class AnalysisNotRetryableError(Exception):
    """Raised by `retry_analysis` (`JOB-01` slice 2, `WP-076`) for a known
    analysis not in the `FAILED` state — matching
    `docs/product-requirements.md`'s "retry failed work": only a `FAILED`
    analysis may be retried in this slice. A `CANCELLED` analysis is not
    itself retryable (a disclosed, reversible scope boundary — see
    `WP-076`'s own Non-goals); a client can simply create a new analysis
    normally instead.
    """

    def __init__(self, analysis_id: str, state: AnalysisState) -> None:
        super().__init__(f"Analysis not retryable in state {state.value}: {analysis_id}")
        self.analysis_id = analysis_id
        self.state = state


class UnknownRuleColumnError(Exception):
    """Raised by `create_rule` (`RULE-01` slice 1) when a requested column
    name does not match any of the analysis's own dataset columns."""

    def __init__(self, analysis_id: str, column_name: str) -> None:
        super().__init__(f"Unknown column {column_name!r} for analysis {analysis_id}")
        self.analysis_id = analysis_id
        self.column_name = column_name


class InvalidRuleParametersError(Exception):
    """Raised by `create_rule` (`RULE-01` slice 1) when the supplied
    parameters do not satisfy `domain.rules.ValidationRule`'s own
    `__post_init__` invariants for the requested `rule_type` — wraps the
    original `ValueError` message rather than re-deriving it."""

    def __init__(self, analysis_id: str, reason: str) -> None:
        super().__init__(f"Invalid rule parameters for analysis {analysis_id}: {reason}")
        self.analysis_id = analysis_id
        self.reason = reason


class InvalidReviewParametersError(Exception):
    """Raised by `set_finding_review` (`REV-01`, `WP-083`) when the
    requested `state`/`dismissal_reason` combination does not satisfy
    `domain.review.FindingReview`'s own `__post_init__` invariant — wraps
    the original `ValueError` message rather than re-deriving it."""

    def __init__(self, analysis_id: str, reason: str) -> None:
        super().__init__(f"Invalid review parameters for analysis {analysis_id}: {reason}")
        self.analysis_id = analysis_id
        self.reason = reason


class RuleNotFoundError(Exception):
    """Raised by `execute_rule_now`/`delete_rule` (`RULE-01` slice 1) for a
    `rule_id` that does not match any of the analysis's own `rules`."""

    def __init__(self, analysis_id: str, rule_id: str) -> None:
        super().__init__(f"Rule not found: {rule_id} (analysis {analysis_id})")
        self.analysis_id = analysis_id
        self.rule_id = rule_id


class AnalysisStoreProtocol(Protocol):
    """The store shape every function in this module actually depends on
    (`add`/`get`/`replace`) — a type-only extraction (`DB-01`, `WP-074`)
    letting `persistence.SqlAnalysisStore` stand in for the in-memory
    `AnalysisStore` below without either type depending on the other.
    Every function's `store` parameter in this module is typed against
    this `Protocol`, not the concrete `AnalysisStore` class; `AnalysisStore`
    itself is unchanged and every existing caller that constructs it
    directly continues to work unmodified (structural typing).
    """

    def add(self, analysis: Analysis) -> None: ...

    def get(self, analysis_id: str) -> Analysis | None: ...

    def replace(self, analysis: Analysis) -> None: ...

    def update_ai_enrichment(
        self,
        analysis_id: str,
        update: Callable[[AiEnrichmentRecord | None], AiEnrichmentRecord | None],
    ) -> None: ...

    def delete(self, analysis_id: str) -> bool:
        """Remove the analysis and everything stored with it; `False` when
        it did not exist. `replace` never re-creates a deleted analysis."""
        ...


class AnalysisStore:
    """A minimal in-memory dict-backed store. Whole-analysis writes have no
    concurrency safety (disclosed, matching this package's stated
    non-goals). `DB-01` adds a durable alternative,
    `persistence.SqlAnalysisStore`, structurally satisfying the same
    `AnalysisStoreProtocol` above.

    `Analysis.ai_enrichment` is owned by `update_ai_enrichment` alone
    (`EXP-01` slice 4): `replace` keeps the stored record and ignores the
    one on the analysis it is given, so a stale copy cannot revert a count.
    """

    def __init__(self) -> None:
        self._analyses: dict[str, Analysis] = {}
        self._enrichment_lock = threading.Lock()

    def add(self, analysis: Analysis) -> None:
        self._analyses[analysis.analysis_id] = analysis

    def get(self, analysis_id: str) -> Analysis | None:
        return self._analyses.get(analysis_id)

    def replace(self, analysis: Analysis) -> None:
        """Update an existing analysis; never inserts (`DEL-01`), so a late
        write for a deleted analysis is dropped."""
        with self._enrichment_lock:
            stored = self._analyses.get(analysis.analysis_id)
            if stored is None:
                return
            self._analyses[analysis.analysis_id] = replace(
                analysis, ai_enrichment=stored.ai_enrichment
            )

    def delete(self, analysis_id: str) -> bool:
        with self._enrichment_lock:
            return self._analyses.pop(analysis_id, None) is not None

    def update_ai_enrichment(
        self,
        analysis_id: str,
        update: Callable[[AiEnrichmentRecord | None], AiEnrichmentRecord | None],
    ) -> None:
        with self._enrichment_lock:
            stored = self._analyses.get(analysis_id)
            if stored is not None:
                self._analyses[analysis_id] = replace(
                    stored, ai_enrichment=update(stored.ai_enrichment)
                )


def _generate_demo_content() -> bytes:
    """Generate the bundled demo dataset's CSV bytes in-memory —
    deterministic, byte-identical to the committed
    `demo-data/sales_demo.csv` (`DEMO-01`'s own drift-check precedent).
    No filesystem read occurs.
    """
    generated = generate(seed=SEED)
    return generated.to_csv_text().encode("utf-8")


def create_analysis(store: AnalysisStoreProtocol) -> Analysis:
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


def _parse_analysis_content(analysis: Analysis) -> CsvParseResult | XlsxParseResult:
    """Parse `analysis.content` according to its dataset's format.

    The single place every pipeline stage reads the stored file bytes, so
    no stage can parse a workbook as CSV or read a different worksheet
    than the one recorded on the dataset (`ING-03`). An XLSX dataset is
    always read from its recorded `selected_worksheet`; a missing one is
    refused rather than defaulted, because the upload step records it.
    """
    if analysis.dataset.format is DatasetFormat.XLSX:
        worksheet = analysis.dataset.selected_worksheet
        if worksheet is None:
            raise ValueError("XLSX analysis has no selected worksheet")
        return parse_xlsx(analysis.content, worksheet=worksheet, limits=xlsx_parse_limits())
    return parse_csv(analysis.content, limits=csv_parse_limits())


def create_analysis_from_upload(
    store: AnalysisStoreProtocol,
    *,
    content: bytes,
    original_filename: str,
    dataset_format: DatasetFormat = DatasetFormat.CSV,
    selected_worksheet: str | None = None,
) -> Analysis:
    """Create a new `QUEUED` analysis over an uploaded CSV or XLSX file's
    raw bytes and store it (`UI-01`/`API-01`, extending, `WP-029`;
    `ING-03`). Does not run the pipeline — see `run_analysis`.

    An XLSX upload must name the worksheet to analyze
    (`selected_worksheet`); a CSV upload must not.

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
    if (dataset_format is DatasetFormat.XLSX) != (selected_worksheet is not None):
        raise ValueError("selected_worksheet is required for XLSX and not allowed for CSV")
    stored_filename = f"{dataset_id}.{dataset_format.value}"

    dataset = Dataset(
        dataset_id=dataset_id,
        original_filename=original_filename,
        stored_filename=stored_filename,
        format=dataset_format,
        byte_size=byte_size,
        content_hash=content_hash,
        selected_worksheet=selected_worksheet,
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
    store: AnalysisStoreProtocol,
    analysis_id: str,
    *,
    now: datetime | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> Analysis:
    """Run the full pipeline for a `QUEUED` analysis, transitioning it
    through `PARSING`/`PROFILING`/`DETECTING` to `COMPLETED`.

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

    `cancel_check` (`JOB-01`, `WP-075`) is an optional callback consulted
    at four checkpoints — before `PARSING` starts, and after each of
    `PARSING`/`PROFILING`/`DETECTING` finishes (the last of these is
    consulted immediately before the analysis would otherwise be
    persisted `COMPLETED`, so a cancellation requested during the final
    stage is never silently missed). The first time it returns `True`,
    the analysis is persisted `CANCELLED` (with `cancelled_at` set) and
    this function returns immediately. `None` (the default) preserves
    this function's exact prior behavior — every existing direct caller
    is unaffected. Each stage transition is persisted to `store`
    *before* that stage runs, so `store.get(analysis_id)` observes real
    progress during a long-running call — the mechanism `JobPool` relies
    on to make `GET /status` genuinely reflect an in-flight analysis.

    Raises `AnalysisNotFoundError` for an unknown `analysis_id`.
    """
    analysis = store.get(analysis_id)
    if analysis is None:
        raise AnalysisNotFoundError(analysis_id)
    if analysis.state is not AnalysisState.QUEUED:
        return analysis

    effective_now = now if now is not None else datetime.now(UTC)
    started_at = datetime.now(UTC)

    def _cancelled_if_requested(current: Analysis) -> Analysis | None:
        if cancel_check is None or not cancel_check():
            return None
        cancelled = replace(
            current,
            state=AnalysisState.CANCELLED,
            started_at=started_at,
            cancelled_at=datetime.now(UTC),
        )
        store.replace(cancelled)
        return cancelled

    maybe_cancelled = _cancelled_if_requested(analysis)
    if maybe_cancelled is not None:
        return maybe_cancelled

    try:
        analysis = replace(analysis, state=AnalysisState.PARSING, started_at=started_at)
        store.replace(analysis)
        parsed = _parse_analysis_content(analysis)
        columns = parsed.parsed_dataset.columns

        maybe_cancelled = _cancelled_if_requested(analysis)
        if maybe_cancelled is not None:
            return maybe_cancelled

        analysis = replace(analysis, state=AnalysisState.PROFILING)
        store.replace(analysis)
        dataset_profile = compute_dataset_profile(
            columns,
            parsed.rows,
            parsed.parsed_dataset.sampling,
            as_of=effective_now.date(),
        )

        maybe_cancelled = _cancelled_if_requested(analysis)
        if maybe_cancelled is not None:
            return maybe_cancelled

        analysis = replace(analysis, state=AnalysisState.DETECTING)
        store.replace(analysis)
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
            ingest_facts=project_ingest_facts(parsed.parsed_dataset),
        )
        findings = tuple(finding for result in results for finding in result.findings)
        evidence = tuple(item for result in results for item in result.evidence)
        priority_scores = calculate_finding_priority_scores(
            findings, dataset_profile=dataset_profile
        )
        trust_assessment = calculate_trust_assessment(
            findings, priority_scores, security_exposure=analysis.security_exposure
        )

        maybe_cancelled = _cancelled_if_requested(analysis)
        if maybe_cancelled is not None:
            return maybe_cancelled
    except Exception:  # noqa: BLE001 - isolated per DET-01 engine.py precedent
        failed_at = datetime.now(UTC)
        failed = replace(
            analysis,
            state=AnalysisState.FAILED,
            dataset_profile=None,
            findings=(),
            priority_scores=(),
            evidence=(),
            trust_assessment=None,
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


def delete_analysis(store: AnalysisStoreProtocol, analysis_id: str) -> None:
    """Delete an analysis and everything stored with it (`DEL-01`,
    `docs/product-requirements.md` §8.8): the uploaded content, derived
    profile, context, questions, findings, evidence, rules, reviews, the
    AI enrichment record and every report.

    Irreversible. The caller is responsible for asking a running analysis
    to cancel first; a worker that is still running cannot bring the
    analysis back, because `replace` never inserts.

    Raises `AnalysisNotFoundError` for an unknown (or already deleted) ID.
    """
    if not store.delete(analysis_id):
        raise AnalysisNotFoundError(analysis_id)


def record_ai_enrichment_call(
    store: AnalysisStoreProtocol,
    analysis_id: str,
    *,
    outcome: EnrichmentOutcome,
    evidence_sent: bool,
    confirmed_context_sent: bool,
    location: EnrichmentModelLocation,
) -> None:
    """Add one attempted AI enrichment call to the analysis's record
    (`EXP-01` slice 4). Every route that can reach a model calls this.

    An analysis whose record is `None` (persisted before recording
    existed) is left as is: starting to count now would turn *not
    recorded* into a false *no other calls*. An unknown analysis is
    ignored.

    The record is updated through the store's own atomic
    `update_ai_enrichment`, never through a whole-analysis `replace`, and
    `replace` never overwrites it: a concurrent writer holding a stale copy
    of the analysis therefore cannot revert or drop a count.
    """

    def add_call(current: AiEnrichmentRecord | None) -> AiEnrichmentRecord | None:
        if current is None:
            return None
        return current.with_call(
            outcome,
            evidence_sent=evidence_sent,
            confirmed_context_sent=confirmed_context_sent,
            location=location,
        )

    store.update_ai_enrichment(analysis_id, add_call)


def get_status(store: AnalysisStoreProtocol, analysis_id: str) -> Analysis:
    """Return the current `Analysis` for `analysis_id`.

    Raises `AnalysisNotFoundError` for an unknown ID.
    """
    analysis = store.get(analysis_id)
    if analysis is None:
        raise AnalysisNotFoundError(analysis_id)
    return analysis


def get_profile(store: AnalysisStoreProtocol, analysis_id: str) -> DatasetProfile | None:
    """Return the `DatasetProfile` for a `COMPLETED` analysis, `None` for
    a known but not-yet-`COMPLETED` analysis.

    Raises `AnalysisNotFoundError` for an unknown ID.
    """
    return get_status(store, analysis_id).dataset_profile


def get_findings(store: AnalysisStoreProtocol, analysis_id: str) -> tuple[FindingCandidate, ...]:
    """Return the findings tuple for a `COMPLETED` analysis, an empty
    tuple for a known but not-yet-`COMPLETED` analysis.

    Raises `AnalysisNotFoundError` for an unknown ID.
    """
    return get_status(store, analysis_id).findings


def get_finding(
    store: AnalysisStoreProtocol, analysis_id: str, finding_id: str
) -> FindingCandidate:
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
    store: AnalysisStoreProtocol, analysis_id: str, finding_id: str
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


def set_finding_review(
    store: AnalysisStoreProtocol,
    analysis_id: str,
    finding_id: str,
    *,
    state: FindingReviewState,
    note: str | None,
    dismissal_reason: str | None,
    now: datetime,
) -> FindingReview:
    """Set (replacing any prior value) one finding's review record
    (`REV-01`, `WP-083`) and persist it immediately — unlike `RULE-02`'s
    rule proposals, a review has no separate offer/execute step; there is
    nothing to "run" against rows, only a decision to record.

    Raises `AnalysisNotFoundError`/`AnalysisNotReadyError` with the same
    semantics as `_require_completed`, `FindingNotFoundError` for an
    unknown `finding_id` (via `get_finding`), and
    `InvalidReviewParametersError` when `state`/`dismissal_reason` do not
    satisfy `domain.review.FindingReview`'s own invariant (wrapping the
    underlying `ValueError`) — nothing is persisted on that path.
    """
    analysis = _require_completed(store, analysis_id)
    get_finding(store, analysis_id, finding_id)  # existence check only
    try:
        review = FindingReview(
            finding_id=finding_id,
            state=state,
            note=note,
            dismissal_reason=dismissal_reason,
            reviewed_at=now,
        )
    except ValueError as exc:
        raise InvalidReviewParametersError(analysis_id, str(exc)) from exc

    updated_reviews = dict(analysis.finding_reviews)
    updated_reviews[finding_id] = review
    store.replace(replace(analysis, finding_reviews=MappingProxyType(updated_reviews)))
    return review


def get_finding_row_context(
    store: AnalysisStoreProtocol,
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

    parsed = _parse_analysis_content(analysis)
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


def cancel_analysis(store: AnalysisStoreProtocol, analysis_id: str) -> Analysis:
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


def retry_analysis(store: AnalysisStoreProtocol, analysis_id: str) -> Analysis:
    """Create a new, independent `QUEUED` analysis over a `FAILED`
    analysis's own dataset `content`, linked via `retry_source_analysis_id`
    (`JOB-01` slice 2: retry creates a new analysis, never a versioned
    attempt reusing the same `analysis_id`).

    Mirrors `create_analysis`/`create_analysis_from_upload`'s existing
    create-then-store-then-return-unstarted shape exactly: this function
    does not itself run the pipeline (`run_analysis`) or submit to a
    `JobPool` — that remains the caller's responsibility (`api/v1/
    analyses.py`'s route), matching those two functions' own established
    separation. The original analysis is read but never mutated —
    every existing immutable-terminal-facts invariant is unaffected.

    Raises `AnalysisNotFoundError` for an unknown `analysis_id` and
    `AnalysisNotRetryableError` for a known analysis not in the `FAILED`
    state.
    """
    original = get_status(store, analysis_id)
    if original.state is not AnalysisState.FAILED:
        raise AnalysisNotRetryableError(analysis_id, original.state)

    now = datetime.now(UTC)
    dataset_id = str(uuid.uuid4())
    stored_filename = f"{dataset_id}.{original.dataset.format.value}"
    storage_location = (
        _DEMO_STORAGE_LOCATION
        if original.dataset.source_type is DatasetSourceType.BUNDLED_DEMO
        else f"uploads/{dataset_id}/{stored_filename}"
    )
    dataset = Dataset(
        dataset_id=dataset_id,
        original_filename=original.dataset.original_filename,
        stored_filename=stored_filename,
        format=original.dataset.format,
        byte_size=original.dataset.byte_size,
        content_hash=original.dataset.content_hash,
        selected_worksheet=original.dataset.selected_worksheet,
        created_at=now,
        deleted_at=None,
        storage_location=storage_location,
        source_type=original.dataset.source_type,
    )
    retry = Analysis(
        analysis_id=str(uuid.uuid4()),
        dataset=dataset,
        content=original.content,
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
        retry_source_analysis_id=original.analysis_id,
    )
    store.add(retry)
    return retry


def _require_completed(store: AnalysisStoreProtocol, analysis_id: str) -> Analysis:
    analysis = get_status(store, analysis_id)
    if analysis.state is not AnalysisState.COMPLETED:
        raise AnalysisNotReadyError(analysis_id)
    return analysis


def create_rule(
    store: AnalysisStoreProtocol,
    analysis_id: str,
    *,
    name: str,
    description: str,
    severity: Severity,
    rule_type: ValidationRuleType,
    column_names: tuple[str, ...],
    null_handling: NullHandling = NullHandling.SKIP,
    accepted_values: tuple[str, ...] | None = None,
    minimum: float | None = None,
    maximum: float | None = None,
    minimum_date: date | None = None,
    maximum_date: date | None = None,
    pattern: str | None = None,
    threshold_percentage: float | None = None,
    tolerance: float | None = None,
    comparison_operator: ComparisonOperator | None = None,
    comparison_value: float | None = None,
    condition_operator: ComparisonOperator | None = None,
    condition_value: float | None = None,
    source_finding_id: str | None = None,
) -> ValidationRule:
    """Define a new `ValidationRule` (`RULE-01`; all 11 rule types as of
    slice 2, `WP-079`) against a `COMPLETED` analysis's real columns,
    execute it immediately against
    the analysis's actual parsed rows (`parse_csv(analysis.content)` —
    the same reconstruction-on-demand pattern `get_finding_row_context`/
    `retry_analysis` already use, never a sample), store the result on
    the rule, persist, and return the executed rule.

    `source_finding_id` (`RULE-02` slice 1, `WP-080`; AI-assisted
    extension, slice 2, `WP-081`) is optional: when given, the finding
    must exist on this analysis, and the persisted rule records
    `source_finding_ids=(source_finding_id,)` — the normal way a caller
    accepts a `generate_rule_proposal`/AI-assisted offer.

    Provenance is `RuleProvenance.AI_ASSISTED` only when that finding's
    own detector is one of `rules.generation.AI_ASSISTABLE_DETECTOR_IDS`
    (currently only `consistency.inconsistent_capitalization`) **and**
    the supplied `rule_type`/`accepted_values` genuinely match what an
    AI-assisted proposal for that exact finding could have produced —
    `rule_type=ACCEPTED_VALUES` with exactly one value, itself one of
    that finding's own re-derived `rules.generation.
    extract_ai_assist_candidates` (defense in depth, independent of
    whatever the route layer's own AI-output validator already checked:
    `provenance=ai_assisted` is a claim that AI genuinely chose this
    exact value, so it must never be attachable to an arbitrary
    caller-supplied value merely by naming an eligible finding — a
    mismatch raises `InvalidRuleParametersError` rather than silently
    persisting a false claim under any provenance). Every other
    `source_finding_id` — a detector-generatable finding, or an
    AI-assistable finding whose posted shape does not match a genuine
    AI-assisted candidate — records `RuleProvenance.DETECTOR_GENERATED`,
    unchanged from slice 1's own behavior. When `source_finding_id` is
    omitted (the default), behavior is unchanged:
    `provenance=RuleProvenance.USER_AUTHORED`, `source_finding_ids=()`.

    Raises `AnalysisNotFoundError`/`AnalysisNotReadyError` (via
    `_require_completed`), `FindingNotFoundError` for an unknown
    `source_finding_id`, `UnknownRuleColumnError` for any `column_names`
    entry that does not match a real dataset column, and
    `InvalidRuleParametersError` when the resulting shape violates
    `ValidationRule`'s own invariants for `rule_type`, or (AI-assistable
    findings only) does not genuinely match a real AI-assisted
    candidate for that finding (wraps the underlying `ValueError` in
    the former case; a plain message in the latter).
    """
    analysis = _require_completed(store, analysis_id)
    source_finding = None
    if source_finding_id is not None:
        # Raises FindingNotFoundError if absent; also resolved to decide
        # DETECTOR_GENERATED vs AI_ASSISTED provenance below.
        source_finding = get_finding(store, analysis_id, source_finding_id)
    parsed = _parse_analysis_content(analysis)
    columns_by_name: dict[str, ColumnReference] = {
        column.original_name: column for column in parsed.parsed_dataset.columns
    }
    resolved_columns: list[ColumnReference] = []
    for column_name in column_names:
        column = columns_by_name.get(column_name)
        if column is None:
            raise UnknownRuleColumnError(analysis_id, column_name)
        resolved_columns.append(column)

    if source_finding is None:
        provenance = RuleProvenance.USER_AUTHORED
    elif source_finding.detector_id in rule_generation.AI_ASSISTABLE_DETECTOR_IDS:
        # `provenance=ai_assisted` is a claim that AI genuinely chose this
        # exact value — verified against this finding's own re-derived
        # candidates, never trusted from the caller's word alone.
        source_evidence = get_finding_evidence(store, analysis_id, source_finding_id)  # type: ignore[arg-type]
        candidates = rule_generation.extract_ai_assist_candidates(source_finding, source_evidence)
        is_genuine_ai_assisted_shape = (
            candidates is not None
            and rule_type is ValidationRuleType.ACCEPTED_VALUES
            and accepted_values is not None
            and len(accepted_values) == 1
            and accepted_values[0] in candidates
        )
        if not is_genuine_ai_assisted_shape:
            raise InvalidRuleParametersError(
                analysis_id,
                "source_finding_id names an AI-assistable finding, but the supplied "
                "rule_type/accepted_values do not match a genuine AI-assisted candidate "
                "for that finding (accepted_values must be exactly one of the finding's "
                "own observed values) — provenance=ai_assisted may not be claimed "
                "otherwise",
            )
        provenance = RuleProvenance.AI_ASSISTED
    else:
        provenance = RuleProvenance.DETECTOR_GENERATED
    source_finding_ids = (source_finding_id,) if source_finding_id is not None else ()

    try:
        rule = ValidationRule(
            rule_id=str(uuid.uuid4()),
            schema_version=RULE_SCHEMA_VERSION,
            name=name,
            description=description,
            severity=severity,
            rule_type=rule_type,
            columns=tuple(resolved_columns),
            null_handling=null_handling,
            accepted_values=accepted_values,
            minimum=minimum,
            maximum=maximum,
            minimum_date=minimum_date,
            maximum_date=maximum_date,
            pattern=pattern,
            threshold_percentage=threshold_percentage,
            tolerance=tolerance,
            comparison_operator=comparison_operator,
            comparison_value=comparison_value,
            condition_operator=condition_operator,
            condition_value=condition_value,
            source_finding_ids=source_finding_ids,
            provenance=provenance,
        )
    except ValueError as exc:
        raise InvalidRuleParametersError(analysis_id, str(exc)) from exc

    executed = _execute_rule(rule, parsed.rows, analysis_id=analysis_id, now=datetime.now(UTC))
    stored_rule = replace(rule, last_result=executed)
    updated_analysis = replace(analysis, rules=(*analysis.rules, stored_rule))
    store.replace(updated_analysis)
    return stored_rule


@dataclass(frozen=True, slots=True)
class GeneratedRuleOffer:
    """The result of `generate_rule_proposal` (`RULE-02` slice 1,
    `WP-080`): an already-executed, **unpersisted** candidate rule, or a
    stated reason none is available. `rule`/`result` are set together
    when `available` is `True`; both are `None` when `available` is
    `False`. Never stored on the analysis — accepting the offer is a
    separate, explicit `create_rule(..., source_finding_id=...)` call."""

    available: bool
    reason: str | None
    rule: ValidationRule | None
    result: RuleExecutionResult | None


def generate_rule_proposal(
    store: AnalysisStoreProtocol, analysis_id: str, finding_id: str
) -> GeneratedRuleOffer:
    """Build and execute (never persist) a deterministic candidate
    `ValidationRule` for one finding (`RULE-02` slice 1, `WP-080`,
    `rules.generation.generate_rule_proposal`), against the analysis's
    real parsed rows — the same reconstruction-on-demand pattern
    `create_rule` itself already uses. Every generated field is read
    verbatim from the finding's own already-computed `Evidence`; this
    function performs no new calculation and calls no AI.

    Raises `AnalysisNotFoundError`/`AnalysisNotReadyError`/
    `FindingNotFoundError` with the same semantics as `get_finding`.
    """
    analysis = _require_completed(store, analysis_id)
    finding = get_finding(store, analysis_id, finding_id)
    evidence = get_finding_evidence(store, analysis_id, finding_id)
    parsed = _parse_analysis_content(analysis)

    proposal, reason = rule_generation.generate_rule_proposal(
        finding, evidence, parsed.parsed_dataset.columns
    )
    if proposal is None:
        return GeneratedRuleOffer(available=False, reason=reason, rule=None, result=None)

    params = proposal.parameters
    try:
        rule = ValidationRule(
            rule_id=str(uuid.uuid4()),
            schema_version=RULE_SCHEMA_VERSION,
            name=proposal.name,
            description=proposal.description,
            severity=finding.severity,
            rule_type=proposal.rule_type,
            columns=proposal.columns,
            accepted_values=params.accepted_values,
            minimum=params.minimum,
            maximum=params.maximum,
            minimum_date=params.minimum_date,
            maximum_date=params.maximum_date,
            pattern=params.pattern,
            threshold_percentage=params.threshold_percentage,
            tolerance=params.tolerance,
            source_finding_ids=(finding_id,),
            provenance=RuleProvenance.DETECTOR_GENERATED,
        )
    except ValueError as exc:
        raise InvalidRuleParametersError(analysis_id, str(exc)) from exc

    executed = _execute_rule(rule, parsed.rows, analysis_id=analysis_id, now=datetime.now(UTC))
    offered_rule = replace(rule, last_result=executed)
    return GeneratedRuleOffer(available=True, reason=None, rule=offered_rule, result=executed)


class AiAssistanceNotAvailableError(Exception):
    """Raised by `build_ai_rule_generation_context` (`RULE-02` slice 2,
    `WP-081`) when `finding_id`'s detector is not one
    `rules.generation.AI_ASSISTABLE_DETECTOR_IDS` supports, or its
    referenced evidence does not carry the expected payload shape —
    the same "no safe proposal" honesty `generate_rule_proposal` already
    applies to the deterministic path, just for the AI-assisted one."""

    def __init__(self, analysis_id: str, finding_id: str) -> None:
        super().__init__(
            f"No AI-assisted rule candidates available for finding {finding_id} "
            f"(analysis {analysis_id})"
        )
        self.analysis_id = analysis_id
        self.finding_id = finding_id


@dataclass(frozen=True, slots=True)
class AiRuleGenerationContext:
    """Everything the route layer needs to attempt an AI-assisted rule
    proposal for one finding (`RULE-02` slice 2, `WP-081`) — built here
    so this module stays the single place that resolves a finding's
    real, current evidence, but never itself calls a provider (this
    module's own established provider-free guarantee — see this
    module's own docstring, `docs/decision-log.md` D-037/D-038).
    `candidates` is `finding`'s own already-observed evidence values, in
    the exact order/spelling an AI-assisted proposal may choose among."""

    finding: FindingCandidate
    evidence: tuple[Evidence, ...]
    candidates: tuple[str, ...]


def build_ai_rule_generation_context(
    store: AnalysisStoreProtocol, analysis_id: str, finding_id: str
) -> AiRuleGenerationContext:
    """Resolve `finding_id`'s own evidence and AI-assist candidate values
    (`rules.generation.extract_ai_assist_candidates`) for the route
    layer to build an AI provider request from.

    Raises `AnalysisNotFoundError`/`AnalysisNotReadyError`/
    `FindingNotFoundError` with the same semantics as `get_finding`, and
    `AiAssistanceNotAvailableError` when this finding's detector is not
    AI-assistable or its evidence lacks the expected shape.
    """
    _require_completed(store, analysis_id)
    finding = get_finding(store, analysis_id, finding_id)
    evidence = get_finding_evidence(store, analysis_id, finding_id)
    candidates = rule_generation.extract_ai_assist_candidates(finding, evidence)
    if candidates is None:
        raise AiAssistanceNotAvailableError(analysis_id, finding_id)
    return AiRuleGenerationContext(finding=finding, evidence=evidence, candidates=candidates)


def finalize_ai_assisted_rule(
    store: AnalysisStoreProtocol, analysis_id: str, finding_id: str, canonical_value: str
) -> GeneratedRuleOffer:
    """Build and execute (never persist) an AI-assisted candidate
    `ValidationRule` for one finding (`RULE-02` slice 2, `WP-081`), given
    `canonical_value` — a value an AI provider already chose, through
    the route layer, from exactly this finding's own AI-assist
    candidates. Re-derives and re-checks those candidates itself
    (defense in depth, independent of the route layer's own validated
    AI-output check) rather than trusting the caller's word that
    `canonical_value` is safe.

    Raises `AnalysisNotFoundError`/`AnalysisNotReadyError`/
    `FindingNotFoundError` with the same semantics as `get_finding`,
    `AiAssistanceNotAvailableError` when this finding's detector is not
    AI-assistable or its evidence lacks the expected shape, and
    `InvalidRuleParametersError` when `canonical_value` is not one of
    this finding's own re-derived candidates or the resulting shape
    violates `ValidationRule`'s own invariants.
    """
    analysis = _require_completed(store, analysis_id)
    finding = get_finding(store, analysis_id, finding_id)
    evidence = get_finding_evidence(store, analysis_id, finding_id)
    candidates = rule_generation.extract_ai_assist_candidates(finding, evidence)
    if candidates is None:
        raise AiAssistanceNotAvailableError(analysis_id, finding_id)
    if canonical_value not in candidates:
        raise InvalidRuleParametersError(
            analysis_id,
            f"canonical_value {canonical_value!r} is not one of this finding's own observed values",
        )
    parsed = _parse_analysis_content(analysis)

    try:
        rule = ValidationRule(
            rule_id=str(uuid.uuid4()),
            schema_version=RULE_SCHEMA_VERSION,
            name=f"AI-assisted rule for finding ({finding.detector_id})",
            description=(
                f"Values in the affected column should use the canonical spelling "
                f"and capitalization {canonical_value!r}."
            ),
            severity=finding.severity,
            rule_type=ValidationRuleType.ACCEPTED_VALUES,
            columns=finding.affected_columns,
            accepted_values=(canonical_value,),
            source_finding_ids=(finding_id,),
            provenance=RuleProvenance.AI_ASSISTED,
        )
    except ValueError as exc:
        raise InvalidRuleParametersError(analysis_id, str(exc)) from exc

    executed = _execute_rule(rule, parsed.rows, analysis_id=analysis_id, now=datetime.now(UTC))
    offered_rule = replace(rule, last_result=executed)
    return GeneratedRuleOffer(available=True, reason=None, rule=offered_rule, result=executed)


def _find_rule(analysis: Analysis, rule_id: str) -> ValidationRule:
    for rule in analysis.rules:
        if rule.rule_id == rule_id:
            return rule
    raise RuleNotFoundError(analysis.analysis_id, rule_id)


def execute_rule_now(
    store: AnalysisStoreProtocol, analysis_id: str, rule_id: str
) -> ValidationRule:
    """Re-run an existing rule against the analysis's current parsed rows
    and persist the refreshed result (`RULE-01` slice 1).

    Raises `AnalysisNotFoundError`/`AnalysisNotReadyError` and
    `RuleNotFoundError` for an unknown `rule_id`.
    """
    analysis = _require_completed(store, analysis_id)
    rule = _find_rule(analysis, rule_id)
    parsed = _parse_analysis_content(analysis)
    executed = _execute_rule(rule, parsed.rows, analysis_id=analysis_id, now=datetime.now(UTC))
    updated_rule = replace(rule, last_result=executed)
    updated_rules = tuple(
        updated_rule if existing.rule_id == rule_id else existing for existing in analysis.rules
    )
    store.replace(replace(analysis, rules=updated_rules))
    return updated_rule


def delete_rule(store: AnalysisStoreProtocol, analysis_id: str, rule_id: str) -> None:
    """Remove a rule from the analysis (`RULE-01` slice 1).

    Raises `AnalysisNotFoundError`/`AnalysisNotReadyError` and
    `RuleNotFoundError` for an unknown `rule_id`.
    """
    analysis = _require_completed(store, analysis_id)
    _find_rule(analysis, rule_id)  # raises RuleNotFoundError if absent
    remaining = tuple(rule for rule in analysis.rules if rule.rule_id != rule_id)
    store.replace(replace(analysis, rules=remaining))


def get_or_infer_context(store: AnalysisStoreProtocol, analysis_id: str) -> DatasetContext:
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
    store: AnalysisStoreProtocol, analysis_id: str, augmented_context: DatasetContext
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
    store: AnalysisStoreProtocol, analysis_id: str
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
    store: AnalysisStoreProtocol,
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
    store: AnalysisStoreProtocol,
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


def finalize_context(
    store: AnalysisStoreProtocol, analysis_id: str, *, expected_version: int
) -> Analysis:
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
