"""The `confirmed_context` envelope slot: documentation pinned to behavior
(FUP-012, `docs/decision-log.md` D-042).

`docs/architecture.md` section 7 says the slot carries dataset context
together with each field's own `confirmation_state`; that the context-inference
call deliberately sends inferred and unknown fields as such; and that an
AI-sourced context result is only ever a proposed hypothesis. These tests tie
each of those statements to the real code, and pin the statements themselves so
a later edit cannot quietly drop the qualification.

The complementary claim — that the *finding-analysis* call sends only
user-confirmed or corrected fields of a finalized context — is proven through
the real route and a request-capturing provider in
`tests/api/test_finding_analysis_end_to_end.py`, not duplicated here.
"""

from __future__ import annotations

import re
from dataclasses import replace
from pathlib import Path

from trusttable_backend.ai_provider.mock import MockProvider
from trusttable_backend.context_inference.ai_context import (
    AI_CONTEXT_HYPOTHESIS_CONFIDENCE,
    build_context_inference_envelope,
    combine_hypotheses,
    run_context_inference,
    serialize_dataset_context,
)
from trusttable_backend.context_inference.heuristics import consolidate_dataset_context
from trusttable_backend.domain.context import (
    ConfirmationState,
    ContextField,
    ContextFieldValue,
    DatasetContext,
)
from trusttable_backend.domain.value_objects import Provenance

REPO_ROOT = Path(__file__).resolve().parents[3]
ARCHITECTURE = REPO_ROOT / "docs" / "architecture.md"
DECISION_LOG = REPO_ROOT / "docs" / "decision-log.md"


def _normalized(path: Path) -> str:
    return re.sub(r"\s+", " ", path.read_text(encoding="utf-8"))


def _mixed_state_context() -> DatasetContext:
    """One field in each of the four states, so a serializer that flattened
    or dropped the per-field state would be caught."""
    base = consolidate_dataset_context(())  # every field starts `unknown`
    return replace(
        base,
        probable_domain=ContextFieldValue(
            value="Sales orders",
            confidence=1.0,
            inference_source=Provenance.USER_CONFIRMED,
            confirmation_state=ConfirmationState.CONFIRMED,
            evidence_ids=(),
        ),
        row_grain=ContextFieldValue(
            value="One row per order",
            confidence=1.0,
            inference_source=Provenance.USER_CORRECTED,
            confirmation_state=ConfirmationState.CORRECTED,
            evidence_ids=(),
        ),
        primary_entity=ContextFieldValue(
            value="order",
            confidence=0.5,
            inference_source=Provenance.CALCULATED,
            confirmation_state=ConfirmationState.INFERRED,
            evidence_ids=(),
        ),
    )


def test_every_field_is_serialized_with_its_own_confirmation_state() -> None:
    serialized = serialize_dataset_context(_mixed_state_context())

    assert set(serialized) == {field.value for field in ContextField}
    for entry in serialized.values():
        assert isinstance(entry, dict)
        assert set(entry) == {"value", "confidence", "confirmation_state"}
    states = {name: entry["confirmation_state"] for name, entry in serialized.items()}  # type: ignore[index]
    assert states["probable_domain"] == "confirmed"
    assert states["row_grain"] == "corrected"
    assert states["primary_entity"] == "inferred"
    assert states["currency_behavior"] == "unknown"


def test_the_context_inference_envelope_sends_inferred_and_unknown_fields_as_such() -> None:
    envelope = build_context_inference_envelope(_mixed_state_context())

    slot = envelope.confirmed_context
    assert slot["primary_entity"]["confirmation_state"] == "inferred"  # type: ignore[index]
    assert slot["currency_behavior"]["confirmation_state"] == "unknown"  # type: ignore[index]
    # Nothing is relabelled as confirmed on the way in: exactly the fields that
    # were confirmed or corrected carry those states.
    confirmed_like = {
        name
        for name, entry in slot.items()
        if entry["confirmation_state"] in {"confirmed", "corrected"}  # type: ignore[index]
    }
    assert confirmed_like == {"probable_domain", "row_grain"}


def test_an_accepted_ai_context_result_is_only_a_proposed_hypothesis() -> None:
    context = consolidate_dataset_context(())
    envelope = build_context_inference_envelope(context)

    result = run_context_inference(MockProvider(), envelope)

    assert result.accepted
    assert result.hypothesis is not None
    assert result.hypothesis.provenance is Provenance.AI_INTERPRETATION
    assert result.hypothesis.confidence == AI_CONTEXT_HYPOTHESIS_CONFIDENCE

    consolidated = consolidate_dataset_context(combine_hypotheses((), result))
    # The AI narrative became the effective value, but it is still only inferred:
    # nothing marks it confirmed until a user confirms or corrects it.
    assert consolidated.probable_domain.confirmation_state is ConfirmationState.INFERRED
    assert consolidated.probable_domain.confirmation_state not in {
        ConfirmationState.CONFIRMED,
        ConfirmationState.CORRECTED,
    }


def test_the_architecture_document_records_the_slot_semantics() -> None:
    text = _normalized(ARCHITECTURE)

    assert "What the `confirmed_context` slot carries (D-042)" in text
    assert "together with each field's own `confirmation_state`" in text
    for state in ("confirmed", "corrected", "inferred", "unknown"):
        assert f"`{state}`" in text
    assert "inferred and unknown ones included and labelled as such" in text
    assert "only user-confirmed or corrected fields of a finalized context" in text
    assert "only ever a proposed hypothesis" in text
    assert "not marked confirmed until the user confirms or corrects it" in text
    assert "Renaming or splitting the slot remains an open option" in text


def test_the_decision_log_records_the_slot_decision_and_leaves_the_rename_open() -> None:
    text = _normalized(DECISION_LOG)

    assert "## D-042" in text
    assert "The slot is documented, not renamed." in text
    assert "**left open**, not rejected" in text
