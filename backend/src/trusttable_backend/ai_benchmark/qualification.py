"""Finding-analysis qualification harness (`REL-02`, local-AI qualification
instrument, `docs/decision-log.md` D-043).

The `AI-06` harness (`runner.py`) scores the older narrative contract through
its own benchmark-only adapter. It cannot say how a local model behaves on the
path the product actually ships: the four-section `finding_analysis_v1`
analysis produced by `explanation.ai_explanation.run_finding_explanation`
through the real `LlamaCppProvider`, with the product's own retry bound and its
accept-or-fall-back decision. This module measures *that* path.

**Fidelity rule.** The harness contains no prompt text, output schema,
validator or retry logic. For every case it calls only the product's own
seams, exactly as the explanation route does:

- `confirmed_context_for_finding_analysis` — the context a request may carry;
- `build_finding_explanation_envelope` — the envelope the provider receives;
- `run_finding_explanation` — one structured call, role-aware validation,
  bounded retry with reason-code-only feedback, accept or fall back; and
- a provider supplied by the caller, which the CLI builds with the same
  `create_provider(...)` arguments the route uses.

It then only *observes*: harness-measured wall time (never the provider's
self-reported duration), each attempt's outcome, and a classification of the
final result. Nothing here decides what a user sees; the product does, and the
harness reports which of the four outcomes occurred.

**No thresholds.** This module reports facts. It defines no acceptance
threshold, selects no model and changes no default (`docs/decision-log.md`
D-032). What the numbers mean for `LLM_TIMEOUT_SECONDS` or a model choice is a
human decision made from a measured run (`REL-02` slice 2c).

**Privacy.** A result carries case ids (detector id and finding index),
outcomes, reason codes, exception *class* names and durations. It never
carries model output, exception message text, dataset values, the server URL or
an absolute host path; see `qualification_persistence`.

Percentiles use the nearest-rank rule: the p-th percentile of `n` sorted values
is the value at rank `ceil(p / 100 * n)` (1-based). With few cases the 95th
percentile is therefore the maximum; that is honest, not a defect.

Application-layer package: imports `analysis.service` to build the reference
analysis, like `fixtures.py`. No FastAPI/SQLAlchemy/pydantic import.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from time import perf_counter
from typing import Final

from ..ai_boundary.validation import RejectionReason
from ..ai_provider.contract import (
    AIProvider,
    ProviderHealth,
    ProviderRequest,
    ProviderResponse,
)
from ..ai_provider.display import sanitize_model_identifier
from ..analysis.service import (
    AnalysisState,
    AnalysisStore,
    confirm_context_fields,
    create_analysis,
    finalize_context,
    get_finding_evidence,
    get_or_infer_context,
    get_status,
    run_analysis,
)
from ..detectors.contract import FindingCandidate
from ..domain.context import ConfirmationState, ContextField
from ..domain.evidence import Evidence
from ..explanation.ai_explanation import (
    DEFAULT_MAX_RETRIES,
    FindingExplanationResult,
    build_finding_explanation_envelope,
    confirmed_context_for_finding_analysis,
    run_finding_explanation,
)

#: Bumped whenever the case set, its reference instant, or the fixed user
#: answers below change in a way a later comparison must be able to tell apart.
QUALIFICATION_CASE_SET_VERSION: Final[str] = "1"

#: The demo dataset's own reference date, so the same findings and evidence are
#: reproduced on every run and machine (matches `fixtures.py`).
_REFERENCE_INSTANT: Final[datetime] = datetime(2026, 8, 24, tzinfo=UTC)

#: The five single-value context fields a user can confirm or correct
#: (`analysis.service`'s editable set). The four role fields are never
#: user-confirmed and therefore never sent.
_EDITABLE_CONTEXT_FIELDS: Final[tuple[ContextField, ...]] = (
    ContextField.PROBABLE_DOMAIN,
    ContextField.ROW_GRAIN,
    ContextField.PRIMARY_ENTITY,
    ContextField.CURRENCY_BEHAVIOR,
    ContextField.EXPECTED_BUSINESS_RULES,
)

#: Fixed answers a user would give for a field the deterministic heuristics left
#: unknown. Part of the versioned case set: they make the confirmed-context
#: condition reproducible. They describe the bundled demo dataset only.
_FIXTURE_USER_ANSWERS: Final[Mapping[ContextField, str]] = {
    ContextField.PROBABLE_DOMAIN: "Sales order transactions",
    ContextField.ROW_GRAIN: "One row per order line",
    ContextField.PRIMARY_ENTITY: "order",
    ContextField.CURRENCY_BEHAVIOR: "All monetary amounts are in a single currency.",
    ContextField.EXPECTED_BUSINESS_RULES: (
        "Line total equals quantity times unit price, less discount, plus tax."
    ),
}


class Condition(StrEnum):
    """What context the analysis request carries."""

    EVIDENCE_ONLY = "evidence_only"
    """A context that has not been finalized: the request carries evidence only
    (the state of a first-time Finding Detail request)."""

    CONFIRMED_CONTEXT = "confirmed_context"
    """A finalized context: the request also carries the user-confirmed or
    corrected fields, and only those."""


class CaseScope(StrEnum):
    PER_DETECTOR = "per_detector"
    """The first finding of every detector that fired (default)."""

    ALL_FINDINGS = "all_findings"
    """Every finding of the reference analysis."""


class CaseOutcome(StrEnum):
    """Which of the four things a user would experience for one finding."""

    ACCEPTED_FIRST_ATTEMPT = "accepted_first_attempt"
    ACCEPTED_AFTER_RETRY = "accepted_after_retry"
    FELL_BACK_REJECTED = "fell_back_rejected"
    """Every attempt was rejected by the validator: built-in guidance shown."""

    FELL_BACK_PROVIDER_ERROR = "fell_back_provider_error"
    """The provider failed (timeout, connection, invalid response, or any
    unexpected error): built-in guidance shown."""


#: The explanation route's `ai_call_status` for each outcome. Kept beside the
#: outcome so a reader can correlate a result with what the UI disclosed; the
#: route-equivalence test proves the mapping against the real route.
PRODUCT_AI_CALL_STATUS: Final[Mapping[CaseOutcome, str]] = {
    CaseOutcome.ACCEPTED_FIRST_ATTEMPT: "attempted_accepted",
    CaseOutcome.ACCEPTED_AFTER_RETRY: "attempted_accepted",
    CaseOutcome.FELL_BACK_REJECTED: "attempted_rejected",
    CaseOutcome.FELL_BACK_PROVIDER_ERROR: "attempted_provider_error",
}


@dataclass(frozen=True, slots=True)
class QualificationCase:
    """One finding to analyse. Identifies the case by detector id and finding
    index only — never by a dataset value."""

    case_id: str
    detector_id: str
    finding_id: str
    finding: FindingCandidate = field(repr=False)
    evidence: tuple[Evidence, ...] = field(repr=False)


@dataclass(frozen=True, slots=True)
class QualificationSuite:
    """The reference cases plus the confirmed-context payload the product would
    send once the reference analysis's context is finalized."""

    scope: CaseScope
    cases: tuple[QualificationCase, ...]
    confirmed_context: Mapping[str, object] = field(repr=False)
    case_set_version: str = QUALIFICATION_CASE_SET_VERSION

    def __post_init__(self) -> None:
        if not self.cases:
            raise ValueError("QualificationSuite.cases must not be empty")
        if not self.confirmed_context:
            raise ValueError("QualificationSuite.confirmed_context must not be empty")


def build_qualification_suite(scope: CaseScope = CaseScope.PER_DETECTOR) -> QualificationSuite:
    """Run the bundled demo dataset through the real analysis pipeline at the
    fixed reference instant, confirm and finalize its context through the real
    context flow, and select the cases.

    The confirmed-context payload is computed by the product's own
    `confirmed_context_for_finding_analysis`, from the analysis's own context and
    finalized flag — the same call the explanation route makes.
    """
    store = AnalysisStore()
    created = create_analysis(store)
    analysis = run_analysis(store, created.analysis_id, now=_REFERENCE_INSTANT)
    if analysis.state is not AnalysisState.COMPLETED:
        raise RuntimeError("the reference demo analysis did not complete")

    context = get_or_infer_context(store, analysis.analysis_id)
    edits: dict[ContextField, str] = {}
    for context_field in _EDITABLE_CONTEXT_FIELDS:
        current = getattr(context, context_field.value)
        if current.confirmation_state is ConfirmationState.UNKNOWN:
            edits[context_field] = _FIXTURE_USER_ANSWERS[context_field]
        else:
            edits[context_field] = str(current.value)
    version = get_status(store, analysis.analysis_id).context_version
    confirm_context_fields(store, analysis.analysis_id, edits, expected_version=version)
    version = get_status(store, analysis.analysis_id).context_version
    finalized = finalize_context(store, analysis.analysis_id, expected_version=version)

    confirmed_context = confirmed_context_for_finding_analysis(
        finalized.context, finalized=finalized.context_finalized
    )
    if confirmed_context is None:
        raise RuntimeError("the reference context produced no confirmed fields")

    indexed = sorted(enumerate(finalized.findings), key=lambda pair: (pair[1].detector_id, pair[0]))
    seen_detectors: set[str] = set()
    cases: list[QualificationCase] = []
    for index, finding in indexed:
        if scope is CaseScope.PER_DETECTOR:
            if finding.detector_id in seen_detectors:
                continue
            seen_detectors.add(finding.detector_id)
        finding_id = str(index)
        cases.append(
            QualificationCase(
                case_id=f"{finding.detector_id}#{finding_id}",
                detector_id=finding.detector_id,
                finding_id=finding_id,
                finding=finding,
                evidence=get_finding_evidence(store, finalized.analysis_id, finding_id),
            )
        )
    return QualificationSuite(scope=scope, cases=tuple(cases), confirmed_context=confirmed_context)


@dataclass(frozen=True, slots=True)
class AttemptRecord:
    """One provider call, as the harness observed it."""

    duration_ms: float
    error_kind: str | None
    """The exception *class name* when the call raised, else `None`. Never the
    exception message (it can echo model output or a URL)."""

    def __post_init__(self) -> None:
        if self.duration_ms < 0:
            raise ValueError("AttemptRecord.duration_ms must not be negative")


class MeasuringProvider:
    """Wraps an `AIProvider`, timing every `complete()` call with the harness's
    own clock and recording how it ended, while behaving exactly like the
    wrapped provider for the product code that calls it: the response is
    returned unchanged and an exception propagates unchanged.

    The provider's self-reported `ProviderResponse.duration_ms` is ignored.
    Satisfies the `AIProvider` protocol structurally.
    """

    def __init__(self, inner: AIProvider, *, clock: Callable[[], float] = perf_counter) -> None:
        self._inner = inner
        self._clock = clock
        self._attempts: list[AttemptRecord] = []

    @property
    def provider_name(self) -> str:
        return self._inner.provider_name

    def health_check(self) -> ProviderHealth:
        return self._inner.health_check()

    def complete(self, request: ProviderRequest) -> ProviderResponse:
        start = self._clock()
        try:
            response = self._inner.complete(request)
        except Exception as exc:
            self._attempts.append(
                AttemptRecord(
                    duration_ms=(self._clock() - start) * 1000, error_kind=type(exc).__name__
                )
            )
            raise
        self._attempts.append(
            AttemptRecord(duration_ms=(self._clock() - start) * 1000, error_kind=None)
        )
        return response

    def take_attempts(self) -> tuple[AttemptRecord, ...]:
        """Return the attempts recorded since the last call and clear them."""
        taken = tuple(self._attempts)
        self._attempts.clear()
        return taken


@dataclass(frozen=True, slots=True)
class CaseResult:
    case_id: str
    detector_id: str
    condition: Condition
    outcome: CaseOutcome
    product_ai_call_status: str
    retries_used: int
    rejection_reasons: tuple[RejectionReason, ...]
    provider_error_kind: str | None
    attempts: tuple[AttemptRecord, ...]
    total_duration_ms: float
    """Wall time of the whole product call including retries, measured by the
    harness — what a user waits for this finding."""

    confirmed_context_sent: bool

    @property
    def accepted(self) -> bool:
        return self.outcome in (
            CaseOutcome.ACCEPTED_FIRST_ATTEMPT,
            CaseOutcome.ACCEPTED_AFTER_RETRY,
        )


def classify_result(
    result: FindingExplanationResult | None,
    attempts: Sequence[AttemptRecord],
    unexpected_error_kind: str | None,
) -> tuple[CaseOutcome, int, tuple[RejectionReason, ...], str | None]:
    """Classify what the product did, from the product's own result.

    Returns `(outcome, retries_used, final rejection reasons, provider error
    kind)`. `unexpected_error_kind` is set when `run_finding_explanation` itself
    raised — the explanation route swallows that and falls back, so it counts as
    a provider-error fallback here too.
    """
    if result is None:
        kind = unexpected_error_kind or "UnexpectedError"
        return CaseOutcome.FELL_BACK_PROVIDER_ERROR, max(len(attempts) - 1, 0), (), kind
    if result.accepted:
        outcome = (
            CaseOutcome.ACCEPTED_FIRST_ATTEMPT
            if result.retries_used == 0
            else CaseOutcome.ACCEPTED_AFTER_RETRY
        )
        return outcome, result.retries_used, (), None
    if result.provider_error is not None:
        kind = attempts[-1].error_kind if attempts and attempts[-1].error_kind else "ProviderError"
        return CaseOutcome.FELL_BACK_PROVIDER_ERROR, result.retries_used, (), kind
    return CaseOutcome.FELL_BACK_REJECTED, result.retries_used, result.rejection_reasons, None


@dataclass(frozen=True, slots=True)
class LatencySummary:
    count: int
    mean_ms: float
    p50_ms: float
    p95_ms: float
    max_ms: float


@dataclass(frozen=True, slots=True)
class QualificationAggregate:
    case_count: int
    accepted_count: int
    first_attempt_accepted_count: int
    fallback_count: int
    fill_rate: float
    """Cases where the AI analysis was shown / all cases."""

    first_attempt_fill_rate: float
    fallback_rate: float
    """Cases where built-in guidance was shown / all cases."""

    outcome_counts: Mapping[str, int]
    rejection_reason_counts: Mapping[str, int]
    provider_error_kind_counts: Mapping[str, int]
    retries_total: int
    attempt_count: int
    case_latency: LatencySummary
    slowest_attempt_ms: float
    slowest_completed_attempt_ms: float
    """The slowest attempt that did not raise. A timed-out attempt lasts about
    the configured timeout, so this is the number a timeout choice must clear."""


def percentile_nearest_rank(sorted_values: Sequence[float], percentile: float) -> float:
    """Nearest-rank percentile of an ascending sequence; `0.0` when empty."""
    if not sorted_values:
        return 0.0
    rank = max(math.ceil(percentile / 100 * len(sorted_values)), 1)
    return float(sorted_values[min(rank, len(sorted_values)) - 1])


def summarize_latency(values: Sequence[float]) -> LatencySummary:
    ordered = sorted(values)
    count = len(ordered)
    return LatencySummary(
        count=count,
        mean_ms=(sum(ordered) / count) if count else 0.0,
        p50_ms=percentile_nearest_rank(ordered, 50),
        p95_ms=percentile_nearest_rank(ordered, 95),
        max_ms=float(ordered[-1]) if ordered else 0.0,
    )


def aggregate_results(results: Sequence[CaseResult]) -> QualificationAggregate:
    case_count = len(results)
    accepted = sum(1 for r in results if r.accepted)
    first_attempt = sum(1 for r in results if r.outcome is CaseOutcome.ACCEPTED_FIRST_ATTEMPT)
    outcome_counts = Counter(r.outcome.value for r in results)
    reasons = Counter(reason.value for r in results for reason in r.rejection_reasons)
    error_kinds = Counter(r.provider_error_kind for r in results if r.provider_error_kind)
    attempts = [attempt for r in results for attempt in r.attempts]
    completed = [a.duration_ms for a in attempts if a.error_kind is None]
    return QualificationAggregate(
        case_count=case_count,
        accepted_count=accepted,
        first_attempt_accepted_count=first_attempt,
        fallback_count=case_count - accepted,
        fill_rate=(accepted / case_count) if case_count else 0.0,
        first_attempt_fill_rate=(first_attempt / case_count) if case_count else 0.0,
        fallback_rate=((case_count - accepted) / case_count) if case_count else 0.0,
        outcome_counts={o.value: outcome_counts.get(o.value, 0) for o in CaseOutcome},
        rejection_reason_counts=dict(sorted(reasons.items())),
        provider_error_kind_counts=dict(sorted(error_kinds.items())),
        retries_total=sum(r.retries_used for r in results),
        attempt_count=len(attempts),
        case_latency=summarize_latency([r.total_duration_ms for r in results]),
        slowest_attempt_ms=max((a.duration_ms for a in attempts), default=0.0),
        slowest_completed_attempt_ms=max(completed, default=0.0),
    )


@dataclass(frozen=True, slots=True)
class QualificationConfig:
    """Run-time settings that are *recorded*, not enforced, except `conditions`.

    `configured_timeout_seconds` is the provider timeout the caller configured,
    stored so a reader can compare it with the observed latencies. The retry
    bound is not configurable: it is the product's own (`DEFAULT_MAX_RETRIES`).
    """

    conditions: tuple[Condition, ...] = (Condition.EVIDENCE_ONLY, Condition.CONFIRMED_CONTEXT)
    configured_timeout_seconds: float | None = None
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.conditions:
            raise ValueError("QualificationConfig.conditions must not be empty")
        if len(set(self.conditions)) != len(self.conditions):
            raise ValueError("QualificationConfig.conditions must not repeat a condition")
        if self.configured_timeout_seconds is not None and self.configured_timeout_seconds <= 0:
            raise ValueError("QualificationConfig.configured_timeout_seconds must be positive")


@dataclass(frozen=True, slots=True)
class QualificationReport:
    provider_name: str
    model_identifier: str | None
    """Sanitized: the final path segment only (`ai_provider.display`)."""

    server_available_at_start: bool
    case_set_version: str
    scope: CaseScope
    conditions: tuple[Condition, ...]
    max_retries: int
    configured_timeout_seconds: float | None
    notes: str
    case_results: tuple[CaseResult, ...]
    aggregate: QualificationAggregate
    aggregate_by_condition: Mapping[str, QualificationAggregate]


def run_qualification(
    provider: AIProvider,
    suite: QualificationSuite,
    *,
    config: QualificationConfig | None = None,
    clock: Callable[[], float] = perf_counter,
    on_case_complete: Callable[[CaseResult], None] | None = None,
) -> QualificationReport:
    """Run every case under every configured condition through the product's own
    finding-analysis path and return the observed report.

    Never raises for a provider failure: every failure mode is one of the four
    outcomes. `on_case_complete` is called after each case (the CLI uses it for
    progress).
    """
    cfg = config if config is not None else QualificationConfig()
    health = provider.health_check()
    measuring = MeasuringProvider(provider, clock=clock)
    results: list[CaseResult] = []
    for condition in cfg.conditions:
        context = suite.confirmed_context if condition is Condition.CONFIRMED_CONTEXT else None
        for case in suite.cases:
            envelope = build_finding_explanation_envelope(
                case.finding, case.evidence, confirmed_context=context
            )
            measuring.take_attempts()
            start = clock()
            result: FindingExplanationResult | None
            unexpected: str | None = None
            try:
                result = run_finding_explanation(measuring, envelope, case.evidence)
            except Exception as exc:
                result = None
                unexpected = type(exc).__name__
            total_ms = (clock() - start) * 1000
            attempts = measuring.take_attempts()
            outcome, retries, reasons, error_kind = classify_result(result, attempts, unexpected)
            case_result = CaseResult(
                case_id=case.case_id,
                detector_id=case.detector_id,
                condition=condition,
                outcome=outcome,
                product_ai_call_status=PRODUCT_AI_CALL_STATUS[outcome],
                retries_used=retries,
                rejection_reasons=reasons,
                provider_error_kind=error_kind,
                attempts=attempts,
                total_duration_ms=total_ms,
                confirmed_context_sent=context is not None,
            )
            results.append(case_result)
            if on_case_complete is not None:
                on_case_complete(case_result)

    return QualificationReport(
        provider_name=provider.provider_name,
        model_identifier=sanitize_model_identifier(health.model_identifier),
        server_available_at_start=health.available,
        case_set_version=suite.case_set_version,
        scope=suite.scope,
        conditions=cfg.conditions,
        max_retries=DEFAULT_MAX_RETRIES,
        configured_timeout_seconds=cfg.configured_timeout_seconds,
        notes=cfg.notes,
        case_results=tuple(results),
        aggregate=aggregate_results(results),
        aggregate_by_condition={
            condition.value: aggregate_results([r for r in results if r.condition is condition])
            for condition in cfg.conditions
        },
    )


__all__ = [
    "PRODUCT_AI_CALL_STATUS",
    "QUALIFICATION_CASE_SET_VERSION",
    "AttemptRecord",
    "CaseOutcome",
    "CaseResult",
    "CaseScope",
    "Condition",
    "LatencySummary",
    "MeasuringProvider",
    "QualificationAggregate",
    "QualificationCase",
    "QualificationConfig",
    "QualificationReport",
    "QualificationSuite",
    "aggregate_results",
    "build_qualification_suite",
    "classify_result",
    "percentile_nearest_rank",
    "run_qualification",
    "summarize_latency",
]
