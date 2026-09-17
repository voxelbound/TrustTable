"""Tests for `domain.explanation.FindingExplanation` (`AI-05`, `WP-061`).

Covers AC-01: non-empty-narrative and provenance-membership invariants.
"""

from __future__ import annotations

import pytest

from trusttable_backend.domain.explanation import FindingExplanation
from trusttable_backend.domain.value_objects import ColumnReference, Provenance


def make_explanation(**overrides: object) -> FindingExplanation:
    fields: dict[str, object] = {
        "narrative": "This finding matters because of X.",
        "provenance": Provenance.DETERMINISTIC_FALLBACK,
        "referenced_evidence_ids": ("ev-1",),
        "referenced_columns": (),
    }
    fields.update(overrides)
    return FindingExplanation(**fields)  # type: ignore[arg-type]


def test_finding_explanation_constructs_with_deterministic_fallback_provenance() -> None:
    explanation = make_explanation(provenance=Provenance.DETERMINISTIC_FALLBACK)
    assert explanation.provenance is Provenance.DETERMINISTIC_FALLBACK


def test_finding_explanation_constructs_with_ai_interpretation_provenance() -> None:
    explanation = make_explanation(provenance=Provenance.AI_INTERPRETATION)
    assert explanation.provenance is Provenance.AI_INTERPRETATION


def test_finding_explanation_rejects_empty_narrative() -> None:
    with pytest.raises(ValueError, match="narrative"):
        make_explanation(narrative="")


@pytest.mark.parametrize(
    "provenance",
    [Provenance.CALCULATED, Provenance.USER_CONFIRMED, Provenance.USER_CORRECTED],
)
def test_finding_explanation_rejects_disallowed_provenance(provenance: Provenance) -> None:
    with pytest.raises(ValueError, match="provenance"):
        make_explanation(provenance=provenance)


def test_finding_explanation_carries_referenced_evidence_and_columns() -> None:
    column = ColumnReference(original_name="qty", internal_key="qty", ordinal=0)
    explanation = make_explanation(
        referenced_evidence_ids=("ev-1", "ev-2"), referenced_columns=(column,)
    )
    assert explanation.referenced_evidence_ids == ("ev-1", "ev-2")
    assert explanation.referenced_columns == (column,)
