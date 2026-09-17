"""Tests for validated AI finding explanations (`AI-05`, `WP-061`).

Covers AC-04..AC-11: envelope construction, structural zero-sample
sending, the positive/retry-success/retry-exhaustion/provider-error
paths of `run_finding_explanation`, `FindingExplanationResult`'s
invariants, known-numeric-facts extraction/grounding, no-eval/exec, and
(AC-12, AI half) a real end-to-end check against the committed
`demo-data/sales_demo.csv`.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from trusttable_backend.ai_boundary.validation import RejectionReason
from trusttable_backend.ai_provider.contract import ProviderRequest
from trusttable_backend.ai_provider.disabled import DisabledProvider
from trusttable_backend.ai_provider.mock import MockProvider
from trusttable_backend.detectors.catalogue import DETECTORS
from trusttable_backend.detectors.contract import (
    DetectorCategory,
    FindingCandidate,
    SecurityExposureState,
)
from trusttable_backend.detectors.engine import run_detectors
from trusttable_backend.domain.evidence import Evidence, EvidenceType
from trusttable_backend.domain.explanation import FindingExplanation
from trusttable_backend.domain.parsing import SamplingScope
from trusttable_backend.domain.value_objects import ColumnReference, Provenance, Severity
from trusttable_backend.explanation.ai_explanation import (
    DEFAULT_MAX_RETRIES,
    FindingExplanationResult,
    build_finding_explanation_envelope,
    run_finding_explanation,
)
from trusttable_backend.parsers.csv_parser import parse_csv
from trusttable_backend.profiling.metrics import compute_dataset_profile

REPO_ROOT = Path(__file__).resolve().parents[3]
DEMO_CSV_PATH = REPO_ROOT / "demo-data" / "sales_demo.csv"
ANALYSIS_TIMESTAMP = datetime(2026, 8, 24, tzinfo=UTC)
NO_EXPOSURE = SecurityExposureState(model_provider_enabled=False, sample_transmission_enabled=False)


def make_column(name: str, ordinal: int = 0) -> ColumnReference:
    return ColumnReference(original_name=name, internal_key=name, ordinal=ordinal)


def make_evidence(**overrides: object) -> Evidence:
    fields: dict[str, object] = {
        "evidence_id": "ev-1",
        "evidence_type": EvidenceType.ROW_SET,
        "calculation_version": "1",
        "structured_payload": {"row_count": 2},
        "affected_columns": (make_column("order_id"),),
        "affected_row_references": (),
        "scope": SamplingScope.FULL,
        "display_safe_summary": "2 duplicate rows found",
    }
    fields.update(overrides)
    return Evidence(**fields)  # type: ignore[arg-type]


def make_finding(**overrides: object) -> FindingCandidate:
    fields: dict[str, object] = {
        "detector_id": "structural.exact_duplicate_rows",
        "detector_version": "1",
        "category": DetectorCategory.STRUCTURAL,
        "severity": Severity.MEDIUM,
        "confidence": 1.0,
        "calculated_observation": "2 rows are exact duplicates",
        "affected_columns": (make_column("order_id"),),
        "affected_row_references": (),
        "evidence_ids": ("ev-1",),
        "default_remediation_template_key": None,
        "default_validation_rule_template_key": None,
    }
    fields.update(overrides)
    return FindingCandidate(**fields)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# AC-04: envelope construction
# ---------------------------------------------------------------------------


def test_envelope_forwards_evidence_unchanged() -> None:
    evidence = (make_evidence(),)
    finding = make_finding()

    envelope = build_finding_explanation_envelope(finding, evidence)

    assert envelope.computed_evidence == evidence


def test_envelope_sends_zero_samples() -> None:
    finding = make_finding()

    envelope = build_finding_explanation_envelope(finding, (make_evidence(),))

    assert envelope.untrusted_dataset_samples == ()
    assert envelope.sample_sending_enabled is False


# ---------------------------------------------------------------------------
# AC-05: positive path
# ---------------------------------------------------------------------------


def test_run_finding_explanation_accepts_default_mock_output() -> None:
    evidence = (make_evidence(),)
    envelope = build_finding_explanation_envelope(make_finding(), evidence)
    provider = MockProvider()

    result = run_finding_explanation(provider, envelope, evidence)

    assert result.accepted is True
    assert result.explanation is not None
    assert result.explanation.provenance is Provenance.AI_INTERPRETATION
    assert result.explanation.referenced_evidence_ids == ("ev-1",)
    assert result.retries_used == 0
    assert result.provider_error is None


# ---------------------------------------------------------------------------
# UI-02 slice 1 (WP-063): provider identity threaded from a real response
# ---------------------------------------------------------------------------


def test_accepted_explanation_carries_real_provider_identity() -> None:
    evidence = (make_evidence(),)
    envelope = build_finding_explanation_envelope(make_finding(), evidence)
    provider = MockProvider()

    result = run_finding_explanation(provider, envelope, evidence)

    assert result.accepted is True
    assert result.explanation is not None
    assert result.explanation.provider_name == provider.provider_name
    assert result.explanation.model_identifier == "mock-v1"
    assert result.rejection_reasons == ()


# ---------------------------------------------------------------------------
# AC-06: retry-then-success path
# ---------------------------------------------------------------------------


def test_run_finding_explanation_retries_with_feedback_then_succeeds() -> None:
    evidence = (make_evidence(),)
    envelope = build_finding_explanation_envelope(make_finding(), evidence)

    def response_factory(request: ProviderRequest) -> dict[str, object]:
        if request.retry_feedback is None:
            return {"schema_version": "not-a-real-version"}
        return {
            "schema_version": "1",
            "narrative": "Retried and valid explanation.",
            "provenance": Provenance.AI_INTERPRETATION.value,
        }

    provider = MockProvider(response_factory=response_factory)

    result = run_finding_explanation(provider, envelope, evidence)

    assert result.accepted is True
    assert result.retries_used == 1
    assert result.explanation is not None
    assert result.explanation.narrative == "Retried and valid explanation."


# ---------------------------------------------------------------------------
# AC-07: bounded retry exhaustion
# ---------------------------------------------------------------------------


def test_run_finding_explanation_exhausts_retries_and_rejects() -> None:
    evidence = (make_evidence(),)
    envelope = build_finding_explanation_envelope(make_finding(), evidence)
    provider = MockProvider(raw_output={"schema_version": "wrong"})

    result = run_finding_explanation(provider, envelope, evidence)

    assert result.accepted is False
    assert result.explanation is None
    assert result.retries_used == DEFAULT_MAX_RETRIES
    assert result.rejection_reasons != ()
    assert result.provider_error is None


# ---------------------------------------------------------------------------
# AC-08: provider-error path
# ---------------------------------------------------------------------------


def test_run_finding_explanation_handles_provider_error_without_raising() -> None:
    evidence = (make_evidence(),)
    envelope = build_finding_explanation_envelope(make_finding(), evidence)
    provider = DisabledProvider()

    result = run_finding_explanation(provider, envelope, evidence)

    assert result.accepted is False
    assert result.explanation is None
    assert result.retries_used == 0
    assert result.provider_error is not None
    assert "ProviderConnectionError" in result.provider_error


# ---------------------------------------------------------------------------
# AC-09: FindingExplanationResult invariants
# ---------------------------------------------------------------------------


def make_explanation_object(**overrides: object) -> FindingExplanation:
    fields: dict[str, object] = {
        "narrative": "An AI-grounded narrative.",
        "provenance": Provenance.AI_INTERPRETATION,
        "referenced_evidence_ids": ("ev-1",),
        "referenced_columns": (),
    }
    fields.update(overrides)
    return FindingExplanation(**fields)  # type: ignore[arg-type]


def test_finding_explanation_result_rejects_accepted_without_explanation() -> None:
    with pytest.raises(ValueError, match="explanation"):
        FindingExplanationResult(
            accepted=True,
            explanation=None,
            rejection_reasons=(),
            provider_error=None,
            retries_used=0,
        )


def test_finding_explanation_result_rejects_not_accepted_with_explanation() -> None:
    with pytest.raises(ValueError, match="explanation"):
        FindingExplanationResult(
            accepted=False,
            explanation=make_explanation_object(),
            rejection_reasons=(),
            provider_error=None,
            retries_used=0,
        )


def test_finding_explanation_result_rejects_negative_retries_used() -> None:
    with pytest.raises(ValueError, match="retries_used"):
        FindingExplanationResult(
            accepted=False,
            explanation=None,
            rejection_reasons=(),
            provider_error=None,
            retries_used=-1,
        )


# ---------------------------------------------------------------------------
# AC-10: known-numeric-facts extraction and grounding
# ---------------------------------------------------------------------------


def test_correct_numeric_claim_is_accepted() -> None:
    evidence = (make_evidence(structured_payload={"row_count": 2}),)
    envelope = build_finding_explanation_envelope(make_finding(), evidence)
    provider = MockProvider(
        raw_output={
            "schema_version": "1",
            "narrative": "Two rows are affected.",
            "provenance": Provenance.AI_INTERPRETATION.value,
            "numeric_claims": {"row_count": 2},
        }
    )

    result = run_finding_explanation(provider, envelope, evidence)

    assert result.accepted is True


def test_wrong_numeric_claim_is_rejected() -> None:
    evidence = (make_evidence(structured_payload={"row_count": 2}),)
    envelope = build_finding_explanation_envelope(make_finding(), evidence)
    provider = MockProvider(
        raw_output={
            "schema_version": "1",
            "narrative": "Five rows are affected.",
            "provenance": Provenance.AI_INTERPRETATION.value,
            "numeric_claims": {"row_count": 5},
        }
    )

    result = run_finding_explanation(provider, envelope, evidence)

    assert result.accepted is False
    assert RejectionReason.NUMERIC_CLAIM_MISMATCH in result.rejection_reasons


def test_invented_numeric_claim_key_is_rejected() -> None:
    evidence = (make_evidence(structured_payload={"row_count": 2}),)
    envelope = build_finding_explanation_envelope(make_finding(), evidence)
    provider = MockProvider(
        raw_output={
            "schema_version": "1",
            "narrative": "There were 99 invented rows affected.",
            "provenance": Provenance.AI_INTERPRETATION.value,
            "numeric_claims": {"invented_field": 99},
        }
    )

    result = run_finding_explanation(provider, envelope, evidence)

    assert result.accepted is False
    assert RejectionReason.UNKNOWN_NUMERIC_CLAIM in result.rejection_reasons


def test_explanation_referenced_columns_grounded_in_evidence_not_model_claim() -> None:
    evidence = (make_evidence(affected_columns=(make_column("order_id"),)),)
    envelope = build_finding_explanation_envelope(make_finding(), evidence)
    provider = MockProvider(
        raw_output={
            "schema_version": "1",
            "narrative": "Grounded narrative.",
            "provenance": Provenance.AI_INTERPRETATION.value,
        }
    )

    result = run_finding_explanation(provider, envelope, evidence)

    assert result.accepted is True
    assert result.explanation is not None
    assert result.explanation.referenced_columns == (make_column("order_id"),)


# ---------------------------------------------------------------------------
# AC-11: no eval/exec
# ---------------------------------------------------------------------------


def test_no_eval_or_exec_in_ai_explanation_module() -> None:
    module_path = (
        REPO_ROOT / "backend" / "src" / "trusttable_backend" / "explanation" / "ai_explanation.py"
    )
    source = module_path.read_text(encoding="utf-8")
    assert "eval(" not in source
    assert "exec(" not in source


# ---------------------------------------------------------------------------
# AC-12 (AI half): real end-to-end check against the committed demo dataset
# ---------------------------------------------------------------------------


def test_real_demo_csv_ai_explanation_is_grounded_in_real_evidence() -> None:
    content = DEMO_CSV_PATH.read_bytes()
    parsed = parse_csv(content)
    columns = parsed.parsed_dataset.columns
    dataset_profile = compute_dataset_profile(
        columns, parsed.rows, parsed.parsed_dataset.sampling, as_of=date(2026, 8, 24)
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
        security_exposure=NO_EXPOSURE,
        analysis_timestamp=ANALYSIS_TIMESTAMP,
    )
    findings = tuple(finding for result in results for finding in result.findings)
    all_evidence = tuple(item for result in results for item in result.evidence)
    assert findings, "committed demo dataset is expected to produce at least one finding"
    finding = findings[0]
    evidence_by_id = {item.evidence_id: item for item in all_evidence}
    finding_evidence = tuple(evidence_by_id[eid] for eid in finding.evidence_ids)

    envelope = build_finding_explanation_envelope(finding, finding_evidence)
    provider = MockProvider(
        raw_output={
            "schema_version": "1",
            "narrative": "This finding reflects a real, grounded data-quality issue.",
            "provenance": Provenance.AI_INTERPRETATION.value,
        }
    )

    result = run_finding_explanation(provider, envelope, finding_evidence)

    assert result.accepted is True
    assert result.explanation is not None
    assert result.explanation.referenced_evidence_ids == finding.evidence_ids
