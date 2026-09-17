"""Tests for the dataset context contracts (CTX-01).

Covers this package's acceptance criterion AC-01: `ContextField`'s and
`ConfirmationState`'s closed enumerations, and `ContextHypothesis`/
`ContextFieldValue`/`DatasetContext`'s positive, negative, and boundary
cases.
"""

from __future__ import annotations

import pytest

from trusttable_backend.domain.context import (
    ConfirmationState,
    ContextField,
    ContextFieldValue,
    ContextHypothesis,
    DatasetContext,
)
from trusttable_backend.domain.value_objects import ColumnReference, Provenance


def make_hypothesis(**overrides: object) -> ContextHypothesis:
    fields: dict[str, object] = {
        "hypothesis_id": "ctx-1",
        "context_field": ContextField.CANDIDATE_KEYS,
        "proposed_value": "order_id",
        "confidence": 0.9,
        "provenance": Provenance.CALCULATED,
        "related_columns": (),
        "evidence_ids": (),
        "rationale": "Column 'order_id' is inferred as IDENTIFIER.",
    }
    fields.update(overrides)
    return ContextHypothesis(**fields)  # type: ignore[arg-type]


def make_field_value(**overrides: object) -> ContextFieldValue:
    fields: dict[str, object] = {
        "value": "order",
        "confidence": 0.55,
        "inference_source": Provenance.CALCULATED,
        "confirmation_state": ConfirmationState.INFERRED,
        "evidence_ids": (),
    }
    fields.update(overrides)
    return ContextFieldValue(**fields)  # type: ignore[arg-type]


def make_dataset_context(**overrides: object) -> DatasetContext:
    fields: dict[str, object] = {
        "schema_version": "1",
        "probable_domain": make_field_value(value="unknown", confidence=0.0),
        "row_grain": make_field_value(value="One row per order_id"),
        "primary_entity": make_field_value(value="order"),
        "candidate_keys": make_field_value(value=("order_id",), confidence=0.9),
        "business_dates": make_field_value(value=("order_date",), confidence=0.9),
        "measure_roles": make_field_value(value=("quantity",), confidence=0.75),
        "dimensions": make_field_value(value=("region",), confidence=0.7),
        "currency_behavior": make_field_value(value="unknown", confidence=0.0),
        "expected_business_rules": make_field_value(value="unknown", confidence=0.0),
    }
    fields.update(overrides)
    return DatasetContext(**fields)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# ContextField / ConfirmationState closed enumerations
# ---------------------------------------------------------------------------


def test_context_field_is_a_closed_enumeration() -> None:
    assert {member.value for member in ContextField} == {
        "probable_domain",
        "row_grain",
        "primary_entity",
        "candidate_keys",
        "business_dates",
        "measure_roles",
        "dimensions",
        "currency_behavior",
        "expected_business_rules",
    }


def test_confirmation_state_is_a_closed_enumeration() -> None:
    assert {member.value for member in ConfirmationState} == {
        "inferred",
        "confirmed",
        "corrected",
        "unknown",
    }


# ---------------------------------------------------------------------------
# ContextHypothesis
# ---------------------------------------------------------------------------


def test_context_hypothesis_constructs_with_valid_fields() -> None:
    hypothesis = make_hypothesis()

    assert hypothesis.hypothesis_id == "ctx-1"
    assert hypothesis.context_field is ContextField.CANDIDATE_KEYS
    assert hypothesis.proposed_value == "order_id"
    assert hypothesis.superseded is False


def test_context_hypothesis_is_immutable() -> None:
    hypothesis = make_hypothesis()

    with pytest.raises(AttributeError):
        hypothesis.proposed_value = "other"  # type: ignore[misc]


def test_context_hypothesis_rejects_empty_hypothesis_id() -> None:
    with pytest.raises(ValueError, match="hypothesis_id"):
        make_hypothesis(hypothesis_id="")


def test_context_hypothesis_rejects_empty_proposed_value() -> None:
    with pytest.raises(ValueError, match="proposed_value"):
        make_hypothesis(proposed_value="")


def test_context_hypothesis_rejects_empty_rationale() -> None:
    with pytest.raises(ValueError, match="rationale"):
        make_hypothesis(rationale="")


@pytest.mark.parametrize("confidence", [-0.01, 1.01])
def test_context_hypothesis_rejects_confidence_outside_unit_interval(confidence: float) -> None:
    with pytest.raises(ValueError, match="confidence"):
        make_hypothesis(confidence=confidence)


@pytest.mark.parametrize("confidence", [0.0, 1.0])
def test_context_hypothesis_accepts_confidence_boundary(confidence: float) -> None:
    hypothesis = make_hypothesis(confidence=confidence)
    assert hypothesis.confidence == confidence


def test_context_hypothesis_supports_related_columns_and_evidence_ids() -> None:
    column = ColumnReference(original_name="order_id", internal_key="order_id", ordinal=0)
    hypothesis = make_hypothesis(related_columns=(column,), evidence_ids=("ev-1",))

    assert hypothesis.related_columns == (column,)
    assert hypothesis.evidence_ids == ("ev-1",)


def test_context_hypothesis_supports_superseded_flag() -> None:
    hypothesis = make_hypothesis(superseded=True)
    assert hypothesis.superseded is True


def test_context_hypothesis_supports_every_context_field() -> None:
    for context_field in ContextField:
        hypothesis = make_hypothesis(context_field=context_field)
        assert hypothesis.context_field is context_field


# ---------------------------------------------------------------------------
# ContextFieldValue
# ---------------------------------------------------------------------------


def test_context_field_value_constructs_with_valid_fields() -> None:
    field_value = make_field_value()

    assert field_value.value == "order"
    assert field_value.confirmation_state is ConfirmationState.INFERRED


def test_context_field_value_is_immutable() -> None:
    field_value = make_field_value()

    with pytest.raises(AttributeError):
        field_value.value = "other"  # type: ignore[misc]


@pytest.mark.parametrize("confidence", [-0.01, 1.01])
def test_context_field_value_rejects_confidence_outside_unit_interval(confidence: float) -> None:
    with pytest.raises(ValueError, match="confidence"):
        make_field_value(confidence=confidence)


def test_context_field_value_supports_tuple_value_for_role_fields() -> None:
    field_value = make_field_value(value=("order_id", "customer_id"))
    assert field_value.value == ("order_id", "customer_id")


def test_context_field_value_supports_unknown_state() -> None:
    field_value = make_field_value(
        value="unknown", confidence=0.0, confirmation_state=ConfirmationState.UNKNOWN
    )
    assert field_value.confirmation_state is ConfirmationState.UNKNOWN
    assert field_value.confidence == 0.0


# ---------------------------------------------------------------------------
# DatasetContext
# ---------------------------------------------------------------------------


def test_dataset_context_constructs_with_valid_fields() -> None:
    context = make_dataset_context()

    assert context.schema_version == "1"
    assert context.primary_entity.value == "order"
    assert context.candidate_keys.value == ("order_id",)


def test_dataset_context_is_immutable() -> None:
    context = make_dataset_context()

    with pytest.raises(AttributeError):
        context.schema_version = "2"  # type: ignore[misc]


def test_dataset_context_rejects_empty_schema_version() -> None:
    with pytest.raises(ValueError, match="schema_version"):
        make_dataset_context(schema_version="")


def test_dataset_context_supports_all_unknown_fields() -> None:
    unknown = make_field_value(
        value="unknown", confidence=0.0, confirmation_state=ConfirmationState.UNKNOWN
    )
    unknown_role = make_field_value(
        value=(), confidence=0.0, confirmation_state=ConfirmationState.UNKNOWN
    )
    context = make_dataset_context(
        probable_domain=unknown,
        row_grain=unknown,
        primary_entity=unknown,
        candidate_keys=unknown_role,
        business_dates=unknown_role,
        measure_roles=unknown_role,
        dimensions=unknown_role,
        currency_behavior=unknown,
        expected_business_rules=unknown,
    )

    assert context.currency_behavior.confirmation_state is ConfirmationState.UNKNOWN
    assert context.candidate_keys.value == ()
