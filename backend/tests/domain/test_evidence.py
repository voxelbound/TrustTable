"""Tests for the evidence contracts (PROF-01).

Covers this package's acceptance criteria AC-01/AC-02: `EvidenceType`'s
closed enumeration and `Evidence`'s positive, negative, and boundary
cases.
"""

from __future__ import annotations

import pytest

from trusttable_backend.domain.evidence import Evidence, EvidenceType
from trusttable_backend.domain.parsing import SamplingScope
from trusttable_backend.domain.value_objects import ColumnReference, RowReference


def make_evidence(**overrides: object) -> Evidence:
    fields: dict[str, object] = {
        "evidence_id": "ev-1",
        "evidence_type": EvidenceType.METRIC,
        "calculation_version": "1",
        "structured_payload": {"mean": 1.5},
        "affected_columns": (),
        "affected_row_references": (),
        "scope": SamplingScope.FULL,
        "display_safe_summary": "Mean value is 1.5",
    }
    fields.update(overrides)
    return Evidence(**fields)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# AC-01: EvidenceType
# ---------------------------------------------------------------------------


def test_evidence_type_is_a_closed_enumeration() -> None:
    assert {member.value for member in EvidenceType} == {
        "metric",
        "distribution",
        "row_set",
        "category_frequency",
        "cross_field_comparison",
        "temporal_pattern",
        "security_pattern",
        "detector_configuration",
        "representative_sample",
    }


# ---------------------------------------------------------------------------
# AC-02: Evidence
# ---------------------------------------------------------------------------


def test_evidence_constructs_with_valid_fields() -> None:
    evidence = make_evidence()

    assert evidence.evidence_id == "ev-1"
    assert evidence.evidence_type is EvidenceType.METRIC
    assert evidence.structured_payload == {"mean": 1.5}


def test_evidence_is_immutable() -> None:
    evidence = make_evidence()

    with pytest.raises(AttributeError):
        evidence.evidence_id = "ev-2"  # type: ignore[misc]


def test_evidence_rejects_empty_evidence_id() -> None:
    with pytest.raises(ValueError, match="evidence_id"):
        make_evidence(evidence_id="")


def test_evidence_rejects_empty_calculation_version() -> None:
    with pytest.raises(ValueError, match="calculation_version"):
        make_evidence(calculation_version="")


def test_evidence_rejects_empty_display_safe_summary() -> None:
    with pytest.raises(ValueError, match="display_safe_summary"):
        make_evidence(display_safe_summary="")


def test_evidence_constructs_with_affected_columns_and_rows() -> None:
    column = ColumnReference(original_name="Qty", internal_key="qty", ordinal=0)
    row = RowReference(row_number=0)
    evidence = make_evidence(affected_columns=(column,), affected_row_references=(row,))

    assert evidence.affected_columns == (column,)
    assert evidence.affected_row_references == (row,)


def test_evidence_supports_every_evidence_type() -> None:
    for evidence_type in EvidenceType:
        evidence = make_evidence(evidence_type=evidence_type)
        assert evidence.evidence_type is evidence_type
