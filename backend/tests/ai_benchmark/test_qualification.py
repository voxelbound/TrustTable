"""Core tests for the finding-analysis qualification harness (`REL-02`,
`docs/decision-log.md` D-043).

These prove what the harness observes and how it classifies and aggregates.
Every expected value is derived from the *script* a provider was given (or
recomputed independently here), never from the harness's own output, and time
comes from an injected manual clock so durations are exact.

The shared helpers at the top (`ManualClock`, `ScriptedProvider`,
`grounded_output`, ...) are imported by the sibling qualification test files.
"""

from __future__ import annotations

import ast
import math
import re
from collections import Counter
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from trusttable_backend.ai_benchmark import qualification as qualification_module
from trusttable_backend.ai_benchmark.qualification import (
    PRODUCT_AI_CALL_STATUS,
    AttemptRecord,
    CaseOutcome,
    CaseResult,
    CaseScope,
    Condition,
    MeasuringProvider,
    QualificationConfig,
    QualificationSuite,
    aggregate_results,
    build_qualification_suite,
    classify_result,
    percentile_nearest_rank,
    run_qualification,
    summarize_latency,
)
from trusttable_backend.ai_boundary.prompt import build_safe_prompt
from trusttable_backend.ai_boundary.validation import RejectionReason
from trusttable_backend.ai_provider.contract import (
    AIProvider,
    ProviderConnectionError,
    ProviderHealth,
    ProviderInvalidResponseError,
    ProviderRequest,
    ProviderResponse,
    ProviderTimeoutError,
)
from trusttable_backend.ai_provider.disabled import DisabledProvider
from trusttable_backend.analysis.service import AnalysisStore, create_analysis, run_analysis
from trusttable_backend.explanation.ai_explanation import (
    DEFAULT_MAX_RETRIES,
    FindingExplanationResult,
)

# ---------------------------------------------------------------------------
# Shared helpers (imported by the sibling qualification test files)
# ---------------------------------------------------------------------------

EDITABLE_FIELD_NAMES = {
    "probable_domain",
    "row_grain",
    "primary_entity",
    "currency_behavior",
    "expected_business_rules",
}
ROLE_FIELD_NAMES = {"candidate_keys", "business_dates", "measure_roles", "dimensions"}


class ManualClock:
    """A clock a test advances explicitly, so durations are exact."""

    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def payload_of_request(request: ProviderRequest) -> dict[str, Any]:
    """The untrusted-data payload a real provider would put in its prompt."""
    return dict(build_safe_prompt(request.envelope).data_payload)


def grounded_output(payload: dict[str, Any], *, use_context: bool = True) -> dict[str, Any]:
    """What an honest model would answer, derived only from `payload`: it cites
    the evidence ids and columns it was given, quotes a number that is in the
    evidence, and relies on a confirmed-context field only when one was sent."""
    evidence = payload["computed_evidence"]
    ids = [item["evidence_id"] for item in evidence]
    columns = list(dict.fromkeys(col for item in evidence for col in item["affected_columns"]))
    row_count = evidence[0]["affected_row_count"] if evidence else 0
    impact: list[dict[str, Any]] = [
        {
            "statement": "The supplied evidence documents this condition in the data.",
            "evidence_ids": ids[:1],
            "context_fields": [],
            "assumption": "the affected rows are used in analysis",
        },
        {
            "statement": "Reports built on this data may be affected.",
            "evidence_ids": [],
            "context_fields": [],
            "assumption": "the affected values feed reports",
        },
    ]
    context_fields = list(payload["confirmed_context"])
    if use_context and context_fields:
        impact.append(
            {
                "statement": "This matters in light of the confirmed dataset context.",
                "evidence_ids": [],
                "context_fields": context_fields[:1],
                "assumption": "the confirmed context describes how the data is used",
            }
        )
    return {
        "schema_version": "finding_analysis_v1",
        "provenance": "ai_interpretation",
        "explanation": f"The evidence records {row_count} affected row(s).",
        "business_impact": impact,
        "remediation": ["Review the flagged values in the source system and correct them there."],
        "validation_rule": {
            "rule_type": "not_null",
            "columns": columns[:5],
            "description": "Proposed: values in the affected columns should follow this rule.",
        },
        "referenced_evidence_ids": ids,
        "referenced_columns": columns,
    }


#: Schema-valid JSON that the role-aware validator rejects (required keys missing).
INVALID_OUTPUT: dict[str, Any] = {"schema_version": "finding_analysis_v1"}

Behavior = Callable[[ProviderRequest], ProviderResponse]


def response_for(request: ProviderRequest, raw_output: dict[str, Any]) -> ProviderResponse:
    return ProviderResponse(
        raw_output=raw_output,
        provider_name="scripted",
        model_identifier="scripted-model",
        duration_ms=1.0,
    )


def accepted_response(request: ProviderRequest) -> ProviderResponse:
    return response_for(request, grounded_output(payload_of_request(request)))


def rejected_response(request: ProviderRequest) -> ProviderResponse:
    return response_for(request, dict(INVALID_OUTPUT))


class ScriptedProvider:
    """An `AIProvider` whose `complete()` runs a caller-supplied behavior and
    records every request it received."""

    def __init__(self, behavior: Behavior, *, model_identifier: str = "scripted-model") -> None:
        self._behavior = behavior
        self._model_identifier = model_identifier
        self.requests: list[ProviderRequest] = []

    @property
    def provider_name(self) -> str:
        return "scripted"

    def health_check(self) -> ProviderHealth:
        return ProviderHealth(
            available=True,
            provider_name="scripted",
            model_identifier=self._model_identifier,
            detail="scripted",
        )

    def complete(self, request: ProviderRequest) -> ProviderResponse:
        self.requests.append(request)
        return self._behavior(request)


def detector_of(request: ProviderRequest) -> str:
    """The detector id the request's task text names (application-defined text)."""
    match = re.search(r"detector '([^']+)'", request.envelope.task)
    assert match is not None
    return match.group(1)


@pytest.fixture(scope="module")
def suite() -> QualificationSuite:
    return build_qualification_suite()


# ---------------------------------------------------------------------------
# The case set
# ---------------------------------------------------------------------------


def test_per_detector_suite_has_one_finding_per_detector_in_a_stable_order(
    suite: QualificationSuite,
) -> None:
    detector_ids = [case.detector_id for case in suite.cases]
    assert len(detector_ids) == len(set(detector_ids))
    assert detector_ids == sorted(detector_ids)
    assert len(detector_ids) >= 12  # the demo dataset exercises the detector catalogue
    assert all(case.case_id == f"{case.detector_id}#{case.finding_id}" for case in suite.cases)
    again = build_qualification_suite()
    assert [c.case_id for c in again.cases] == [c.case_id for c in suite.cases]


def test_all_findings_scope_covers_every_finding_and_contains_the_per_detector_cases(
    suite: QualificationSuite,
) -> None:
    store = AnalysisStore()
    reference = run_analysis(
        store,
        create_analysis(store).analysis_id,
        now=qualification_module._REFERENCE_INSTANT,
    )
    everything = build_qualification_suite(CaseScope.ALL_FINDINGS)

    assert len(everything.cases) == len(reference.findings)
    assert len({c.case_id for c in everything.cases}) == len(everything.cases)
    assert {c.case_id for c in suite.cases} <= {c.case_id for c in everything.cases}
    assert everything.scope is CaseScope.ALL_FINDINGS


def test_each_case_carries_the_findings_own_evidence(suite: QualificationSuite) -> None:
    for case in suite.cases:
        assert tuple(item.evidence_id for item in case.evidence) == case.finding.evidence_ids


def test_confirmed_context_holds_only_user_confirmed_or_corrected_fields(
    suite: QualificationSuite,
) -> None:
    context = dict(suite.confirmed_context)
    assert set(context) == EDITABLE_FIELD_NAMES
    assert not set(context) & ROLE_FIELD_NAMES  # inferred role fields are never sent
    states = {name: entry["confirmation_state"] for name, entry in context.items()}  # type: ignore[index]
    assert set(states.values()) <= {"confirmed", "corrected"}
    assert "corrected" in states.values()  # the fixed user answers for unknown fields
    assert "confirmed" in states.values()  # heuristics' own values, confirmed as-is


def test_a_suite_needs_cases_and_a_context() -> None:
    with pytest.raises(ValueError, match="cases"):
        QualificationSuite(scope=CaseScope.PER_DETECTOR, cases=(), confirmed_context={"a": 1})


# ---------------------------------------------------------------------------
# MeasuringProvider
# ---------------------------------------------------------------------------


def test_measuring_provider_times_with_the_harness_clock_not_the_providers_self_report(
    suite: QualificationSuite,
) -> None:
    clock = ManualClock()

    def slow(request: ProviderRequest) -> ProviderResponse:
        clock.advance(2.5)
        return ProviderResponse(
            raw_output=grounded_output(payload_of_request(request)),
            provider_name="scripted",
            model_identifier="scripted-model",
            duration_ms=9_999_999.0,  # a provider lying about its own time
        )

    measuring = MeasuringProvider(ScriptedProvider(slow), clock=clock)
    request = _any_request(suite)
    response = measuring.complete(request)

    attempts = measuring.take_attempts()
    assert attempts == (AttemptRecord(duration_ms=2500.0, error_kind=None),)
    assert response.duration_ms == 9_999_999.0  # returned unchanged, merely ignored


def test_measuring_provider_records_the_error_class_and_propagates_the_same_exception(
    suite: QualificationSuite,
) -> None:
    clock = ManualClock()
    raised = ProviderTimeoutError("a message that must never be recorded")

    def failing(request: ProviderRequest) -> ProviderResponse:
        clock.advance(4.0)
        raise raised

    measuring = MeasuringProvider(ScriptedProvider(failing), clock=clock)
    with pytest.raises(ProviderTimeoutError) as excinfo:
        measuring.complete(_any_request(suite))

    assert excinfo.value is raised
    (attempt,) = measuring.take_attempts()
    assert attempt == AttemptRecord(duration_ms=4000.0, error_kind="ProviderTimeoutError")
    assert "message" not in repr(attempt)


def test_take_attempts_returns_then_clears(suite: QualificationSuite) -> None:
    measuring = MeasuringProvider(ScriptedProvider(accepted_response), clock=ManualClock())
    request = _any_request(suite)
    measuring.complete(request)
    measuring.complete(request)
    assert len(measuring.take_attempts()) == 2
    assert measuring.take_attempts() == ()


def test_measuring_provider_satisfies_the_provider_protocol_and_delegates_identity() -> None:
    inner = ScriptedProvider(accepted_response, model_identifier="m-1")
    measuring = MeasuringProvider(inner)
    assert isinstance(measuring, AIProvider)
    assert measuring.provider_name == "scripted"
    assert measuring.health_check().model_identifier == "m-1"


def test_attempt_record_rejects_a_negative_duration() -> None:
    with pytest.raises(ValueError, match="negative"):
        AttemptRecord(duration_ms=-1.0, error_kind=None)


def _any_request(suite: QualificationSuite) -> ProviderRequest:
    """A real request the product would build for the first case."""
    provider = ScriptedProvider(accepted_response)
    run_qualification(
        provider,
        suite,
        config=QualificationConfig(conditions=(Condition.EVIDENCE_ONLY,)),
    )
    return provider.requests[0]


# ---------------------------------------------------------------------------
# Classification (pure)
# ---------------------------------------------------------------------------


def _result(**overrides: Any) -> FindingExplanationResult:
    base: dict[str, Any] = {
        "accepted": False,
        "explanation": None,
        "rejection_reasons": (),
        "provider_error": None,
        "retries_used": 0,
    }
    base.update(overrides)
    return FindingExplanationResult(**base)


def test_classify_a_provider_error_uses_the_last_attempts_error_class() -> None:
    attempts = [AttemptRecord(10.0, None), AttemptRecord(20.0, "ProviderConnectionError")]
    outcome, retries, reasons, kind = classify_result(
        _result(provider_error="ProviderConnectionError: x", retries_used=1), attempts, None
    )
    assert outcome is CaseOutcome.FELL_BACK_PROVIDER_ERROR
    assert (retries, reasons, kind) == (1, (), "ProviderConnectionError")


def test_classify_a_rejection_keeps_the_final_reasons() -> None:
    reasons_in = (RejectionReason.UNKNOWN_EVIDENCE_ID,)
    outcome, retries, reasons, kind = classify_result(
        _result(rejection_reasons=reasons_in, retries_used=2), [AttemptRecord(1.0, None)], None
    )
    assert outcome is CaseOutcome.FELL_BACK_REJECTED
    assert (retries, reasons, kind) == (2, reasons_in, None)


def test_classify_an_unexpected_exception_is_a_provider_error_fallback() -> None:
    outcome, retries, reasons, kind = classify_result(
        None, [AttemptRecord(1.0, "RuntimeError"), AttemptRecord(1.0, None)], "RuntimeError"
    )
    assert outcome is CaseOutcome.FELL_BACK_PROVIDER_ERROR
    assert (retries, reasons, kind) == (1, (), "RuntimeError")


def test_product_status_names_match_the_routes_vocabulary() -> None:
    assert PRODUCT_AI_CALL_STATUS == {
        CaseOutcome.ACCEPTED_FIRST_ATTEMPT: "attempted_accepted",
        CaseOutcome.ACCEPTED_AFTER_RETRY: "attempted_accepted",
        CaseOutcome.FELL_BACK_REJECTED: "attempted_rejected",
        CaseOutcome.FELL_BACK_PROVIDER_ERROR: "attempted_provider_error",
    }


# ---------------------------------------------------------------------------
# Running the product path
# ---------------------------------------------------------------------------


def test_an_accepting_provider_yields_first_attempt_success_for_every_case_and_condition(
    suite: QualificationSuite,
) -> None:
    provider = ScriptedProvider(accepted_response)
    report = run_qualification(provider, suite)

    cases = len(suite.cases)
    assert len(report.case_results) == 2 * cases
    assert all(r.outcome is CaseOutcome.ACCEPTED_FIRST_ATTEMPT for r in report.case_results)
    assert all(r.retries_used == 0 and len(r.attempts) == 1 for r in report.case_results)
    assert len(provider.requests) == 2 * cases  # no extra or repeated calls
    assert report.aggregate.fill_rate == 1.0
    assert report.max_retries == DEFAULT_MAX_RETRIES


def test_the_two_conditions_send_different_context_and_only_confirmed_fields(
    suite: QualificationSuite,
) -> None:
    provider = ScriptedProvider(accepted_response)
    report = run_qualification(provider, suite)

    cases = len(suite.cases)
    evidence_only = provider.requests[:cases]
    confirmed = provider.requests[cases:]
    assert all(not r.envelope.confirmed_context for r in evidence_only)
    for request in confirmed:
        sent = dict(request.envelope.confirmed_context)
        assert set(sent) == EDITABLE_FIELD_NAMES
        assert sent == dict(suite.confirmed_context)
    flags = [(r.condition, r.confirmed_context_sent) for r in report.case_results]
    assert (
        flags
        == [(Condition.EVIDENCE_ONLY, False)] * cases
        + [(Condition.CONFIRMED_CONTEXT, True)] * cases
    )


def test_a_rejected_first_answer_then_a_valid_one_is_accepted_after_one_retry(
    suite: QualificationSuite,
) -> None:
    clock = ManualClock()

    def behavior(request: ProviderRequest) -> ProviderResponse:
        if request.retry_feedback is None:
            clock.advance(2.0)
            return rejected_response(request)
        clock.advance(3.0)
        return accepted_response(request)

    provider = ScriptedProvider(behavior)
    report = run_qualification(
        provider,
        suite,
        config=QualificationConfig(conditions=(Condition.EVIDENCE_ONLY,)),
        clock=clock,
    )

    for result in report.case_results:
        assert result.outcome is CaseOutcome.ACCEPTED_AFTER_RETRY
        assert result.retries_used == 1
        assert [a.duration_ms for a in result.attempts] == [2000.0, 3000.0]
        assert result.total_duration_ms == 5000.0
        assert result.product_ai_call_status == "attempted_accepted"
    retry_requests = [r for r in provider.requests if r.retry_feedback is not None]
    assert retry_requests
    assert all(
        re.fullmatch(r"rejected: [a-z_]+(, [a-z_]+)*", r.retry_feedback or "")
        for r in retry_requests
    )


def test_answers_rejected_on_every_attempt_fall_back_after_the_products_retry_bound(
    suite: QualificationSuite,
) -> None:
    provider = ScriptedProvider(rejected_response)
    report = run_qualification(
        provider, suite, config=QualificationConfig(conditions=(Condition.EVIDENCE_ONLY,))
    )

    for result in report.case_results:
        assert result.outcome is CaseOutcome.FELL_BACK_REJECTED
        assert result.retries_used == DEFAULT_MAX_RETRIES
        assert len(result.attempts) == 1 + DEFAULT_MAX_RETRIES
        assert result.rejection_reasons
        assert result.provider_error_kind is None
        assert result.product_ai_call_status == "attempted_rejected"
    assert len(provider.requests) == len(suite.cases) * (1 + DEFAULT_MAX_RETRIES)


@pytest.mark.parametrize(
    "error",
    [ProviderTimeoutError, ProviderConnectionError, ProviderInvalidResponseError],
)
def test_each_provider_error_stops_at_once_and_falls_back_recording_only_its_class(
    suite: QualificationSuite, error: type[Exception]
) -> None:
    def failing(request: ProviderRequest) -> ProviderResponse:
        raise error("SENTINEL-EXCEPTION-TEXT")

    report = run_qualification(
        ScriptedProvider(failing),
        suite,
        config=QualificationConfig(conditions=(Condition.EVIDENCE_ONLY,)),
    )

    for result in report.case_results:
        assert result.outcome is CaseOutcome.FELL_BACK_PROVIDER_ERROR
        assert result.provider_error_kind == error.__name__
        assert len(result.attempts) == 1  # a provider error is never retried
        assert result.product_ai_call_status == "attempted_provider_error"
    assert "SENTINEL-EXCEPTION-TEXT" not in repr(report)
    assert report.aggregate.provider_error_kind_counts == {error.__name__: len(suite.cases)}


def test_an_unexpected_provider_exception_is_a_fallback_and_never_escapes(
    suite: QualificationSuite,
) -> None:
    def broken(request: ProviderRequest) -> ProviderResponse:
        raise RuntimeError("unexpected")

    report = run_qualification(
        ScriptedProvider(broken),
        suite,
        config=QualificationConfig(conditions=(Condition.EVIDENCE_ONLY,)),
    )
    assert {r.outcome for r in report.case_results} == {CaseOutcome.FELL_BACK_PROVIDER_ERROR}
    assert {r.provider_error_kind for r in report.case_results} == {"RuntimeError"}


def test_the_real_disabled_provider_records_a_provider_error_for_every_case(
    suite: QualificationSuite,
) -> None:
    report = run_qualification(DisabledProvider(), suite)

    assert report.aggregate.fill_rate == 0.0
    assert report.aggregate.fallback_rate == 1.0
    assert {r.provider_error_kind for r in report.case_results} == {"ProviderConnectionError"}
    assert report.server_available_at_start is False


def test_progress_callback_sees_every_case_in_order(suite: QualificationSuite) -> None:
    seen: list[str] = []
    report = run_qualification(
        ScriptedProvider(accepted_response),
        suite,
        on_case_complete=lambda result: seen.append(f"{result.case_id}|{result.condition.value}"),
    )
    assert seen == [f"{r.case_id}|{r.condition.value}" for r in report.case_results]


def test_report_identity_fields_are_sanitized_and_recorded(suite: QualificationSuite) -> None:
    provider = ScriptedProvider(
        accepted_response, model_identifier=r"C:\models\Qwen3.5-4B-Q4_K_M.gguf"
    )
    report = run_qualification(
        provider,
        suite,
        config=QualificationConfig(configured_timeout_seconds=120.0, notes="baseline run"),
    )
    assert report.model_identifier == "Qwen3.5-4B-Q4_K_M.gguf"
    assert report.provider_name == "scripted"
    assert report.server_available_at_start is True
    assert report.configured_timeout_seconds == 120.0
    assert report.notes == "baseline run"
    assert report.case_set_version == suite.case_set_version
    assert report.scope is CaseScope.PER_DETECTOR


# ---------------------------------------------------------------------------
# Aggregation, recomputed independently from the script
# ---------------------------------------------------------------------------


def _mixed_provider(clock: ManualClock, detector_ids: list[str]) -> ScriptedProvider:
    """Five behaviors assigned to detectors cyclically, with exact durations:

    0 accepted first attempt (1 s); 1 rejected (2 s) then accepted (3 s);
    2 rejected on all three attempts (1 s each); 3 timeout after 5 s;
    4 connection error after 0.5 s.
    """
    kind_of = {detector: index % 5 for index, detector in enumerate(detector_ids)}
    attempts: Counter[tuple[str, bool]] = Counter()

    def behavior(request: ProviderRequest) -> ProviderResponse:
        detector = detector_of(request)
        key = (detector, bool(request.envelope.confirmed_context))
        attempts[key] += 1
        kind = kind_of[detector]
        if kind == 0:
            clock.advance(1.0)
            return accepted_response(request)
        if kind == 1:
            if attempts[key] == 1:
                clock.advance(2.0)
                return rejected_response(request)
            clock.advance(3.0)
            return accepted_response(request)
        if kind == 2:
            clock.advance(1.0)
            return rejected_response(request)
        if kind == 3:
            clock.advance(5.0)
            raise ProviderTimeoutError("timed out")
        clock.advance(0.5)
        raise ProviderConnectionError("refused")

    return ScriptedProvider(behavior)


def _nearest_rank(values: list[float], percentile: int) -> float:
    ordered = sorted(values)
    return ordered[math.ceil(percentile * len(ordered) / 100) - 1]


def test_aggregates_equal_values_derived_from_the_script(suite: QualificationSuite) -> None:
    clock = ManualClock()
    detector_ids = [case.detector_id for case in suite.cases]
    report = run_qualification(_mixed_provider(clock, detector_ids), suite, clock=clock)
    aggregate = report.aggregate

    kinds = [index % 5 for index in range(len(detector_ids))]
    per_kind = Counter(kinds)
    conditions = 2
    n = len(detector_ids) * conditions
    expected_total = {0: 1000.0, 1: 5000.0, 2: 3000.0, 3: 5000.0, 4: 500.0}
    latencies = [expected_total[k] for k in kinds] * conditions

    assert aggregate.case_count == n
    assert aggregate.accepted_count == (per_kind[0] + per_kind[1]) * conditions
    assert aggregate.first_attempt_accepted_count == per_kind[0] * conditions
    assert aggregate.fallback_count == (per_kind[2] + per_kind[3] + per_kind[4]) * conditions
    assert aggregate.fill_rate == pytest.approx(aggregate.accepted_count / n)
    assert aggregate.first_attempt_fill_rate == pytest.approx(per_kind[0] * conditions / n)
    assert aggregate.fallback_rate == pytest.approx(1 - aggregate.fill_rate)
    assert aggregate.outcome_counts == {
        "accepted_first_attempt": per_kind[0] * conditions,
        "accepted_after_retry": per_kind[1] * conditions,
        "fell_back_rejected": per_kind[2] * conditions,
        "fell_back_provider_error": (per_kind[3] + per_kind[4]) * conditions,
    }
    assert aggregate.provider_error_kind_counts == {
        "ProviderConnectionError": per_kind[4] * conditions,
        "ProviderTimeoutError": per_kind[3] * conditions,
    }
    assert (
        aggregate.retries_total
        == (per_kind[1] * 1 + per_kind[2] * DEFAULT_MAX_RETRIES) * conditions
    )
    attempts_expected = (
        per_kind[0] * 1 + per_kind[1] * 2 + per_kind[2] * 3 + per_kind[3] + per_kind[4]
    ) * conditions
    assert aggregate.attempt_count == attempts_expected

    latency = aggregate.case_latency
    assert latency.count == n
    assert latency.mean_ms == pytest.approx(sum(latencies) / n)
    assert latency.p50_ms == _nearest_rank(latencies, 50)
    assert latency.p95_ms == _nearest_rank(latencies, 95)
    assert latency.max_ms == max(latencies)
    assert aggregate.slowest_attempt_ms == 5000.0
    assert aggregate.slowest_completed_attempt_ms == 3000.0  # the accepted retry's 3 s

    rejection_reasons = Counter(
        reason.value for r in report.case_results for reason in r.rejection_reasons
    )
    assert aggregate.rejection_reason_counts == dict(sorted(rejection_reasons.items()))
    assert sum(rejection_reasons.values()) >= per_kind[2] * conditions


def test_per_condition_aggregates_partition_the_overall_one(suite: QualificationSuite) -> None:
    clock = ManualClock()
    detector_ids = [case.detector_id for case in suite.cases]
    report = run_qualification(_mixed_provider(clock, detector_ids), suite, clock=clock)

    assert set(report.aggregate_by_condition) == {"evidence_only", "confirmed_context"}
    parts = report.aggregate_by_condition.values()
    assert sum(p.case_count for p in parts) == report.aggregate.case_count
    assert sum(p.accepted_count for p in parts) == report.aggregate.accepted_count
    assert sum(p.attempt_count for p in parts) == report.aggregate.attempt_count
    for name, part in report.aggregate_by_condition.items():
        assert part.case_count == len(suite.cases), name


def test_percentile_nearest_rank_boundaries() -> None:
    values = [float(v) for v in range(1, 21)]
    assert percentile_nearest_rank(values, 50) == 10.0
    assert percentile_nearest_rank(values, 95) == 19.0
    assert percentile_nearest_rank(values, 100) == 20.0
    assert percentile_nearest_rank(values, 1) == 1.0
    assert percentile_nearest_rank([7.0], 95) == 7.0
    assert percentile_nearest_rank([], 50) == 0.0


def test_a_single_case_has_equal_percentiles_and_an_empty_run_is_all_zero() -> None:
    single = summarize_latency([1234.0])
    assert (single.count, single.mean_ms, single.p50_ms, single.p95_ms, single.max_ms) == (
        1,
        1234.0,
        1234.0,
        1234.0,
        1234.0,
    )
    empty = aggregate_results([])
    assert empty.case_count == 0
    assert (empty.fill_rate, empty.fallback_rate, empty.first_attempt_fill_rate) == (0.0, 0.0, 0.0)
    assert empty.case_latency == summarize_latency([])
    assert empty.slowest_attempt_ms == 0.0 and empty.slowest_completed_attempt_ms == 0.0
    assert all(count == 0 for count in empty.outcome_counts.values())


def test_aggregating_a_hand_built_result_uses_only_that_results_facts() -> None:
    result = CaseResult(
        case_id="x#0",
        detector_id="x",
        condition=Condition.EVIDENCE_ONLY,
        outcome=CaseOutcome.FELL_BACK_PROVIDER_ERROR,
        product_ai_call_status="attempted_provider_error",
        retries_used=0,
        rejection_reasons=(),
        provider_error_kind="ProviderTimeoutError",
        attempts=(AttemptRecord(120000.0, "ProviderTimeoutError"),),
        total_duration_ms=120000.0,
        confirmed_context_sent=False,
    )
    aggregate = aggregate_results([result])
    assert aggregate.slowest_attempt_ms == 120000.0
    assert aggregate.slowest_completed_attempt_ms == 0.0  # a timeout is not a completed attempt


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def test_config_validation() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        QualificationConfig(conditions=())
    with pytest.raises(ValueError, match="repeat"):
        QualificationConfig(conditions=(Condition.EVIDENCE_ONLY, Condition.EVIDENCE_ONLY))
    with pytest.raises(ValueError, match="positive"):
        QualificationConfig(configured_timeout_seconds=0)
    assert QualificationConfig().conditions == (
        Condition.EVIDENCE_ONLY,
        Condition.CONFIRMED_CONTEXT,
    )


# ---------------------------------------------------------------------------
# Structural fidelity: the harness owns no prompt, schema, validator or retry
# ---------------------------------------------------------------------------


def _imported_names(source: str) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom):
            names.update(alias.name for alias in node.names)
            if node.module:
                names.add(node.module)
        elif isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
    return names


def test_the_harness_imports_no_validator_prompt_builder_or_older_adapter() -> None:
    source = Path(qualification_module.__file__).read_text(encoding="utf-8")
    imported = _imported_names(source)
    forbidden = {
        "validate_model_output",
        "validate_finding_analysis_output",
        "build_safe_prompt",
        "build_finding_analysis_contract",
        "build_prompt_envelope",
    }
    assert not imported & forbidden
    older_harness_modules = {"runner", "fixtures", "adapters", "adapters.llama_cpp_http"}
    assert not imported & older_harness_modules
    tree = ast.parse(source)
    identifiers = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    identifiers |= {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    assert "retry_feedback" not in identifiers  # the product owns retry and its feedback


def test_the_harness_calls_the_products_own_seams() -> None:
    source = Path(qualification_module.__file__).read_text(encoding="utf-8")
    imported = _imported_names(source)
    assert {
        "build_finding_explanation_envelope",
        "confirmed_context_for_finding_analysis",
        "run_finding_explanation",
    } <= imported
