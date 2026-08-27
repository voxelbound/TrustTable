"""Tests for the secure CSV parser (ING-02).

Covers this package's acceptance criteria AC-01..AC-13: fatal-rejection
cases, graceful-degradation (warning) cases, delimiter detection, the
never-execute-content guarantee, sampling/row-reference invariants,
deterministic hashing, and a real-file integration-flavored check against
the committed `demo-data/sales_demo.csv`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from trusttable_backend.demo_data.generator import COLUMN_NAMES, ROW_COUNT
from trusttable_backend.domain.parsing import DatasetFormat, SamplingScope
from trusttable_backend.parsers.csv_parser import (
    CsvParseError,
    CsvParseLimits,
    parse_csv,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
DEMO_CSV_PATH = REPO_ROOT / "demo-data" / "sales_demo.csv"


def _warning_codes(warnings: object) -> set[str]:
    return {w.code for w in warnings}  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# AC-01/AC-02/AC-03: fatal decode/structure rejections
# ---------------------------------------------------------------------------


def test_rejects_empty_content() -> None:
    with pytest.raises(CsvParseError, match="empty"):
        parse_csv(b"")


def test_rejects_undecodable_bytes() -> None:
    with pytest.raises(CsvParseError, match="UTF-8"):
        parse_csv(b"a,b,c\n\xff\xfe,2,3\n")


def test_strips_utf8_bom_from_first_column_name() -> None:
    content = "name,value\nAlice,1\n".encode("utf-8-sig")
    result = parse_csv(content)
    assert result.parsed_dataset.columns[0].original_name == "name"


def test_rejects_blank_header_row() -> None:
    with pytest.raises(CsvParseError, match="header"):
        parse_csv(b"\n")


# ---------------------------------------------------------------------------
# AC-04: hard resource-limit rejections
# ---------------------------------------------------------------------------


def test_rejects_header_column_count_over_limit() -> None:
    header = ",".join(f"col{i}" for i in range(5))
    limits = CsvParseLimits(max_columns=4)
    with pytest.raises(CsvParseError, match="columns"):
        parse_csv(f"{header}\n1,2,3,4,5\n".encode(), limits=limits)


def test_accepts_header_column_count_at_limit_boundary() -> None:
    header = ",".join(f"col{i}" for i in range(4))
    limits = CsvParseLimits(max_columns=4)
    result = parse_csv(f"{header}\n1,2,3,4\n".encode(), limits=limits)
    assert len(result.parsed_dataset.columns) == 4


def test_rejects_row_count_over_limit() -> None:
    limits = CsvParseLimits(max_rows=2)
    content = b"a,b\n1,2\n3,4\n5,6\n"
    with pytest.raises(CsvParseError, match="rows"):
        parse_csv(content, limits=limits)


def test_accepts_row_count_at_limit_boundary() -> None:
    limits = CsvParseLimits(max_rows=2)
    content = b"a,b\n1,2\n3,4\n"
    result = parse_csv(content, limits=limits)
    assert result.parsed_dataset.row_count == 2


def test_rejects_content_over_byte_limit() -> None:
    limits = CsvParseLimits(max_bytes=10)
    with pytest.raises(CsvParseError, match="bytes"):
        parse_csv(b"a,b,c\n1,2,3\n", limits=limits)


# ---------------------------------------------------------------------------
# AC-05/AC-06: column naming
# ---------------------------------------------------------------------------


def test_builds_column_references_preserving_original_name() -> None:
    result = parse_csv(b"Order ID,Qty\n1,2\n")
    columns = result.parsed_dataset.columns
    assert columns[0].original_name == "Order ID"
    assert columns[0].internal_key == "order_id"
    assert columns[1].original_name == "Qty"
    assert columns[1].internal_key == "qty"


def test_deduplicates_colliding_internal_keys_with_warning() -> None:
    result = parse_csv(b"Order ID,order id\n1,2\n")
    columns = result.parsed_dataset.columns
    assert columns[0].internal_key == "order_id"
    assert columns[1].internal_key == "order_id_2"
    assert "parsing.duplicate_column_name" in _warning_codes(result.parsed_dataset.parsing_warnings)


def test_empty_header_cell_gets_placeholder_name_with_warning() -> None:
    result = parse_csv(b"a,,c\n1,2,3\n")
    columns = result.parsed_dataset.columns
    assert columns[1].original_name == "column_1"
    assert "parsing.empty_column_name" in _warning_codes(result.parsed_dataset.parsing_warnings)


def test_over_long_column_name_is_truncated_with_warning() -> None:
    long_name = "x" * 300
    limits = CsvParseLimits(max_column_name_length=10)
    result = parse_csv(f"{long_name},b\n1,2\n".encode(), limits=limits)
    assert len(result.parsed_dataset.columns[0].original_name) == 10
    assert "parsing.column_name_truncated" in _warning_codes(result.parsed_dataset.parsing_warnings)


# ---------------------------------------------------------------------------
# AC-07: ragged rows
# ---------------------------------------------------------------------------


def test_short_row_is_padded_with_none_and_warns() -> None:
    result = parse_csv(b"a,b,c\n1,2\n")
    assert result.rows[0] == ("1", "2", None)
    assert "parsing.ragged_row" in _warning_codes(result.parsed_dataset.parsing_warnings)


def test_long_row_is_truncated_and_warns() -> None:
    result = parse_csv(b"a,b\n1,2,3,4\n")
    assert result.rows[0] == ("1", "2")
    assert "parsing.ragged_row" in _warning_codes(result.parsed_dataset.parsing_warnings)


def test_well_formed_row_produces_no_ragged_warning() -> None:
    result = parse_csv(b"a,b\n1,2\n")
    assert "parsing.ragged_row" not in _warning_codes(result.parsed_dataset.parsing_warnings)


# ---------------------------------------------------------------------------
# AC-08: over-long field values
# ---------------------------------------------------------------------------


def test_over_long_field_value_is_truncated_with_warning() -> None:
    limits = CsvParseLimits(max_field_length=5)
    result = parse_csv(f"a,b\n{'x' * 20},2\n".encode(), limits=limits)
    assert result.rows[0][0] == "x" * 5
    assert "parsing.field_value_truncated" in _warning_codes(result.parsed_dataset.parsing_warnings)


def test_field_value_at_limit_boundary_is_not_truncated() -> None:
    limits = CsvParseLimits(max_field_length=5)
    result = parse_csv(f"a,b\n{'x' * 5},2\n".encode(), limits=limits)
    assert result.rows[0][0] == "x" * 5
    assert "parsing.field_value_truncated" not in _warning_codes(
        result.parsed_dataset.parsing_warnings
    )


# ---------------------------------------------------------------------------
# AC-09: delimiter detection
# ---------------------------------------------------------------------------


def test_detects_semicolon_delimiter() -> None:
    result = parse_csv(b"a;b;c\n1;2;3\n")
    assert len(result.parsed_dataset.columns) == 3
    assert result.rows[0] == ("1", "2", "3")


def test_detects_tab_delimiter() -> None:
    result = parse_csv(b"a\tb\tc\n1\t2\t3\n")
    assert len(result.parsed_dataset.columns) == 3


def test_detects_pipe_delimiter() -> None:
    result = parse_csv(b"a|b|c\n1|2|3\n")
    assert len(result.parsed_dataset.columns) == 3


def test_defaults_to_comma_when_inconclusive() -> None:
    result = parse_csv(b"single_column\nvalue\n")
    assert len(result.parsed_dataset.columns) == 1
    assert result.parsed_dataset.columns[0].original_name == "single_column"


# ---------------------------------------------------------------------------
# AC-10: never executes content
# ---------------------------------------------------------------------------


def test_formula_like_value_is_read_as_literal_text() -> None:
    result = parse_csv(b"a,b\n=SUM(A1:A2),2\n")
    assert result.rows[0][0] == "=SUM(A1:A2)"


def test_module_source_contains_no_eval_or_exec_call() -> None:
    from trusttable_backend.parsers import csv_parser

    source = Path(csv_parser.__file__).read_text(encoding="utf-8")
    assert "eval(" not in source
    assert "exec(" not in source


# ---------------------------------------------------------------------------
# AC-11: sampling / row-reference invariants
# ---------------------------------------------------------------------------


def test_sampling_is_always_full_scope() -> None:
    result = parse_csv(b"a,b\n1,2\n3,4\n")
    sampling = result.parsed_dataset.sampling
    assert sampling.scope is SamplingScope.FULL
    assert sampling.population_size == sampling.sample_size == 2


def test_row_references_match_row_order() -> None:
    result = parse_csv(b"a\n10\n20\n30\n")
    row_references = result.parsed_dataset.row_references
    assert [ref.row_number for ref in row_references] == [0, 1, 2]


def test_header_only_file_produces_zero_rows() -> None:
    result = parse_csv(b"a,b,c\n")
    assert result.parsed_dataset.row_count == 0
    assert result.parsed_dataset.row_references == ()
    assert result.parsed_dataset.sampling.population_size == 0


# ---------------------------------------------------------------------------
# AC-12: content hash / byte size
# ---------------------------------------------------------------------------


def test_content_hash_and_byte_size_are_deterministic() -> None:
    content = b"a,b\n1,2\n"
    first = parse_csv(content)
    second = parse_csv(content)
    assert first.content_hash == second.content_hash
    assert first.byte_size == second.byte_size == len(content)


def test_different_content_produces_different_hash() -> None:
    first = parse_csv(b"a,b\n1,2\n")
    second = parse_csv(b"a,b\n1,3\n")
    assert first.content_hash != second.content_hash


# ---------------------------------------------------------------------------
# AC-13: real committed demo dataset
# ---------------------------------------------------------------------------


def test_parses_committed_demo_csv_with_expected_shape() -> None:
    content = DEMO_CSV_PATH.read_bytes()
    result = parse_csv(content)

    assert len(result.parsed_dataset.columns) == len(COLUMN_NAMES)
    assert result.parsed_dataset.row_count == ROW_COUNT
    assert result.parsed_dataset.format is DatasetFormat.CSV

    internal_keys = [c.internal_key for c in result.parsed_dataset.columns]
    ordinals = [c.ordinal for c in result.parsed_dataset.columns]
    assert len(internal_keys) == len(set(internal_keys))
    assert len(ordinals) == len(set(ordinals))
