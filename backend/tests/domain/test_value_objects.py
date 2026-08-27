"""Tests for the shared value objects (ING-01).

Covers this package's acceptance criteria AC-01 (`ColumnReference`) and
AC-02 (`RowReference`): positive, negative (invariant-violation), and
boundary cases.
"""

from __future__ import annotations

import pytest

from trusttable_backend.domain.value_objects import ColumnReference, RowReference

# ---------------------------------------------------------------------------
# AC-01: ColumnReference
# ---------------------------------------------------------------------------


def test_column_reference_constructs_with_valid_fields() -> None:
    ref = ColumnReference(original_name="Order Date", internal_key="order_date", ordinal=0)

    assert ref.original_name == "Order Date"
    assert ref.internal_key == "order_date"
    assert ref.ordinal == 0


def test_column_reference_is_immutable() -> None:
    ref = ColumnReference(original_name="Order Date", internal_key="order_date", ordinal=0)

    with pytest.raises(AttributeError):
        ref.ordinal = 1  # type: ignore[misc]


def test_column_reference_rejects_empty_original_name() -> None:
    with pytest.raises(ValueError, match="original_name"):
        ColumnReference(original_name="", internal_key="order_date", ordinal=0)


def test_column_reference_rejects_empty_internal_key() -> None:
    with pytest.raises(ValueError, match="internal_key"):
        ColumnReference(original_name="Order Date", internal_key="", ordinal=0)


def test_column_reference_rejects_negative_ordinal() -> None:
    with pytest.raises(ValueError, match="ordinal"):
        ColumnReference(original_name="Order Date", internal_key="order_date", ordinal=-1)


def test_column_reference_accepts_zero_ordinal_boundary() -> None:
    ref = ColumnReference(original_name="Order Date", internal_key="order_date", ordinal=0)
    assert ref.ordinal == 0


# ---------------------------------------------------------------------------
# AC-02: RowReference
# ---------------------------------------------------------------------------


def test_row_reference_constructs_with_row_number_only() -> None:
    ref = RowReference(row_number=5)

    assert ref.row_number == 5
    assert ref.source_line_number is None
    assert ref.fingerprint is None


def test_row_reference_constructs_with_all_fields() -> None:
    ref = RowReference(row_number=5, source_line_number=7, fingerprint="abc123")

    assert ref.row_number == 5
    assert ref.source_line_number == 7
    assert ref.fingerprint == "abc123"


def test_row_reference_is_immutable() -> None:
    ref = RowReference(row_number=5)

    with pytest.raises(AttributeError):
        ref.row_number = 6  # type: ignore[misc]


def test_row_reference_rejects_negative_row_number() -> None:
    with pytest.raises(ValueError, match="row_number"):
        RowReference(row_number=-1)


def test_row_reference_accepts_zero_row_number_boundary() -> None:
    ref = RowReference(row_number=0)
    assert ref.row_number == 0
