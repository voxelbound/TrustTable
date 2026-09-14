"""Tests for the fixed, versioned benchmark fixture set (`AI-06`).

Covers this package's acceptance criteria AC-01..AC-03.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from trusttable_backend.ai_benchmark.fixtures import (
    FIXTURE_SET_VERSION,
    BenchmarkTask,
    build_fixture_tasks,
)
from trusttable_backend.ai_provider.contract import AIOperation
from trusttable_backend.analysis.service import AnalysisStore, create_analysis, run_analysis

_REFERENCE_INSTANT = datetime(2026, 8, 24, tzinfo=UTC)

_EXPECTED_TASK_DETECTOR_IDS = {
    "context_inference": "structural.empty_column",
    "guided_questions": "completeness.missing_likely_identifier",
    "finding_explanation": "validity.future_dates",
    "remediation": "validity.negative_likely_non_negative_values",
    "rule_description": "validity.invalid_percentages",
}


def _independent_reference_analysis():
    """Build a second, wholly independent reference analysis (its own
    store/instance) for AC-03's independent re-verification, rather than
    reusing anything `fixtures.py` itself constructed."""
    store = AnalysisStore()
    created = create_analysis(store)
    return run_analysis(store, created.analysis_id, now=_REFERENCE_INSTANT)


# ---------------------------------------------------------------------------
# AC-01: exactly 6 tasks, one per AIOperation, each non-empty and evidenced


def test_build_fixture_tasks_returns_exactly_six_tasks() -> None:
    tasks = build_fixture_tasks()
    assert len(tasks) == 6


def test_build_fixture_tasks_covers_every_ai_operation_exactly_once() -> None:
    tasks = build_fixture_tasks()
    operations = [task.operation for task in tasks]
    assert sorted(operations, key=lambda op: op.value) == sorted(
        AIOperation, key=lambda op: op.value
    )
    assert len(set(operations)) == 6


def test_every_fixture_task_has_non_empty_description_and_evidence() -> None:
    for task in build_fixture_tasks():
        assert task.description != ""
        assert task.request.envelope.task == task.description
        assert len(task.request.envelope.computed_evidence) >= 1


def test_every_fixture_task_has_samples_disabled_by_default() -> None:
    """Boundary: fixtures never enable dataset-sample transmission
    (`docs/product-requirements.md` §12's "disabled by default")."""
    for task in build_fixture_tasks():
        assert task.request.envelope.sample_sending_enabled is False
        assert task.request.envelope.untrusted_dataset_samples == ()


def test_benchmark_task_rejects_empty_task_id() -> None:
    tasks = build_fixture_tasks()
    template = tasks[0]
    with pytest.raises(ValueError, match="task_id"):
        BenchmarkTask(
            task_id="",
            operation=template.operation,
            description=template.description,
            request=template.request,
        )


def test_benchmark_task_rejects_empty_description() -> None:
    tasks = build_fixture_tasks()
    template = tasks[0]
    with pytest.raises(ValueError, match="description"):
        BenchmarkTask(
            task_id=template.task_id,
            operation=template.operation,
            description="",
            request=template.request,
        )


# ---------------------------------------------------------------------------
# AC-02: reproducibility — two independent calls are byte-identical


def test_build_fixture_tasks_is_reproducible_across_two_independent_calls() -> None:
    first = build_fixture_tasks()
    second = build_fixture_tasks()
    assert [t.task_id for t in first] == [t.task_id for t in second]
    assert [t.operation for t in first] == [t.operation for t in second]
    assert [t.description for t in first] == [t.description for t in second]
    for a, b in zip(first, second, strict=True):
        assert a.request.envelope.computed_evidence == b.request.envelope.computed_evidence
        assert a.request.envelope.task == b.request.envelope.task
        assert a.request.known_numeric_facts == b.request.known_numeric_facts


def test_fixture_set_version_is_a_non_empty_fixed_constant() -> None:
    assert FIXTURE_SET_VERSION != ""


# ---------------------------------------------------------------------------
# AC-03: grounding evidence independently re-verified, not merely trusted


@pytest.mark.parametrize("task_id,expected_detector_id", list(_EXPECTED_TASK_DETECTOR_IDS.items()))
def test_single_finding_task_grounding_matches_independent_reference_analysis(
    task_id: str, expected_detector_id: str
) -> None:
    tasks = {task.task_id: task for task in build_fixture_tasks()}
    task = tasks[task_id]

    reference = _independent_reference_analysis()
    matching = [f for f in reference.findings if f.detector_id == expected_detector_id]
    assert matching, f"reference analysis has no finding for {expected_detector_id!r}"
    expected_evidence_ids = {eid for f in matching for eid in f.evidence_ids}

    actual_evidence_ids = {e.evidence_id for e in task.request.envelope.computed_evidence}
    assert actual_evidence_ids
    assert actual_evidence_ids <= expected_evidence_ids


def test_report_summary_task_grounded_in_top_priority_findings() -> None:
    tasks = {task.task_id: task for task in build_fixture_tasks()}
    task = tasks["report_summary"]
    assert task.operation is AIOperation.REPORT_SUMMARY

    reference = _independent_reference_analysis()
    ranked = sorted(
        range(len(reference.findings)),
        key=lambda i: reference.priority_scores[i],
        reverse=True,
    )
    top_finding_ids = {reference.findings[i].detector_id for i in ranked[:3]}
    grounded_evidence_ids = {e.evidence_id for e in task.request.envelope.computed_evidence}

    # Every evidence id used by the report_summary task must trace back
    # to one of the top-3-by-priority-score findings' own evidence_ids.
    expected_evidence_ids: set[str] = set()
    for i in ranked[:3]:
        expected_evidence_ids.update(reference.findings[i].evidence_ids)
    assert grounded_evidence_ids <= expected_evidence_ids
    assert top_finding_ids  # sanity: the reference analysis actually has findings
