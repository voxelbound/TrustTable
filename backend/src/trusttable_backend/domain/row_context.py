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
    #: True when the window was clipped by the response-size bound (`UX-06`,
    #: D-073) rather than by the file's own start or end or the row limit; the
    #: truncation flags still report the shortfall, this says why it is not
    #: recoverable by asking for more rows.
    size_limited: bool = False

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


#: Closed set of scopes a `ScopedRowWindow` can have (`UX-06` part b, D-074).
SCOPE_OBSERVATION = "observation"
SCOPE_COLUMN_WIDE_FINDING = "column_wide_finding"

#: Closed set of anchor sources. The anchor is always chosen by the server from
#: data the analysis already records; a client can only pick among
#: `anchor_rows`.
ANCHOR_OBSERVATION_EXAMPLE = "observation_example"
ANCHOR_START_OF_FILE = "start_of_file"

_SCOPE_KINDS = frozenset({SCOPE_OBSERVATION, SCOPE_COLUMN_WIDE_FINDING})
_ANCHOR_SOURCES = frozenset({ANCHOR_OBSERVATION_EXAMPLE, ANCHOR_START_OF_FILE})


@dataclass(frozen=True, slots=True)
class ScopedRowWindow:
    """A `RowContextWindow` reached from an observation or from a column-wide
    finding rather than from a finding's own affected rows (`UX-06` part b,
    D-074).

    `anchor_rows` is the complete set of rows a reader may centre the window
    on, chosen by the server: an observation's own example rows, the example
    rows of observations about the same columns as a column-wide finding, or
    only row 0 when none exist (`start_of_file`). Inside `window`,
    `is_affected_by_finding` means "is one of `anchor_rows`" and is never true
    for a start-of-file window's rows: the start of a file is not evidence of
    a column-wide finding and is never marked as if it were.
    """

    window: RowContextWindow
    scope_kind: str
    anchor_source: str
    anchor_rows: tuple[int, ...]

    def __post_init__(self) -> None:
        if self.scope_kind not in _SCOPE_KINDS:
            raise ValueError("ScopedRowWindow.scope_kind is not a known scope")
        if self.anchor_source not in _ANCHOR_SOURCES:
            raise ValueError("ScopedRowWindow.anchor_source is not a known source")
        if not self.anchor_rows:
            raise ValueError("ScopedRowWindow.anchor_rows must not be empty")
        if list(self.anchor_rows) != sorted(set(self.anchor_rows)):
            raise ValueError("ScopedRowWindow.anchor_rows must be ascending and unique")
        anchor = next(entry for entry in self.window.rows if entry.is_anchor)
        if anchor.row_reference.row_number not in self.anchor_rows:
            raise ValueError("ScopedRowWindow's anchor must be one of anchor_rows")
        if self.anchor_source == ANCHOR_START_OF_FILE:
            if self.anchor_rows != (0,):
                raise ValueError("A start-of-file window can only be anchored on row 0")
            if any(entry.is_affected_by_finding for entry in self.window.rows):
                raise ValueError("A start-of-file window must not mark any row")
