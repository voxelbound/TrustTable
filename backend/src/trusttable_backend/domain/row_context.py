"""Row-context domain contracts (`FIND-01`), matching `docs/domain-model.md`
§13's "Row context (non-Evidence)" subsection.

Explicitly not `Evidence` (`domain.evidence`): row context is a live,
on-demand inspection capability, not a precomputed/curated finding-support
object. Framework-independent: no FastAPI/SQLAlchemy/pydantic import.
Stdlib only (`dataclasses`).
"""

from __future__ import annotations

from dataclasses import dataclass

from .value_objects import ColumnReference, RowReference


@dataclass(frozen=True, slots=True)
class RowContextEntry:
    """One row in a `RowContextWindow` (`docs/domain-model.md` §13: "its
    existing RowReference, is_anchor, is_affected_by_finding, and values
    by column").

    `values` is positional, aligned with the owning `RowContextWindow.columns`
    tuple by index (matching `parsers.csv_parser.CsvParseResult.rows`' own
    existing column-ordinal alignment) — not a mapping, avoiding a second,
    redundant column-keying scheme.
    """

    row_reference: RowReference
    is_anchor: bool
    is_affected_by_finding: bool
    values: tuple[str | None, ...]


@dataclass(frozen=True, slots=True)
class RowContextWindow:
    """A bounded physical-neighborhood window around one finding's anchor
    row (`docs/domain-model.md` §13, `docs/api-specification.md` §10).

    Invariants enforce every documented property: exactly one anchor row,
    contiguous physical row numbers, requested-vs-actual window sizes
    correctly bounded and reflected in the truncation flags, and every
    row's `values` matching `columns` in length.
    """

    columns: tuple[ColumnReference, ...]
    requested_before: int
    requested_after: int
    actual_before: int
    actual_after: int
    truncated_at_start: bool
    truncated_at_end: bool
    max_window: int
    rows: tuple[RowContextEntry, ...]

    def __post_init__(self) -> None:
        if self.requested_before < 0:
            raise ValueError("RowContextWindow.requested_before must not be negative")
        if self.requested_after < 0:
            raise ValueError("RowContextWindow.requested_after must not be negative")
        if self.actual_before < 0:
            raise ValueError("RowContextWindow.actual_before must not be negative")
        if self.actual_after < 0:
            raise ValueError("RowContextWindow.actual_after must not be negative")
        if self.max_window < 0:
            raise ValueError("RowContextWindow.max_window must not be negative")
        if self.actual_before > self.requested_before:
            raise ValueError("RowContextWindow.actual_before must not exceed requested_before")
        if self.actual_after > self.requested_after:
            raise ValueError("RowContextWindow.actual_after must not exceed requested_after")
        if self.actual_before > self.max_window:
            raise ValueError("RowContextWindow.actual_before must not exceed max_window")
        if self.actual_after > self.max_window:
            raise ValueError("RowContextWindow.actual_after must not exceed max_window")
        if self.truncated_at_start != (self.actual_before < self.requested_before):
            raise ValueError(
                "RowContextWindow.truncated_at_start must equal (actual_before < requested_before)"
            )
        if self.truncated_at_end != (self.actual_after < self.requested_after):
            raise ValueError(
                "RowContextWindow.truncated_at_end must equal (actual_after < requested_after)"
            )

        if not self.rows:
            raise ValueError("RowContextWindow.rows must not be empty")
        expected_row_count = self.actual_before + self.actual_after + 1
        if len(self.rows) != expected_row_count:
            raise ValueError(
                "RowContextWindow.rows length must equal actual_before + actual_after + 1"
            )

        anchor_count = sum(1 for entry in self.rows if entry.is_anchor)
        if anchor_count != 1:
            raise ValueError("RowContextWindow.rows must contain exactly one anchor row")

        row_numbers = [entry.row_reference.row_number for entry in self.rows]
        for previous, current in zip(row_numbers, row_numbers[1:], strict=False):
            if current != previous + 1:
                raise ValueError("RowContextWindow.rows must be contiguous physical row numbers")

        for entry in self.rows:
            if len(entry.values) != len(self.columns):
                raise ValueError(
                    "RowContextEntry.values length must match RowContextWindow.columns length"
                )
