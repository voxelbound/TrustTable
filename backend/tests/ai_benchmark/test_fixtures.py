"""Tests for the fixed, versioned benchmark fixture set (`AI-06`).

Covers this package's acceptance criteria AC-01..AC-03.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from trusttable_backend.ai_benchmark.fixtures import (
    FIXTURE_SET_VERSION,
    BenchmarkTask,
    _known_numeric_facts_from_evidence,
    build_fixture_tasks,
)
from trusttable_backend.ai_boundary.envelope import PromptEnvelope
from trusttable_backend.ai_boundary.validation import (
    MODEL_OUTPUT_SCHEMA_VERSION,
    RejectionReason,
    validate_model_output,
)
from trusttable_backend.ai_provider.contract import AIOperation
from trusttable_backend.analysis.service import (
    Analysis,
    AnalysisStore,
    create_analysis,
    run_analysis,
)
from trusttable_backend.domain.evidence import Evidence, EvidenceType
from trusttable_backend.domain.parsing import SamplingScope
from trusttable_backend.domain.value_objects import Provenance

_REFERENCE_INSTANT = datetime(2026, 8, 24, tzinfo=UTC)


def _make_evidence(**overrides: object) -> Evidence:
    fields: dict[str, object] = {
        "evidence_id": "ev-synthetic",
        "evidence_type": EvidenceType.METRIC,
        "calculation_version": "1",
        "structured_payload": {},
        "affected_columns": (),
        "affected_row_references": (),
        "scope": SamplingScope.FULL,
        "display_safe_summary": "Synthetic evidence for a WP-045 regression test.",
    }
    fields.update(overrides)
    return Evidence(**fields)  # type: ignore[arg-type]


def _well_formed_claim_output(numeric_claims: dict[str, object]) -> dict[str, object]:
    return {
        "schema_version": MODEL_OUTPUT_SCHEMA_VERSION,
        "narrative": "Synthetic narrative for a WP-045 numeric-grounding regression test.",
        "provenance": Provenance.AI_INTERPRETATION.value,
        "numeric_claims": numeric_claims,
    }


_EXPECTED_TASK_DETECTOR_IDS = {
    "context_inference": "structural.empty_column",
    "guided_questions": "completeness.missing_likely_identifier",
    "finding_explanation": "validity.future_dates",
    "remediation": "validity.negative_likely_non_negative_values",
    "rule_description": "validity.invalid_percentages",
}


def _independent_reference_analysis() -> Analysis:
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


# ---------------------------------------------------------------------------
# WP-045: known_numeric_facts grounding-gap fix
#
# `_make_task` previously hardcoded `known_numeric_facts={}` for every
# fixture, so `validate_model_output` rejected *any* `numeric_claims` key
# with `unknown_numeric_claim` regardless of correctness (a real defect
# found and diagnosed by the same-session read-only activity
# `AI-06-fixture-validator-trace-20260915`, corroborated by a real
# hands-on rejection in `AI-06-hands-on-smoke-20260915-r3`). These cases
# are numbered to match the human owner's own explicit CHANGE
# instruction (WP-045's "Decisions and clarifications").


def test_1_finding_explanation_exposes_future_date_count_as_flat_key() -> None:
    tasks = {task.task_id: task for task in build_fixture_tasks()}
    task = tasks["finding_explanation"]

    # Independently re-derive the expected value from a second, wholly
    # separate reference analysis, matching this file's existing AC-03
    # independent-re-verification convention rather than trusting
    # fixtures.py's own internal construction.
    reference = _independent_reference_analysis()
    matching = [f for f in reference.findings if f.detector_id == "validity.future_dates"]
    assert matching
    evidence_by_id = {e.evidence_id: e for e in reference.evidence}
    expected_counts = {
        evidence_by_id[eid].structured_payload["future_date_count"]
        for finding in matching
        for eid in finding.evidence_ids
    }
    assert len(expected_counts) == 1
    expected_count = next(iter(expected_counts))
    assert expected_count == 2  # documented real value for the committed demo dataset

    assert task.request.known_numeric_facts.get("future_date_count") == expected_count
    # The finding's own non-numeric `reference_date` field must never
    # leak into the numeric allow-list.
    assert "reference_date" not in task.request.known_numeric_facts


def test_2_correct_future_date_count_claim_is_accepted() -> None:
    tasks = {task.task_id: task for task in build_fixture_tasks()}
    task = tasks["finding_explanation"]
    known = task.request.known_numeric_facts
    output = _well_formed_claim_output({"future_date_count": known["future_date_count"]})

    outcome = validate_model_output(output, task.request.envelope, known_numeric_facts=known)

    assert outcome.accepted is True
    assert outcome.rejection_reasons == ()


def test_3_wrong_future_date_count_claim_is_rejected_with_numeric_claim_mismatch() -> None:
    tasks = {task.task_id: task for task in build_fixture_tasks()}
    task = tasks["finding_explanation"]
    known = task.request.known_numeric_facts
    wrong_value = known["future_date_count"] + 1
    output = _well_formed_claim_output({"future_date_count": wrong_value})

    outcome = validate_model_output(output, task.request.envelope, known_numeric_facts=known)

    assert outcome.accepted is False
    assert RejectionReason.NUMERIC_CLAIM_MISMATCH in outcome.rejection_reasons
    assert RejectionReason.UNKNOWN_NUMERIC_CLAIM not in outcome.rejection_reasons


def test_4_invented_numeric_key_is_rejected_with_unknown_numeric_claim() -> None:
    tasks = {task.task_id: task for task in build_fixture_tasks()}
    task = tasks["finding_explanation"]
    known = task.request.known_numeric_facts
    output = _well_formed_claim_output({"totally_invented_numeric_key": 1})

    outcome = validate_model_output(output, task.request.envelope, known_numeric_facts=known)

    assert outcome.accepted is False
    assert RejectionReason.UNKNOWN_NUMERIC_CLAIM in outcome.rejection_reasons


def test_5_duplicate_field_with_identical_values_is_deterministic_and_unambiguous() -> None:
    ev_a = _make_evidence(evidence_id="ev-a", structured_payload={"negative_count": 3})
    ev_b = _make_evidence(evidence_id="ev-b", structured_payload={"negative_count": 3})

    forward = _known_numeric_facts_from_evidence((ev_a, ev_b))
    backward = _known_numeric_facts_from_evidence((ev_b, ev_a))

    assert forward == {"negative_count": 3.0}
    assert backward == {"negative_count": 3.0}  # order-independent, not last-write-wins


def test_6_duplicate_field_with_conflicting_values_is_omitted_and_fails_closed() -> None:
    ev_a = _make_evidence(evidence_id="ev-a", structured_payload={"negative_count": 3})
    ev_b = _make_evidence(evidence_id="ev-b", structured_payload={"negative_count": 5})

    known = _known_numeric_facts_from_evidence((ev_a, ev_b))
    assert "negative_count" not in known

    envelope = PromptEnvelope(
        task="Synthetic ambiguous-key regression case.",
        computed_evidence=(ev_a, ev_b),
        confirmed_context={},
        untrusted_dataset_samples=(),
        sample_sending_enabled=False,
    )
    # A claim using either conflicting value must be rejected — never
    # silently resolved to one of them.
    for claimed_value in (3, 5):
        output = _well_formed_claim_output({"negative_count": claimed_value})
        outcome = validate_model_output(output, envelope, known_numeric_facts=known)
        assert outcome.accepted is False
        assert RejectionReason.UNKNOWN_NUMERIC_CLAIM in outcome.rejection_reasons
        assert RejectionReason.NUMERIC_CLAIM_MISMATCH not in outcome.rejection_reasons


def test_known_numeric_facts_excludes_non_numeric_and_boolean_values() -> None:
    """AC-07: `bool` (a Python `int` subclass) and non-numeric fields
    (e.g. `future_dates`' own `reference_date` string) never participate
    in the derived allow-list."""
    ev = _make_evidence(
        structured_payload={
            "reference_date": "2026-08-24",
            "future_date_count": 2,
            "flagged": True,
        }
    )

    known = _known_numeric_facts_from_evidence((ev,))

    assert known == {"future_date_count": 2.0}
