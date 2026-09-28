"""Tests for `rules.ai_generation` (`RULE-02` slice 2, `WP-081`).

Per case: `run_rule_generation` accepts only a value that is exactly one
of the supplied candidates and never retries; a `ProviderError` is
isolated into a safe `provider_error` string, never raised.
"""

from __future__ import annotations

from trusttable_backend.ai_boundary.rule_generation import RuleGenerationRejectionReason
from trusttable_backend.ai_provider.contract import (
    ProviderConnectionError,
    ProviderHealth,
    ProviderRequest,
    ProviderResponse,
)
from trusttable_backend.ai_provider.mock import MockProvider
from trusttable_backend.detectors.contract import DetectorCategory, FindingCandidate
from trusttable_backend.domain.evidence import Evidence, EvidenceType
from trusttable_backend.domain.parsing import SamplingScope
from trusttable_backend.domain.value_objects import ColumnReference, Severity
from trusttable_backend.rules.ai_generation import (
    RULE_GENERATION_TASK,
    build_rule_generation_envelope,
    run_rule_generation,
)

CANDIDATES = ("ny", "NY")


def make_finding() -> FindingCandidate:
    column = ColumnReference(original_name="city", internal_key="city", ordinal=7)
    return FindingCandidate(
        detector_id="consistency.inconsistent_capitalization",
        detector_version="1",
        category=DetectorCategory.CONSISTENCY,
        severity=Severity.LOW,
        confidence=1.0,
        calculated_observation="observed condition",
        affected_columns=(column,),
        affected_row_references=(),
        evidence_ids=("consistency.inconsistent_capitalization.evidence.city.ny",),
        default_remediation_template_key=None,
        default_validation_rule_template_key=None,
    )


def make_evidence(finding: FindingCandidate) -> tuple[Evidence, ...]:
    column = finding.affected_columns[0]
    return (
        Evidence(
            evidence_id=finding.evidence_ids[0],
            evidence_type=EvidenceType.ROW_SET,
            calculation_version="1",
            structured_payload={"distinct_casings": list(CANDIDATES), "affected_row_count": 2},
            affected_columns=(column,),
            affected_row_references=(),
            scope=SamplingScope.FULL,
            display_safe_summary="summary",
        ),
    )


# ---------------------------------------------------------------------------
# build_rule_generation_envelope
# ---------------------------------------------------------------------------


def test_envelope_carries_the_fixed_task_and_the_findings_own_evidence() -> None:
    finding = make_finding()
    evidence = make_evidence(finding)

    envelope = build_rule_generation_envelope(finding, evidence)

    assert envelope.task == RULE_GENERATION_TASK
    assert len(envelope.computed_evidence) == 1
    assert envelope.sample_sending_enabled is False
    assert envelope.untrusted_dataset_samples == ()


def test_envelope_uses_the_neutral_provider_alias_not_the_canonical_evidence_id() -> None:
    """`InconsistentCapitalizationDetector`'s own evidence id embeds the
    normalized cell value — a provider must only ever see the neutral
    positional alias."""
    finding = make_finding()
    evidence = make_evidence(finding)

    envelope = build_rule_generation_envelope(finding, evidence)

    assert envelope.computed_evidence[0].evidence_id == "evidence_1"
    assert envelope.computed_evidence[0].evidence_id != finding.evidence_ids[0]


# ---------------------------------------------------------------------------
# run_rule_generation: acceptance
# ---------------------------------------------------------------------------


def test_accepts_the_mock_providers_default_contract_grounded_answer() -> None:
    """With no caller-supplied output, `MockProvider` falls through to the
    request's own `output_contract.mock_output_factory` — always one of
    the exact supplied candidates, so it is always accepted."""
    finding = make_finding()
    evidence = make_evidence(finding)
    envelope = build_rule_generation_envelope(finding, evidence)
    provider = MockProvider()

    result = run_rule_generation(provider, envelope, CANDIDATES)

    assert result.accepted is True
    assert result.canonical_value in CANDIDATES
    assert result.rejection_reasons == ()
    assert result.provider_error is None


def test_accepts_a_provider_choosing_the_other_exact_candidate() -> None:
    finding = make_finding()
    evidence = make_evidence(finding)
    envelope = build_rule_generation_envelope(finding, evidence)
    provider = MockProvider(
        raw_output={
            "schema_version": "rule_generation_v1",
            "provenance": "ai_interpretation",
            "canonical_value": "ny",
        }
    )

    result = run_rule_generation(provider, envelope, CANDIDATES)

    assert result.accepted is True
    assert result.canonical_value == "ny"


# ---------------------------------------------------------------------------
# run_rule_generation: rejection (an invented value)
# ---------------------------------------------------------------------------


def test_rejects_a_provider_inventing_a_value_outside_the_candidates() -> None:
    finding = make_finding()
    evidence = make_evidence(finding)
    envelope = build_rule_generation_envelope(finding, evidence)
    provider = MockProvider(
        raw_output={
            "schema_version": "rule_generation_v1",
            "provenance": "ai_interpretation",
            "canonical_value": "New York",
        }
    )

    result = run_rule_generation(provider, envelope, CANDIDATES)

    assert result.accepted is False
    assert result.canonical_value is None
    assert RuleGenerationRejectionReason.VALUE_NOT_CANDIDATE in result.rejection_reasons
    assert result.provider_error is None


def test_never_retries_a_rejected_first_attempt() -> None:
    """Unlike `run_finding_explanation`'s bounded retry loop, a rejected
    answer here is final: the schema already constrains the choice to a
    closed enum, so a second call would not change anything."""
    finding = make_finding()
    evidence = make_evidence(finding)
    envelope = build_rule_generation_envelope(finding, evidence)
    call_count = 0

    def response_factory(request: ProviderRequest) -> dict[str, object]:
        nonlocal call_count
        call_count += 1
        return {
            "schema_version": "rule_generation_v1",
            "provenance": "ai_interpretation",
            "canonical_value": "invented",
        }

    provider = MockProvider(response_factory=response_factory)
    result = run_rule_generation(provider, envelope, CANDIDATES)

    assert result.accepted is False
    assert call_count == 1


# ---------------------------------------------------------------------------
# run_rule_generation: provider error isolation
# ---------------------------------------------------------------------------


class _FailingProvider:
    """A minimal `AIProvider` whose `complete()` always raises."""

    @property
    def provider_name(self) -> str:
        return "failing"

    def health_check(self) -> ProviderHealth:
        return ProviderHealth(
            available=False, provider_name="failing", model_identifier="none", detail="down"
        )

    def complete(self, request: ProviderRequest) -> ProviderResponse:
        del request
        raise ProviderConnectionError("connection refused")


def test_provider_error_is_isolated_into_a_safe_string_never_raised() -> None:
    finding = make_finding()
    evidence = make_evidence(finding)
    envelope = build_rule_generation_envelope(finding, evidence)

    result = run_rule_generation(_FailingProvider(), envelope, CANDIDATES)

    assert result.accepted is False
    assert result.canonical_value is None
    assert result.rejection_reasons == ()
    assert result.provider_error is not None
    assert "ProviderConnectionError" in result.provider_error
