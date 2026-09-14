"""Tests for the config-driven benchmark runner (`AI-06`).

Covers this package's acceptance criteria AC-04..AC-08.
"""

from __future__ import annotations

from trusttable_backend.ai_benchmark.fixtures import BenchmarkTask, build_fixture_tasks
from trusttable_backend.ai_benchmark.runner import BenchmarkConfig, run_benchmark
from trusttable_backend.ai_boundary.envelope import PromptEnvelope
from trusttable_backend.ai_boundary.validation import MODEL_OUTPUT_SCHEMA_VERSION, RejectionReason
from trusttable_backend.ai_provider.contract import AIOperation, ProviderRequest
from trusttable_backend.ai_provider.disabled import DisabledProvider
from trusttable_backend.ai_provider.mock import MockProvider
from trusttable_backend.domain.evidence import Evidence, EvidenceType
from trusttable_backend.domain.parsing import SamplingScope
from trusttable_backend.domain.value_objects import ColumnReference, Provenance


def make_column(key: str) -> ColumnReference:
    return ColumnReference(original_name=key, internal_key=key, ordinal=0)


def make_evidence(**overrides: object) -> Evidence:
    fields: dict[str, object] = {
        "evidence_id": "ev-1",
        "evidence_type": EvidenceType.METRIC,
        "calculation_version": "1",
        "structured_payload": {"mean": 1.5},
        "affected_columns": (make_column("quantity"),),
        "affected_row_references": (),
        "scope": SamplingScope.FULL,
        "display_safe_summary": "Mean value is 1.5",
    }
    fields.update(overrides)
    return Evidence(**fields)  # type: ignore[arg-type]


def make_task(
    *, task_id: str = "t1", operation: AIOperation = AIOperation.FINDING_EXPLANATION
) -> BenchmarkTask:
    envelope = PromptEnvelope(
        task="Explain the following.",
        computed_evidence=(make_evidence(),),
        confirmed_context={},
        untrusted_dataset_samples=(),
        sample_sending_enabled=False,
    )
    request = ProviderRequest(operation=operation, envelope=envelope, known_numeric_facts={})
    return BenchmarkTask(
        task_id=task_id, operation=operation, description="Explain the following.", request=request
    )


def well_formed_output(**overrides: object) -> dict[str, object]:
    fields: dict[str, object] = {
        "schema_version": MODEL_OUTPUT_SCHEMA_VERSION,
        "narrative": "A well-formed narrative.",
        "provenance": Provenance.AI_INTERPRETATION.value,
    }
    fields.update(overrides)
    return fields


def hostile_output() -> dict[str, object]:
    return {
        "schema_version": MODEL_OUTPUT_SCHEMA_VERSION,
        "narrative": "Hostile.",
        "provenance": Provenance.AI_INTERPRETATION.value,
        "override_findings": True,  # unsupported control field -> always rejected
    }


# ---------------------------------------------------------------------------
# AC-04: full real-fixture run against a well-formed MockProvider


def test_run_benchmark_against_default_mock_provider_accepts_every_fixture_task() -> None:
    report = run_benchmark(MockProvider(), build_fixture_tasks())
    assert report.task_count == 6
    assert report.accepted_count == 6
    assert report.validity_rate == 1.0
    for result in report.task_results:
        assert result.accepted is True
        assert result.retries_used == 0
        assert result.consistent is True
        assert result.provider_error is None


def test_run_benchmark_reports_provider_and_model_identity() -> None:
    report = run_benchmark(MockProvider(model_identifier="mock-bench"), build_fixture_tasks())
    assert report.provider_name == "mock"
    assert report.model_identifier == "mock-bench"
    assert report.fixture_set_version != ""


def test_benchmark_config_hardware_profile_is_recorded_unchanged() -> None:
    report = run_benchmark(
        MockProvider(),
        build_fixture_tasks(),
        config=BenchmarkConfig(hardware_profile="accelerated"),
    )
    assert report.hardware_profile == "accelerated"


# ---------------------------------------------------------------------------
# AC-05: bounded retries, exhaustion, and retry_feedback actually reaching
# the provider's next attempt


def test_run_benchmark_exhausts_retries_when_output_is_always_rejected() -> None:
    provider = MockProvider(response_factory=lambda request: hostile_output())
    task = make_task()
    report = run_benchmark(
        provider, [task], config=BenchmarkConfig(max_retries=2, consistency_repeats=0)
    )
    result = report.task_results[0]
    assert result.accepted is False
    assert result.retries_used == 2
    assert RejectionReason.UNSUPPORTED_CONTROL_FIELD in result.rejection_reasons
    assert report.accepted_count == 0
    assert report.average_retries_used == 2.0


def test_run_benchmark_retry_feedback_reaches_second_attempt() -> None:
    def factory(request: ProviderRequest) -> dict[str, object]:
        if request.retry_feedback is None:
            return hostile_output()
        return well_formed_output()

    provider = MockProvider(response_factory=factory)
    task = make_task()
    report = run_benchmark(
        provider, [task], config=BenchmarkConfig(max_retries=2, consistency_repeats=0)
    )
    result = report.task_results[0]
    assert result.accepted is True
    assert result.retries_used == 1


# ---------------------------------------------------------------------------
# AC-06: a provider that always raises never crashes the runner


def test_run_benchmark_against_disabled_provider_never_raises() -> None:
    report = run_benchmark(DisabledProvider(), build_fixture_tasks())
    assert report.task_count == 6
    assert report.accepted_count == 0
    assert report.validity_rate == 0.0
    for result in report.task_results:
        assert result.accepted is False
        assert result.provider_error is not None
        assert "ProviderConnectionError" in result.provider_error
        assert result.consistent is False


# ---------------------------------------------------------------------------
# AC-07: repeated-call consistency correctly detects non-determinism


def test_run_benchmark_detects_inconsistent_repeated_output() -> None:
    call_count = {"n": 0}

    def factory(request: ProviderRequest) -> dict[str, object]:
        call_count["n"] += 1
        return well_formed_output(narrative=f"Attempt number {call_count['n']}.")

    provider = MockProvider(response_factory=factory)
    task = make_task()
    report = run_benchmark(
        provider, [task], config=BenchmarkConfig(max_retries=0, consistency_repeats=2)
    )
    result = report.task_results[0]
    assert result.accepted is True  # each individual attempt is well-formed
    assert result.consistent is False  # but the content differs call-to-call


def test_run_benchmark_reports_consistent_true_for_deterministic_provider() -> None:
    provider = MockProvider(raw_output=well_formed_output())
    task = make_task()
    report = run_benchmark(provider, [task], config=BenchmarkConfig(consistency_repeats=3))
    assert report.task_results[0].consistent is True


def test_zero_consistency_repeats_is_vacuously_consistent() -> None:
    """Boundary: `consistency_repeats=0` performs no repeat calls at all
    and is trivially recorded as consistent (nothing contradicted it)."""
    call_count = {"n": 0}

    def factory(request: ProviderRequest) -> dict[str, object]:
        call_count["n"] += 1
        return well_formed_output(narrative=f"Call {call_count['n']}.")

    provider = MockProvider(response_factory=factory)
    task = make_task()
    report = run_benchmark(
        provider, [task], config=BenchmarkConfig(max_retries=0, consistency_repeats=0)
    )
    assert report.task_results[0].consistent is True
    assert call_count["n"] == 1  # only the original attempt, no repeats


# ---------------------------------------------------------------------------
# AC-08: aggregate fields independently recomputed and compared


def test_benchmark_report_aggregate_fields_match_independent_recomputation() -> None:
    tasks = [
        make_task(task_id="a", operation=AIOperation.FINDING_EXPLANATION),
        make_task(task_id="b", operation=AIOperation.REMEDIATION),
        make_task(task_id="c", operation=AIOperation.RULE_DESCRIPTION),
    ]
    provider = MockProvider(raw_output=well_formed_output())
    report = run_benchmark(provider, tasks, config=BenchmarkConfig(consistency_repeats=1))

    recomputed_accepted = sum(1 for r in report.task_results if r.accepted)
    recomputed_validity_rate = recomputed_accepted / len(report.task_results)
    recomputed_avg_duration = sum(r.duration_ms for r in report.task_results) / len(
        report.task_results
    )
    recomputed_avg_retries = sum(r.retries_used for r in report.task_results) / len(
        report.task_results
    )
    recomputed_consistency_rate = sum(1 for r in report.task_results if r.consistent) / len(
        report.task_results
    )

    assert report.accepted_count == recomputed_accepted
    assert report.validity_rate == recomputed_validity_rate
    assert report.average_duration_ms == recomputed_avg_duration
    assert report.average_retries_used == recomputed_avg_retries
    assert report.consistency_rate == recomputed_consistency_rate
    assert report.task_count == len(tasks) == len(report.task_results)


def test_run_benchmark_with_empty_task_list_produces_zeroed_report() -> None:
    """Boundary: an empty task sequence does not divide by zero."""
    report = run_benchmark(MockProvider(), [])
    assert report.task_count == 0
    assert report.accepted_count == 0
    assert report.validity_rate == 0.0
    assert report.average_duration_ms == 0.0
    assert report.average_retries_used == 0.0
    assert report.consistency_rate == 0.0
