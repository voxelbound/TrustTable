"""Tests for the AI provider interface (AI-01).

Covers this package's acceptance criteria AC-01..AC-09 (positive,
negative, and boundary cases for every new type and behavior), using
stub/fake providers — no real provider exists yet (`AI-02`/`AI-03`
provide those, the same precedent `DET-01`'s `WP-013` set ahead of
`DET-02`'s real detectors).
"""

from __future__ import annotations

import pytest

from trusttable_backend.ai_boundary.envelope import PromptEnvelope, UntrustedSample
from trusttable_backend.ai_boundary.validation import (
    MODEL_OUTPUT_SCHEMA_VERSION,
    validate_model_output,
)
from trusttable_backend.ai_provider.contract import (
    AIOperation,
    AIProvider,
    ProviderConnectionError,
    ProviderError,
    ProviderHealth,
    ProviderInvalidResponseError,
    ProviderRequest,
    ProviderResponse,
    ProviderTimeoutError,
)
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


def make_envelope() -> PromptEnvelope:
    sample = UntrustedSample(column=make_column("notes"), value="hello", truncated=False)
    return PromptEnvelope(
        task="Explain supplied deterministic findings.",
        computed_evidence=(make_evidence(),),
        confirmed_context={},
        untrusted_dataset_samples=(sample,),
        sample_sending_enabled=True,
    )


def well_formed_output(**overrides: object) -> dict[str, object]:
    fields: dict[str, object] = {
        "schema_version": MODEL_OUTPUT_SCHEMA_VERSION,
        "narrative": "The quantity column has a mean of 1.5.",
        "referenced_evidence_ids": ["ev-1"],
        "referenced_columns": ["quantity"],
        "numeric_claims": {"mean_quantity": 1.5},
        "severity": "medium",
        "provenance": Provenance.AI_INTERPRETATION.value,
    }
    fields.update(overrides)
    return fields


# ---------------------------------------------------------------------------
# AC-01: AIOperation
# ---------------------------------------------------------------------------


def test_ai_operation_has_exactly_six_documented_values() -> None:
    assert {member.value for member in AIOperation} == {
        "context_inference",
        "guided_questions",
        "finding_explanation",
        "remediation",
        "rule_description",
        "report_summary",
    }


# ---------------------------------------------------------------------------
# AC-02: ProviderHealth
# ---------------------------------------------------------------------------


def test_provider_health_constructs_with_all_fields() -> None:
    health = ProviderHealth(
        available=True,
        provider_name="mock",
        model_identifier="mock-v1",
        detail="reachable",
    )
    assert health.available is True
    assert health.provider_name == "mock"
    assert health.model_identifier == "mock-v1"
    assert health.detail == "reachable"


def test_provider_health_rejects_empty_provider_name() -> None:
    with pytest.raises(ValueError, match="provider_name"):
        ProviderHealth(available=False, provider_name="", model_identifier="", detail="")


# ---------------------------------------------------------------------------
# AC-03: ProviderRequest
# ---------------------------------------------------------------------------


def test_provider_request_constructs_with_default_retry_feedback() -> None:
    request = ProviderRequest(
        operation=AIOperation.FINDING_EXPLANATION,
        envelope=make_envelope(),
        known_numeric_facts={"mean_quantity": 1.5},
    )
    assert request.operation is AIOperation.FINDING_EXPLANATION
    assert isinstance(request.envelope, PromptEnvelope)
    assert request.retry_feedback is None


def test_provider_request_accepts_explicit_retry_feedback() -> None:
    request = ProviderRequest(
        operation=AIOperation.REMEDIATION,
        envelope=make_envelope(),
        known_numeric_facts={},
        retry_feedback="unknown_evidence_id: ev-99",
    )
    assert request.retry_feedback == "unknown_evidence_id: ev-99"


# ---------------------------------------------------------------------------
# AC-04: ProviderResponse
# ---------------------------------------------------------------------------


def test_provider_response_constructs_with_all_fields() -> None:
    response = ProviderResponse(
        raw_output=well_formed_output(),
        provider_name="mock",
        model_identifier="mock-v1",
        duration_ms=12.5,
    )
    assert response.provider_name == "mock"
    assert response.model_identifier == "mock-v1"
    assert response.duration_ms == 12.5


def test_provider_response_rejects_empty_provider_name() -> None:
    with pytest.raises(ValueError, match="provider_name"):
        ProviderResponse(
            raw_output=well_formed_output(),
            provider_name="",
            model_identifier="mock-v1",
            duration_ms=0.0,
        )


def test_provider_response_rejects_negative_duration() -> None:
    with pytest.raises(ValueError, match="duration_ms"):
        ProviderResponse(
            raw_output=well_formed_output(),
            provider_name="mock",
            model_identifier="mock-v1",
            duration_ms=-1.0,
        )


def test_provider_response_duration_zero_boundary_accepted() -> None:
    response = ProviderResponse(
        raw_output=well_formed_output(),
        provider_name="mock",
        model_identifier="mock-v1",
        duration_ms=0.0,
    )
    assert response.duration_ms == 0.0


def test_provider_response_raw_output_round_trips_through_validate_model_output() -> None:
    """AC-04: `ProviderResponse.raw_output` is accepted unmodified by
    `ai_boundary.validation.validate_model_output` when well-formed —
    proving this package's response shape is genuinely compatible with
    `SEC-02`'s existing validator, not merely superficially similar.
    """
    envelope = make_envelope()
    response = ProviderResponse(
        raw_output=well_formed_output(),
        provider_name="mock",
        model_identifier="mock-v1",
        duration_ms=5.0,
    )
    outcome = validate_model_output(
        response.raw_output,
        envelope,
        known_numeric_facts={"mean_quantity": 1.5},
    )
    assert outcome.accepted is True
    assert outcome.rejection_reasons == ()


# ---------------------------------------------------------------------------
# AC-05: ProviderError hierarchy
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "exception_cls",
    [ProviderTimeoutError, ProviderConnectionError, ProviderInvalidResponseError],
)
def test_provider_error_subclasses_are_provider_errors(
    exception_cls: type[ProviderError],
) -> None:
    error = exception_cls("boom")
    assert isinstance(error, ProviderError)
    assert str(error) == "boom"


def test_provider_error_subclasses_are_distinct() -> None:
    assert not issubclass(ProviderTimeoutError, ProviderConnectionError)
    assert not issubclass(ProviderTimeoutError, ProviderInvalidResponseError)
    assert not issubclass(ProviderConnectionError, ProviderInvalidResponseError)


# ---------------------------------------------------------------------------
# AC-06/AC-07: AIProvider Protocol, exception hierarchy catchability
# ---------------------------------------------------------------------------


class _StubProvider:
    """A minimal stub satisfying the `AIProvider` Protocol structurally
    (no explicit inheritance) — no real provider exists yet.
    """

    def __init__(self, *, raise_error: type[ProviderError] | None = None) -> None:
        self._raise_error = raise_error

    @property
    def provider_name(self) -> str:
        return "stub"

    def health_check(self) -> ProviderHealth:
        return ProviderHealth(
            available=True,
            provider_name=self.provider_name,
            model_identifier="stub-v1",
            detail="always available",
        )

    def complete(self, request: ProviderRequest) -> ProviderResponse:
        if self._raise_error is not None:
            raise self._raise_error("stub failure")
        return ProviderResponse(
            raw_output=well_formed_output(),
            provider_name=self.provider_name,
            model_identifier="stub-v1",
            duration_ms=1.0,
        )


def test_stub_provider_satisfies_ai_provider_protocol_structurally() -> None:
    provider: AIProvider = _StubProvider()
    assert isinstance(provider, AIProvider)
    health = provider.health_check()
    assert health.available is True
    response = provider.complete(
        ProviderRequest(
            operation=AIOperation.CONTEXT_INFERENCE,
            envelope=make_envelope(),
            known_numeric_facts={},
        )
    )
    assert response.provider_name == "stub"


@pytest.mark.parametrize(
    "exception_cls",
    [ProviderTimeoutError, ProviderConnectionError, ProviderInvalidResponseError],
)
def test_provider_errors_are_catchable_as_specific_and_base_class(
    exception_cls: type[ProviderError],
) -> None:
    provider = _StubProvider(raise_error=exception_cls)
    request = ProviderRequest(
        operation=AIOperation.REPORT_SUMMARY,
        envelope=make_envelope(),
        known_numeric_facts={},
    )

    with pytest.raises(exception_cls):
        provider.complete(request)

    with pytest.raises(ProviderError):
        provider.complete(request)


# ---------------------------------------------------------------------------
# AC-08: no forbidden imports (structural, exercised via grep in CI/local
# checks per the work package's Evidence-required section; this test only
# asserts the module imports cleanly with no network/framework side effect)
# ---------------------------------------------------------------------------


def test_module_import_has_no_side_effects_beyond_definitions() -> None:
    import trusttable_backend.ai_provider as ai_provider_module

    assert hasattr(ai_provider_module, "AIProvider")
    assert hasattr(ai_provider_module, "AIOperation")
