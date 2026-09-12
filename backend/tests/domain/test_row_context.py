"""Tests for `domain.row_context` (`FIND-01`).

Covers `RowContextWindow`/`RowContextEntry`'s positive, negative, and
boundary invariants: exactly one anchor row, contiguous physical row
numbers, requested-vs-actual window sizes correctly bounded, truncation
flags matching those sizes, and per-row `values` length matching `columns`.
"""

from __future__ import annotations

import pytest

from trusttable_backend.domain.row_context import RowContextEntry, RowContextWindow
from trusttable_backend.domain.value_objects import ColumnReference, RowReference

_COLUMNS = (
    ColumnReference(original_name="a", internal_key="a", ordinal=0),
    ColumnReference(original_name="b", internal_key="b", ordinal=1),
)


def _entry(
    row_number: int, *, is_anchor: bool = False, is_affected: bool = False
) -> RowContextEntry:
    return RowContextEntry(
        row_reference=RowReference(row_number=row_number),
        is_anchor=is_anchor,
        is_affected_by_finding=is_affected,
        values=("v1", "v2"),
    )


def _window(**overrides: object) -> RowContextWindow:
    fields: dict[str, object] = {
        "columns": _COLUMNS,
        "requested_before": 1,
        "requested_after": 1,
        "actual_before": 1,
        "actual_after": 1,
        "truncated_at_start": False,
        "truncated_at_end": False,
        "max_window": 25,
        "rows": (
            _entry(4, is_affected=True),
            _entry(5, is_anchor=True, is_affected=True),
            _entry(6),
        ),
    }
    fields.update(overrides)
    return RowContextWindow(**fields)  # type: ignore[arg-type]


def test_valid_window_constructs() -> None:
    window = _window()
    assert window.rows[1].is_anchor is True
    assert window.actual_before == 1
    assert window.actual_after == 1


def test_requires_exactly_one_anchor() -> None:
    with pytest.raises(ValueError, match="exactly one anchor"):
        _window(rows=(_entry(4), _entry(5), _entry(6)))
    with pytest.raises(ValueError, match="exactly one anchor"):
        _window(
            rows=(
                _entry(4, is_anchor=True),
                _entry(5, is_anchor=True),
                _entry(6),
            )
        )


def test_requires_contiguous_row_numbers() -> None:
    with pytest.raises(ValueError, match="contiguous"):
        _window(
            requested_before=1,
            actual_before=1,
            rows=(_entry(4), _entry(6, is_anchor=True), _entry(7)),
        )


def test_rows_must_not_be_empty() -> None:
    with pytest.raises(ValueError, match="must not be empty"):
        _window(
            requested_before=0,
            requested_after=0,
            actual_before=0,
            actual_after=0,
            rows=(),
        )


def test_rows_length_must_match_actual_sizes() -> None:
    with pytest.raises(ValueError, match="actual_before \\+ actual_after \\+ 1"):
        _window(
            actual_before=1,
            actual_after=1,
            rows=(_entry(5, is_anchor=True),),
        )


def test_actual_must_not_exceed_requested() -> None:
    with pytest.raises(ValueError, match="actual_before must not exceed requested_before"):
        _window(requested_before=0, actual_before=1)
    with pytest.raises(ValueError, match="actual_after must not exceed requested_after"):
        _window(requested_after=0, actual_after=1)


def test_actual_must_not_exceed_max_window() -> None:
    with pytest.raises(ValueError, match="actual_before must not exceed max_window"):
        _window(
            requested_before=30,
            actual_before=30,
            max_window=25,
            rows=tuple(_entry(n, is_anchor=(n == 30)) for n in range(0, 32)),
        )


def test_truncated_at_start_must_match_actual_vs_requested() -> None:
    with pytest.raises(ValueError, match="truncated_at_start"):
        _window(truncated_at_start=True)
    with pytest.raises(ValueError, match="truncated_at_start"):
        _window(
            requested_before=2,
            actual_before=1,
            truncated_at_start=False,
            rows=(
                _entry(4, is_affected=True),
                _entry(5, is_anchor=True, is_affected=True),
                _entry(6),
            ),
        )


def test_truncated_at_end_must_match_actual_vs_requested() -> None:
    with pytest.raises(ValueError, match="truncated_at_end"):
        _window(truncated_at_end=True)


def test_boundary_zero_window_is_valid() -> None:
    window = _window(
        requested_before=0,
        requested_after=0,
        actual_before=0,
        actual_after=0,
        rows=(_entry(5, is_anchor=True),),
    )
    assert len(window.rows) == 1


def test_negative_fields_are_rejected() -> None:
    with pytest.raises(ValueError, match="requested_before"):
        _window(requested_before=-1)
    with pytest.raises(ValueError, match="requested_after"):
        _window(requested_after=-1)
    with pytest.raises(ValueError, match="actual_before"):
        _window(requested_before=0, actual_before=-1)
    with pytest.raises(ValueError, match="actual_after"):
        _window(requested_after=0, actual_after=-1)
    with pytest.raises(ValueError, match="max_window"):
        _window(max_window=-1)


def test_entry_values_length_must_match_columns() -> None:
    bad_entry = RowContextEntry(
        row_reference=RowReference(row_number=5),
        is_anchor=True,
        is_affected_by_finding=True,
        values=("only-one",),
    )
    with pytest.raises(ValueError, match="values length must match"):
        _window(
            requested_before=0,
            requested_after=0,
            actual_before=0,
            actual_after=0,
            rows=(bad_entry,),
        )


def test_no_fastapi_or_sqlalchemy_import() -> None:
    # Scoped to import lines only — the module's own docstring legitimately
    # discusses "no FastAPI/SQLAlchemy/pydantic import" while explaining
    # this package's scope, which a naive whole-file substring scan would
    # misreport as a hit (same known class as `analysis.service`'s own
    # `test_no_fastapi_or_sqlalchemy_import_in_service_module`).
    from pathlib import Path

    module_path = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "trusttable_backend"
        / "domain"
        / "row_context.py"
    )
    import_lines = [
        line
        for line in module_path.read_text(encoding="utf-8").splitlines()
        if line.startswith("import ") or line.startswith("from ")
    ]
    assert not any("fastapi" in line.lower() for line in import_lines)
    assert not any("sqlalchemy" in line.lower() for line in import_lines)
    assert not any("pydantic" in line.lower() for line in import_lines)
