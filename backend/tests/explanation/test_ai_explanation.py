"""Tests for validated AI finding analysis (`AI-05`, restructured by
`AI-08`).

Covers: envelope construction (per-finding trusted task text, zero
samples), the structured `OutputContract` a provider is actually asked for,
the positive/retry-success/retry-exhaustion/provider-error paths of
`run_finding_explanation`, `FindingExplanationResult`'s invariants,
known-numeric-facts extraction and grounding, the confirmed-only context
filter, the mapping of a validated output into the four-section domain
object, no-eval/exec, and a real end-to-end check against the committed
`demo-data/sales_demo.csv`.
"""

from __future__ import annotations

import copy
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

from trusttable_backend.ai_boundary.finding_analysis import (
    FINDING_ANALYSIS_CONTRACT_NAME,
    FINDING_ANALYSIS_SCHEMA_VERSION,
)
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
from trusttable_backend.domain.context import (
    ConfirmationState,
    ContextFieldValue,
    DatasetContext,
)
from trusttable_backend.domain.evidence import Evidence, EvidenceType
from trusttable_backend.domain.explanation import (
    FindingExplanation,
    ImpactBasis,
    ValidationRuleType,
)
from trusttable_backend.domain.parsing import SamplingScope
from trusttable_backend.domain.value_objects import ColumnReference, Provenance, Severity
from trusttable_backend.explanation.ai_explanation import (
    AI_EXPLANATION_TASK,
    DEFAULT_MAX_RETRIES,
    FindingExplanationResult,
    build_finding_analysis_task,
    build_finding_explanation_envelope,
    confirmed_context_for_finding_analysis,
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


def structured_output(**overrides: object) -> dict[str, Any]:
    """A grounded, well-formed `finding_analysis_v1` output for
    `make_evidence()`."""
    output: dict[str, Any] = {
        "schema_version": FINDING_ANALYSIS_SCHEMA_VERSION,
        "provenance": Provenance.AI_INTERPRETATION.value,
        "explanation": "2 duplicate rows were found, so some records are repeated.",
        "business_impact": [
            {
                "basis": "evidence",
                "statement": "Repeated rows can be counted more than once in totals.",
                "evidence_ids": ["ev-1"],
                "context_fields": [],
                "assumption": "",
            },
            {
                "basis": "assumption",
                "statement": "Order counts may be overstated in reports.",
                "evidence_ids": [],
                "context_fields": [],
                "assumption": "the rows feed order-count reporting",
            },
        ],
        "remediation": [
            "Check whether the repeated rows are true duplicates.",
            "Remove true duplicates in the source system.",
        ],
        "validation_rule": {
            "rule_type": "unique",
            "columns": ["order_id"],
            "description": "Each order_id should appear once.",
        },
        "referenced_evidence_ids": ["ev-1"],
        "referenced_columns": ["order_id"],
    }
    output.update(overrides)
    return output


# ---------------------------------------------------------------------------
# Envelope construction
# ---------------------------------------------------------------------------


def test_envelope_forwards_evidence_unchanged() -> None:
    evidence = (make_evidence(),)

    envelope = build_finding_explanation_envelope(make_finding(), evidence)

    assert envelope.computed_evidence == evidence


def test_envelope_sends_zero_samples() -> None:
    envelope = build_finding_explanation_envelope(make_finding(), (make_evidence(),))

    assert envelope.untrusted_dataset_samples == ()
    assert envelope.sample_sending_enabled is False


def test_task_text_names_only_closed_application_defined_finding_facts() -> None:
    finding = make_finding(calculated_observation="ZQXK7 untrusted observation about 'order_id'")

    task = build_finding_analysis_task(finding)

    assert task.startswith(AI_EXPLANATION_TASK)
    assert "structural.exact_duplicate_rows" in task
    assert "category structural" in task
    assert "severity medium" in task
    # The observation is built from column names (untrusted); it must never
    # be placed in the trusted task text.
    assert "ZQXK7" not in task
    assert "order_id" not in task


def test_envelope_task_is_the_per_finding_task() -> None:
    finding = make_finding()
    envelope = build_finding_explanation_envelope(finding, (make_evidence(),))
    assert envelope.task == build_finding_analysis_task(finding)


def test_envelope_carries_supplied_confirmed_context_and_defaults_to_empty() -> None:
    finding = make_finding()
    evidence = (make_evidence(),)
    assert build_finding_explanation_envelope(finding, evidence).confirmed_context == {}
    context = {"row_grain": {"value": "One row per order", "confirmation_state": "confirmed"}}
    envelope = build_finding_explanation_envelope(finding, evidence, confirmed_context=context)
    assert envelope.confirmed_context == context


# ---------------------------------------------------------------------------
# The request a provider actually receives
# ---------------------------------------------------------------------------


class _Recorder:
    """A provider double capturing every `ProviderRequest`."""

    def __init__(self, output: dict[str, Any]) -> None:
        self.requests: list[ProviderRequest] = []
        self._provider = MockProvider(response_factory=self._respond)
        self._output = output

    def _respond(self, request: ProviderRequest) -> dict[str, Any]:
        self.requests.append(request)
        return self._output

    def __getattr__(self, name: str) -> Any:
        return getattr(self._provider, name)


def test_request_carries_the_structured_contract_built_from_the_real_evidence() -> None:
    evidence = (make_evidence(),)
    envelope = build_finding_explanation_envelope(make_finding(), evidence)
    recorder = _Recorder(structured_output())

    result = run_finding_explanation(recorder, envelope, evidence)

    assert result.accepted is True
    assert len(recorder.requests) == 1
    request = recorder.requests[0]
    assert request.output_contract is not None
    assert request.output_contract.name == FINDING_ANALYSIS_CONTRACT_NAME
    properties = request.output_contract.json_schema["properties"]
    assert properties["referenced_evidence_ids"]["items"]["enum"] == ["ev-1"]  # type: ignore[index]
    assert properties["referenced_columns"]["items"]["enum"] == ["order_id"]  # type: ignore[index]
    # Only the numeric facts actually derived from the evidence.
    assert set(properties["numeric_claims"]["properties"]) == {"row_count"}  # type: ignore[index]
    assert request.known_numeric_facts == {"row_count": 2.0}


def test_request_contract_permits_no_context_fields_when_none_were_sent() -> None:
    evidence = (make_evidence(),)
    envelope = build_finding_explanation_envelope(make_finding(), evidence)
    recorder = _Recorder(structured_output())

    run_finding_explanation(recorder, envelope, evidence)

    impact = recorder.requests[0].output_contract.json_schema["properties"]["business_impact"]  # type: ignore[union-attr,index]
    assert impact["items"]["properties"]["context_fields"] == {"type": "array", "maxItems": 0}


def test_request_contract_permits_exactly_the_context_fields_that_were_sent() -> None:
    evidence = (make_evidence(),)
    context = {"row_grain": {"value": "One row per order", "confirmation_state": "confirmed"}}
    envelope = build_finding_explanation_envelope(
        make_finding(), evidence, confirmed_context=context
    )
    recorder = _Recorder(structured_output())

    run_finding_explanation(recorder, envelope, evidence)

    impact = recorder.requests[0].output_contract.json_schema["properties"]["business_impact"]  # type: ignore[union-attr,index]
    assert impact["items"]["properties"]["context_fields"]["items"]["enum"] == ["row_grain"]


# ---------------------------------------------------------------------------
# Positive path
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


def test_accepted_result_carries_all_four_sections() -> None:
    evidence = (make_evidence(),)
    envelope = build_finding_explanation_envelope(make_finding(), evidence)
    provider = MockProvider(raw_output=structured_output())

    result = run_finding_explanation(provider, envelope, evidence)

    assert result.accepted is True
    explanation = result.explanation
    assert explanation is not None
    assert explanation.narrative == "2 duplicate rows were found, so some records are repeated."
    assert [item.basis for item in explanation.business_impact] == [
        ImpactBasis.EVIDENCE,
        ImpactBasis.ASSUMPTION,
    ]
    assert explanation.business_impact[0].evidence_ids == ("ev-1",)
    assert explanation.business_impact[0].assumption is None
    assert explanation.business_impact[1].assumption == "the rows feed order-count reporting"
    assert explanation.remediation == (
        "Check whether the repeated rows are true duplicates.",
        "Remove true duplicates in the source system.",
    )
    rule = explanation.validation_rule
    assert rule is not None
    assert rule.rule_type is ValidationRuleType.UNIQUE
    assert rule.columns == (make_column("order_id"),)
    assert rule.status == "proposed"


def test_rule_columns_are_real_column_references_from_the_evidence() -> None:
    evidence = (make_evidence(affected_columns=(make_column("a", 0), make_column("b", 1))),)
    envelope = build_finding_explanation_envelope(make_finding(), evidence)
    output = structured_output(referenced_columns=["a", "b"])
    output["validation_rule"]["columns"] = ["b"]
    provider = MockProvider(raw_output=output)

    result = run_finding_explanation(provider, envelope, evidence)

    assert result.explanation is not None
    assert result.explanation.validation_rule is not None
    assert result.explanation.validation_rule.columns == (make_column("b", 1),)


# ---------------------------------------------------------------------------
# Provider identity threaded from a real response
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
# Retry-then-success path
# ---------------------------------------------------------------------------


def test_run_finding_explanation_retries_with_feedback_then_succeeds() -> None:
    evidence = (make_evidence(),)
    envelope = build_finding_explanation_envelope(make_finding(), evidence)
    seen_feedback: list[str | None] = []

    def response_factory(request: ProviderRequest) -> dict[str, Any]:
        seen_feedback.append(request.retry_feedback)
        if request.retry_feedback is None:
            return {"schema_version": "not-a-real-version"}
        return structured_output(explanation="Retried and valid explanation.")

    provider = MockProvider(response_factory=response_factory)

    result = run_finding_explanation(provider, envelope, evidence)

    assert result.accepted is True
    assert result.retries_used == 1
    assert result.explanation is not None
    assert result.explanation.narrative == "Retried and valid explanation."
    # Retry feedback is reason codes only.
    assert seen_feedback[0] is None
    assert seen_feedback[1] is not None
    assert seen_feedback[1].startswith("rejected: schema_invalid")
    assert "not-a-real-version" not in seen_feedback[1]


# ---------------------------------------------------------------------------
# Bounded retry exhaustion
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


def test_legacy_narrative_only_output_is_no_longer_accepted() -> None:
    # `FUP-011`: free prose is not an acceptable finding-analysis output any
    # more, however well-formed it is under the generic schema.
    evidence = (make_evidence(),)
    envelope = build_finding_explanation_envelope(make_finding(), evidence)
    provider = MockProvider(
        raw_output={
            "schema_version": "1",
            "narrative": "A perfectly ordinary narrative.",
            "provenance": Provenance.AI_INTERPRETATION.value,
        }
    )

    result = run_finding_explanation(provider, envelope, evidence)

    assert result.accepted is False
    assert RejectionReason.SCHEMA_INVALID in result.rejection_reasons
    assert RejectionReason.UNSUPPORTED_CONTROL_FIELD in result.rejection_reasons


# ---------------------------------------------------------------------------
# Provider-error path
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
# FindingExplanationResult invariants
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
# Known-numeric-facts extraction and grounding
# ---------------------------------------------------------------------------


def test_correct_numeric_claim_is_accepted() -> None:
    evidence = (make_evidence(structured_payload={"row_count": 2}),)
    envelope = build_finding_explanation_envelope(make_finding(), evidence)
    provider = MockProvider(raw_output=structured_output(numeric_claims={"row_count": 2}))

    assert run_finding_explanation(provider, envelope, evidence).accepted is True


def test_wrong_numeric_claim_is_rejected() -> None:
    evidence = (make_evidence(structured_payload={"row_count": 2}),)
    envelope = build_finding_explanation_envelope(make_finding(), evidence)
    provider = MockProvider(raw_output=structured_output(numeric_claims={"row_count": 5}))

    result = run_finding_explanation(provider, envelope, evidence)

    assert result.accepted is False
    assert RejectionReason.NUMERIC_CLAIM_MISMATCH in result.rejection_reasons


def test_invented_numeric_claim_key_is_rejected() -> None:
    evidence = (make_evidence(structured_payload={"row_count": 2}),)
    envelope = build_finding_explanation_envelope(make_finding(), evidence)
    provider = MockProvider(raw_output=structured_output(numeric_claims={"invented_field": 99}))

    result = run_finding_explanation(provider, envelope, evidence)

    assert result.accepted is False
    assert RejectionReason.UNKNOWN_NUMERIC_CLAIM in result.rejection_reasons


def test_an_ungrounded_number_in_prose_is_rejected() -> None:
    evidence = (make_evidence(structured_payload={"row_count": 2}),)
    envelope = build_finding_explanation_envelope(make_finding(), evidence)
    provider = MockProvider(
        raw_output=structured_output(explanation="99 duplicate rows were found.")
    )

    result = run_finding_explanation(provider, envelope, evidence)

    assert result.accepted is False
    assert RejectionReason.UNKNOWN_NUMERIC_CLAIM in result.rejection_reasons


def test_conflicting_duplicate_payload_field_is_omitted_from_the_known_facts() -> None:
    evidence = (
        make_evidence(evidence_id="ev-1", structured_payload={"row_count": 2}),
        make_evidence(evidence_id="ev-2", structured_payload={"row_count": 3}),
    )
    envelope = build_finding_explanation_envelope(make_finding(), evidence)
    recorder = _Recorder(structured_output(referenced_evidence_ids=["ev-1", "ev-2"]))

    run_finding_explanation(recorder, envelope, evidence)

    assert recorder.requests[0].known_numeric_facts == {}


def test_explanation_referenced_columns_grounded_in_evidence_not_model_claim() -> None:
    evidence = (make_evidence(affected_columns=(make_column("order_id"),)),)
    envelope = build_finding_explanation_envelope(make_finding(), evidence)
    provider = MockProvider(raw_output=structured_output(referenced_columns=[]))

    result = run_finding_explanation(provider, envelope, evidence)

    assert result.accepted is True
    assert result.explanation is not None
    assert result.explanation.referenced_columns == (make_column("order_id"),)
    assert result.explanation.referenced_evidence_ids == ("ev-1",)


# ---------------------------------------------------------------------------
# Confirmed-only context filter
# ---------------------------------------------------------------------------


def make_field(value: object, state: ConfirmationState) -> ContextFieldValue:
    return ContextFieldValue(
        value=value,
        confidence=0.9,
        inference_source=Provenance.USER_CONFIRMED
        if state in {ConfirmationState.CONFIRMED, ConfirmationState.CORRECTED}
        else Provenance.CALCULATED,
        confirmation_state=state,
        evidence_ids=(),
    )


def make_context(**overrides: ContextFieldValue) -> DatasetContext:
    unknown = make_field("", ConfirmationState.UNKNOWN)
    fields: dict[str, Any] = {
        name: unknown
        for name in (
            "probable_domain",
            "row_grain",
            "primary_entity",
            "candidate_keys",
            "business_dates",
            "measure_roles",
            "dimensions",
            "currency_behavior",
            "expected_business_rules",
        )
    }
    fields.update(overrides)
    return DatasetContext(schema_version="1", **fields)


def test_context_is_not_sent_before_finalize_even_when_confirmed() -> None:
    context = make_context(row_grain=make_field("One row per order", ConfirmationState.CONFIRMED))
    assert confirmed_context_for_finding_analysis(context, finalized=False) is None


def test_no_context_yields_none() -> None:
    assert confirmed_context_for_finding_analysis(None, finalized=True) is None


def test_finalized_context_with_only_inferred_and_unknown_fields_sends_nothing() -> None:
    context = make_context(
        probable_domain=make_field("Sales", ConfirmationState.INFERRED),
        candidate_keys=make_field(("order_id",), ConfirmationState.INFERRED),
    )
    assert confirmed_context_for_finding_analysis(context, finalized=True) is None


def test_finalized_context_sends_only_confirmed_and_corrected_fields() -> None:
    context = make_context(
        probable_domain=make_field("Sales", ConfirmationState.INFERRED),
        row_grain=make_field("One row per order", ConfirmationState.CONFIRMED),
        primary_entity=make_field("order", ConfirmationState.CORRECTED),
        candidate_keys=make_field(("order_id", "line_no"), ConfirmationState.CONFIRMED),
    )

    sent = confirmed_context_for_finding_analysis(context, finalized=True)

    assert sent is not None
    assert set(sent) == {"row_grain", "primary_entity", "candidate_keys"}
    assert sent["row_grain"] == {"value": "One row per order", "confirmation_state": "confirmed"}
    assert sent["primary_entity"] == {"value": "order", "confirmation_state": "corrected"}
    assert sent["candidate_keys"] == {
        "value": ["order_id", "line_no"],
        "confirmation_state": "confirmed",
    }
    # Never the inference confidence or source.
    for entry in sent.values():
        assert set(entry) == {"value", "confirmation_state"}  # type: ignore[call-overload]


def test_context_backed_statement_is_accepted_only_for_a_field_that_was_sent() -> None:
    evidence = (make_evidence(),)
    context = make_context(row_grain=make_field("One row per order", ConfirmationState.CONFIRMED))
    sent = confirmed_context_for_finding_analysis(context, finalized=True)
    envelope = build_finding_explanation_envelope(make_finding(), evidence, confirmed_context=sent)

    def with_context(field: str) -> dict[str, Any]:
        output = copy.deepcopy(structured_output())
        output["business_impact"].append(
            {
                "basis": "confirmed_context",
                "statement": "Each order should appear on exactly one row.",
                "evidence_ids": [],
                "context_fields": [field],
                "assumption": "",
            }
        )
        return output

    accepted = run_finding_explanation(
        MockProvider(raw_output=with_context("row_grain")), envelope, evidence
    )
    assert accepted.accepted is True
    assert accepted.explanation is not None
    assert accepted.explanation.business_impact[-1].basis is ImpactBasis.CONFIRMED_CONTEXT
    assert accepted.explanation.business_impact[-1].context_fields == ("row_grain",)

    rejected = run_finding_explanation(
        MockProvider(raw_output=with_context("probable_domain")), envelope, evidence
    )
    assert rejected.accepted is False
    assert RejectionReason.UNKNOWN_CONTEXT_FIELD in rejected.rejection_reasons


# ---------------------------------------------------------------------------
# No eval/exec
# ---------------------------------------------------------------------------


def test_no_eval_or_exec_in_ai_explanation_module() -> None:
    module_path = (
        REPO_ROOT / "backend" / "src" / "trusttable_backend" / "explanation" / "ai_explanation.py"
    )
    source = module_path.read_text(encoding="utf-8")
    assert "eval(" not in source
    assert "exec(" not in source


# ---------------------------------------------------------------------------
# Real end-to-end check against the committed demo dataset
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
    evidence_by_id = {item.evidence_id: item for item in all_evidence}

    # Every real finding's default (mock) structured analysis is accepted
    # and grounded in that finding's own evidence.
    for finding in findings:
        finding_evidence = tuple(evidence_by_id[eid] for eid in finding.evidence_ids)
        envelope = build_finding_explanation_envelope(finding, finding_evidence)

        result = run_finding_explanation(MockProvider(), envelope, finding_evidence)

        assert result.accepted is True, (finding.detector_id, result.rejection_reasons)
        assert result.explanation is not None
        assert result.explanation.referenced_evidence_ids == finding.evidence_ids
        assert result.explanation.validation_rule is not None
        assert result.explanation.business_impact
        assert result.explanation.remediation
