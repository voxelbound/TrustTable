"""Tests for type inference (PROF-02).

Covers this package's acceptance criteria AC-01..AC-12: one positive case
per `InferredColumnType` value, boundary cases (single-value columns,
partial-shape "mixed" columns), null/distinct-count correctness, and a
real-file integration-flavored check against the committed
`demo-data/sales_demo.csv` parsed through `ING-02`'s `parse_csv`.
"""

from __future__ import annotations

from pathlib import Path

from trusttable_backend.domain.value_objects import ColumnReference
from trusttable_backend.parsers.csv_parser import parse_csv
from trusttable_backend.profiling.schemas import InferredColumnType
from trusttable_backend.profiling.type_inference import infer_column_types

REPO_ROOT = Path(__file__).resolve().parents[3]
DEMO_CSV_PATH = REPO_ROOT / "demo-data" / "sales_demo.csv"


def make_columns(*names: str) -> tuple[ColumnReference, ...]:
    return tuple(
        ColumnReference(original_name=name, internal_key=name, ordinal=ordinal)
        for ordinal, name in enumerate(names)
    )


def make_rows(*rows: tuple[str | None, ...]) -> tuple[tuple[str | None, ...], ...]:
    return tuple(rows)


# ---------------------------------------------------------------------------
# AC-01: shape and ordering
# ---------------------------------------------------------------------------


def test_returns_one_profile_per_column_in_order() -> None:
    columns = make_columns("a", "b")
    rows = make_rows(("1", "x"), ("2", "y"))

    profiles = infer_column_types(columns, rows)

    assert len(profiles) == 2
    assert profiles[0].column.original_name == "a"
    assert profiles[1].column.original_name == "b"


# ---------------------------------------------------------------------------
# AC-02: NUMERIC
# ---------------------------------------------------------------------------


def test_all_numeric_column_classifies_as_numeric() -> None:
    columns = make_columns("qty")
    rows = make_rows(("1",), ("2.5",), ("-3",))

    profiles = infer_column_types(columns, rows)

    assert profiles[0].inferred_type is InferredColumnType.NUMERIC


# ---------------------------------------------------------------------------
# AC-03: DATE
# ---------------------------------------------------------------------------


def test_all_iso_date_column_classifies_as_date() -> None:
    columns = make_columns("order_date")
    rows = make_rows(("2025-05-14",), ("2025-01-12",))

    profiles = infer_column_types(columns, rows)

    assert profiles[0].inferred_type is InferredColumnType.DATE


def test_non_dashed_date_like_numeric_string_does_not_classify_as_date() -> None:
    # An 8-digit numeric string must not be misread as a basic-format ISO
    # date; only the dashed YYYY-MM-DD form counts as DATE here.
    columns = make_columns("code")
    rows = make_rows(("20250514",), ("20250101",))

    profiles = infer_column_types(columns, rows)

    assert profiles[0].inferred_type is InferredColumnType.NUMERIC


# ---------------------------------------------------------------------------
# AC-04: BOOLEAN
# ---------------------------------------------------------------------------


def test_all_boolean_token_column_classifies_as_boolean() -> None:
    columns = make_columns("active")
    rows = make_rows(("true",), ("False",), ("Yes",), ("no",))

    profiles = infer_column_types(columns, rows)

    assert profiles[0].inferred_type is InferredColumnType.BOOLEAN


# ---------------------------------------------------------------------------
# AC-05: IDENTIFIER
# ---------------------------------------------------------------------------


def test_fully_unique_non_numeric_column_classifies_as_identifier() -> None:
    columns = make_columns("order_id")
    rows = make_rows(("ORD-0001",), ("ORD-0002",), ("ORD-0003",))

    profiles = infer_column_types(columns, rows)

    assert profiles[0].inferred_type is InferredColumnType.IDENTIFIER


# ---------------------------------------------------------------------------
# AC-06: CATEGORICAL
# ---------------------------------------------------------------------------


def test_low_cardinality_column_classifies_as_categorical() -> None:
    columns = make_columns("region")
    rows = make_rows(("North",), ("South",), ("North",), ("East",), ("North",))

    profiles = infer_column_types(columns, rows)

    assert profiles[0].inferred_type is InferredColumnType.CATEGORICAL


# ---------------------------------------------------------------------------
# AC-07: TEXT
# ---------------------------------------------------------------------------


def test_high_cardinality_non_unique_text_column_classifies_as_text() -> None:
    columns = make_columns("comment")
    values = [f"Comment number {i % 25}" for i in range(60)]
    rows = make_rows(*[(value,) for value in values])

    profiles = infer_column_types(columns, rows)

    assert profiles[0].inferred_type is InferredColumnType.TEXT


# ---------------------------------------------------------------------------
# AC-08: MIXED
# ---------------------------------------------------------------------------


def test_partial_numeric_column_classifies_as_mixed_with_warning() -> None:
    columns = make_columns("value")
    rows = make_rows(("1",), ("2",), ("N/A",))

    profiles = infer_column_types(columns, rows)

    assert profiles[0].inferred_type is InferredColumnType.MIXED
    codes = {warning.code for warning in profiles[0].warnings}
    assert "profiling.mixed_column_type" in codes


def test_partial_date_column_classifies_as_mixed() -> None:
    columns = make_columns("when")
    rows = make_rows(("2025-05-14",), ("not a date",))

    profiles = infer_column_types(columns, rows)

    assert profiles[0].inferred_type is InferredColumnType.MIXED


# ---------------------------------------------------------------------------
# AC-09: UNKNOWN
# ---------------------------------------------------------------------------


def test_entirely_blank_column_classifies_as_unknown() -> None:
    columns = make_columns("empty_col")
    rows = make_rows(("",), (None,), ("",))

    profiles = infer_column_types(columns, rows)

    assert profiles[0].inferred_type is InferredColumnType.UNKNOWN
    assert profiles[0].null_count == 3
    assert profiles[0].distinct_count == 0


# ---------------------------------------------------------------------------
# AC-10: null_count / distinct_count correctness
# ---------------------------------------------------------------------------


def test_null_and_distinct_counts_treat_none_and_empty_string_alike() -> None:
    columns = make_columns("value")
    rows = make_rows(("a",), (None,), ("",), ("a",), ("b",))

    profiles = infer_column_types(columns, rows)

    assert profiles[0].null_count == 2
    assert profiles[0].distinct_count == 2


# ---------------------------------------------------------------------------
# AC-11: single-value boundary never classifies as IDENTIFIER
# ---------------------------------------------------------------------------


def test_single_non_blank_value_is_not_classified_as_identifier() -> None:
    columns = make_columns("notes")
    rows = make_rows(("",), ("",), ("only value here",), ("",))

    profiles = infer_column_types(columns, rows)

    assert profiles[0].inferred_type is not InferredColumnType.IDENTIFIER
    assert profiles[0].inferred_type is InferredColumnType.TEXT


# ---------------------------------------------------------------------------
# AC-12: real committed demo dataset
# ---------------------------------------------------------------------------


def test_infers_expected_types_for_committed_demo_csv() -> None:
    content = DEMO_CSV_PATH.read_bytes()
    parsed = parse_csv(content)

    profiles = infer_column_types(parsed.parsed_dataset.columns, parsed.rows)
    by_name = {profile.column.original_name: profile for profile in profiles}

    assert by_name["order_id"].inferred_type is InferredColumnType.IDENTIFIER
    assert by_name["order_date"].inferred_type is InferredColumnType.DATE
    for column_name in ("quantity", "unit_price", "discount_pct", "tax_pct", "line_total"):
        assert by_name[column_name].inferred_type is InferredColumnType.NUMERIC
    for column_name in ("category", "region", "status", "constant_col"):
        assert by_name[column_name].inferred_type is InferredColumnType.CATEGORICAL
    assert by_name["empty_col"].inferred_type is InferredColumnType.UNKNOWN


# ---------------------------------------------------------------------------
# AC-16: metrics always empty from this package
# ---------------------------------------------------------------------------


def test_metrics_are_always_empty() -> None:
    columns = make_columns("qty")
    rows = make_rows(("1",), ("2",))

    profiles = infer_column_types(columns, rows)

    assert profiles[0].metrics == {}
