"""Tests for validated AI context inference (CTX-02, WP-057).

Covers this package's acceptance criteria AC-01..AC-10: envelope
construction, structural sample-sending-disabled-by-default, the
positive/retry-success/retry-exhaustion/provider-error paths of
`run_context_inference`, `ContextInferenceResult`'s invariants,
`combine_hypotheses`, no-eval/exec, and a real end-to-end check against
the committed `demo-data/sales_demo.csv`.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from trusttable_backend.ai_provider.contract import ProviderRequest
from trusttable_backend.ai_provider.disabled import DisabledProvider
from trusttable_backend.ai_provider.mock import MOCK_PROVIDER_NAME, MockProvider
from trusttable_backend.context_inference.ai_context import (
    AI_CONTEXT_HYPOTHESIS_CONFIDENCE,
    DEFAULT_MAX_RETRIES,
    ContextInferenceResult,
    build_context_inference_envelope,
    combine_hypotheses,
    run_context_inference,
)
from trusttable_backend.context_inference.heuristics import (
    consolidate_dataset_context,
    infer_context_hypotheses,
    infer_dataset_context,
)
from trusttable_backend.domain.context import (
    ConfirmationState,
    ContextField,
    ContextFieldValue,
    ContextHypothesis,
    DatasetContext,
)
from trusttable_backend.domain.value_objects import ColumnReference, Provenance
from trusttable_backend.parsers.csv_parser import parse_csv
from trusttable_backend.profiling.metrics import compute_dataset_profile
from trusttable_backend.profiling.schemas import ColumnProfile, InferredColumnType

REPO_ROOT = Path(__file__).resolve().parents[3]
DEMO_CSV_PATH = REPO_ROOT / "demo-data" / "sales_demo.csv"


def make_column(name: str, ordinal: int) -> ColumnReference:
    return ColumnReference(original_name=name, internal_key=name, ordinal=ordinal)


def make_column_profile(
    column: ColumnReference, inferred_type: InferredColumnType, **overrides: object
) -> ColumnProfile:
    fields: dict[str, object] = {
        "column": column,
        "inferred_type": inferred_type,
        "null_count": 0,
        "distinct_count": 1,
        "metrics": {},
        "warnings": (),
    }
    fields.update(overrides)
    return ColumnProfile(**fields)  # type: ignore[arg-type]


def make_dataset_context() -> DatasetContext:
    return consolidate_dataset_context(())


def _role_values(field_value: ContextFieldValue) -> tuple[str, ...]:
    value = field_value.value
    assert isinstance(value, tuple)
    return value


# ---------------------------------------------------------------------------
# AC-01/AC-02: envelope construction
# ---------------------------------------------------------------------------


def test_envelope_serializes_every_dataset_context_field() -> None:
    context = make_dataset_context()

    envelope = build_context_inference_envelope(context)

    assert set(envelope.confirmed_context.keys()) == {field.value for field in ContextField}
    probable_domain_entry = envelope.confirmed_context["probable_domain"]
    assert probable_domain_entry["confirmation_state"] == "unknown"  # type: ignore[index]


def test_envelope_forwards_supplied_evidence_unchanged() -> None:
    context = make_dataset_context()

    envelope = build_context_inference_envelope(context, evidence=())

    assert envelope.computed_evidence == ()


def test_envelope_sample_sending_disabled_by_default() -> None:
    column = make_column("region", 0)
    profile = make_column_profile(
        column, InferredColumnType.CATEGORICAL, metrics={"representative_values": (("West", 5),)}
    )
    context = make_dataset_context()

    envelope = build_context_inference_envelope(context, column_profiles=(profile,))

    assert envelope.untrusted_dataset_samples == ()
    assert envelope.sample_sending_enabled is False


def test_envelope_includes_representative_values_when_enabled() -> None:
    column = make_column("region", 0)
    profile = make_column_profile(
        column, InferredColumnType.CATEGORICAL, metrics={"representative_values": (("West", 5),)}
    )
    context = make_dataset_context()

    envelope = build_context_inference_envelope(
        context, column_profiles=(profile,), sample_sending_enabled=True
    )

    assert len(envelope.untrusted_dataset_samples) == 1
    assert envelope.untrusted_dataset_samples[0].value == "West"
    assert envelope.untrusted_dataset_samples[0].column == column


def test_envelope_skips_columns_with_no_representative_values() -> None:
    column = make_column("empty_col", 0)
    profile = make_column_profile(column, InferredColumnType.UNKNOWN, metrics={})
    context = make_dataset_context()

    envelope = build_context_inference_envelope(
        context, column_profiles=(profile,), sample_sending_enabled=True
    )

    assert envelope.untrusted_dataset_samples == ()


# ---------------------------------------------------------------------------
# AC-03: positive path
# ---------------------------------------------------------------------------


def test_run_context_inference_accepts_default_mock_output() -> None:
    context = make_dataset_context()
    envelope = build_context_inference_envelope(context)
    provider = MockProvider()

    result = run_context_inference(provider, envelope)

    assert result.accepted is True
    assert result.hypothesis is not None
    assert result.hypothesis.context_field is ContextField.PROBABLE_DOMAIN
    assert result.hypothesis.confidence == AI_CONTEXT_HYPOTHESIS_CONFIDENCE
    assert result.hypothesis.provenance is Provenance.AI_INTERPRETATION
    assert result.retries_used == 0
    assert result.provider_error is None
    assert result.rejection_reasons == ()


# ---------------------------------------------------------------------------
# AC-04: retry-then-success path
# ---------------------------------------------------------------------------


def test_run_context_inference_retries_with_feedback_then_succeeds() -> None:
    context = make_dataset_context()
    envelope = build_context_inference_envelope(context)

    def response_factory(request: ProviderRequest) -> dict[str, object]:
        if request.retry_feedback is None:
            return {"schema_version": "not-a-real-version"}
        return {
            "schema_version": "1",
            "narrative": "Retried and valid.",
            "provenance": Provenance.AI_INTERPRETATION.value,
        }

    provider = MockProvider(response_factory=response_factory)

    result = run_context_inference(provider, envelope)

    assert result.accepted is True
    assert result.retries_used == 1
    assert result.hypothesis is not None
    assert result.hypothesis.proposed_value == "Retried and valid."


# ---------------------------------------------------------------------------
# AC-05: bounded retry exhaustion
# ---------------------------------------------------------------------------


def test_run_context_inference_exhausts_retries_and_rejects() -> None:
    context = make_dataset_context()
    envelope = build_context_inference_envelope(context)
    provider = MockProvider(raw_output={"schema_version": "wrong"})

    result = run_context_inference(provider, envelope)

    assert result.accepted is False
    assert result.hypothesis is None
    assert result.retries_used == DEFAULT_MAX_RETRIES
    assert result.rejection_reasons != ()
    assert result.provider_error is None


# ---------------------------------------------------------------------------
# AC-06: provider-error path
# ---------------------------------------------------------------------------


def test_run_context_inference_handles_provider_error_without_raising() -> None:
    context = make_dataset_context()
    envelope = build_context_inference_envelope(context)
    provider = DisabledProvider()

    result = run_context_inference(provider, envelope)

    assert result.accepted is False
    assert result.hypothesis is None
    assert result.retries_used == 0
    assert result.provider_error is not None
    assert "ProviderConnectionError" in result.provider_error


# ---------------------------------------------------------------------------
# AC-07: ContextInferenceResult invariants
# ---------------------------------------------------------------------------


def make_hypothesis(**overrides: object) -> ContextHypothesis:
    fields: dict[str, object] = {
        "hypothesis_id": "ctx-probable_domain-ai-1",
        "context_field": ContextField.PROBABLE_DOMAIN,
        "proposed_value": "Sales data.",
        "confidence": AI_CONTEXT_HYPOTHESIS_CONFIDENCE,
        "provenance": Provenance.AI_INTERPRETATION,
        "related_columns": (),
        "evidence_ids": (),
        "rationale": "stub",
    }
    fields.update(overrides)
    return ContextHypothesis(**fields)  # type: ignore[arg-type]


def test_context_inference_result_rejects_accepted_without_hypothesis() -> None:
    with pytest.raises(ValueError, match="hypothesis"):
        ContextInferenceResult(
            accepted=True,
            hypothesis=None,
            rejection_reasons=(),
            provider_error=None,
            retries_used=0,
        )


def test_context_inference_result_rejects_not_accepted_with_hypothesis() -> None:
    with pytest.raises(ValueError, match="hypothesis"):
        ContextInferenceResult(
            accepted=False,
            hypothesis=make_hypothesis(),
            rejection_reasons=(),
            provider_error=None,
            retries_used=0,
        )


def test_context_inference_result_rejects_negative_retries_used() -> None:
    with pytest.raises(ValueError, match="retries_used"):
        ContextInferenceResult(
            accepted=False,
            hypothesis=None,
            rejection_reasons=(),
            provider_error=None,
            retries_used=-1,
        )


# ---------------------------------------------------------------------------
# AC-08: combine_hypotheses
# ---------------------------------------------------------------------------


def test_combine_hypotheses_appends_when_accepted() -> None:
    existing = (make_hypothesis(hypothesis_id="ctx-existing-1"),)
    result = ContextInferenceResult(
        accepted=True,
        hypothesis=make_hypothesis(),
        rejection_reasons=(),
        provider_error=None,
        retries_used=0,
    )

    combined = combine_hypotheses(existing, result)

    assert combined == (*existing, result.hypothesis)


def test_combine_hypotheses_unchanged_when_not_accepted() -> None:
    existing = (make_hypothesis(hypothesis_id="ctx-existing-1"),)
    result = ContextInferenceResult(
        accepted=False,
        hypothesis=None,
        rejection_reasons=(),
        provider_error="some error",
        retries_used=0,
    )

    combined = combine_hypotheses(existing, result)

    assert combined == existing


def test_ai_hypothesis_wins_consolidation_over_heuristic_default() -> None:
    heuristic_hypothesis = ContextHypothesis(
        hypothesis_id="ctx-probable_domain-1",
        context_field=ContextField.PROBABLE_DOMAIN,
        proposed_value="Sales / order transactions",
        confidence=0.5,
        provenance=Provenance.CALCULATED,
        related_columns=(),
        evidence_ids=(),
        rationale="heuristic",
    )
    ai_result = ContextInferenceResult(
        accepted=True,
        hypothesis=make_hypothesis(proposed_value="A richer AI narrative."),
        rejection_reasons=(),
        provider_error=None,
        retries_used=0,
    )

    combined = combine_hypotheses((heuristic_hypothesis,), ai_result)
    context = consolidate_dataset_context(combined)

    assert context.probable_domain.value == "A richer AI narrative."
    assert context.probable_domain.confidence == AI_CONTEXT_HYPOTHESIS_CONFIDENCE
    assert context.probable_domain.confirmation_state is ConfirmationState.INFERRED


# ---------------------------------------------------------------------------
# AC-09: no eval/exec
# ---------------------------------------------------------------------------


def test_no_eval_or_exec_in_ai_context_module() -> None:
    module_path = (
        REPO_ROOT / "backend" / "src" / "trusttable_backend" / "context_inference" / "ai_context.py"
    )
    source = module_path.read_text(encoding="utf-8")
    assert "eval(" not in source
    assert "exec(" not in source


# ---------------------------------------------------------------------------
# AC-10: real end-to-end check against the committed demo dataset
# ---------------------------------------------------------------------------


def test_real_demo_csv_ai_context_combines_with_heuristics() -> None:
    content = DEMO_CSV_PATH.read_bytes()
    parsed = parse_csv(content)
    profile = compute_dataset_profile(
        parsed.parsed_dataset.columns,
        parsed.rows,
        parsed.parsed_dataset.sampling,
        as_of=date(2026, 8, 24),
    )
    deterministic_hypotheses = infer_context_hypotheses(profile)
    deterministic_context = infer_dataset_context(profile)
    assert deterministic_context.probable_domain.value == "Sales / order transactions"

    envelope = build_context_inference_envelope(
        deterministic_context, column_profiles=profile.column_profiles
    )
    provider = MockProvider(
        raw_output={
            "schema_version": "1",
            "narrative": "This looks like a sales/order transaction log.",
            "provenance": Provenance.AI_INTERPRETATION.value,
        }
    )

    result = run_context_inference(provider, envelope)
    combined = combine_hypotheses(deterministic_hypotheses, result)
    final_context = consolidate_dataset_context(combined)

    assert result.accepted is True
    assert final_context.probable_domain.value == "This looks like a sales/order transaction log."
    assert final_context.probable_domain.confidence == AI_CONTEXT_HYPOTHESIS_CONFIDENCE
    # Non-probable_domain fields are untouched by this package.
    assert "order_id" in _role_values(final_context.candidate_keys)
    assert provider.provider_name == MOCK_PROVIDER_NAME
