"""Shared framework-independent value objects (ING-01).

Implements the two `docs/domain-model.md` §3 "Shared value objects" needed
by this package's parsing contracts: `ColumnReference` and `RowReference`.
The remaining §3 value objects (`AnalysisId`, `EvidenceId`, `DetectorId`,
`Provenance`, `Severity`, `Confidence`) are deferred to the packages that
actually consume them (Analysis, Evidence/Finding, Context) — a disclosed
scoping decision, not a gap.

Stdlib only (`dataclasses`) — no FastAPI/SQLAlchemy/pydantic import.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ColumnReference:
    """Identifies a source column (`docs/domain-model.md` §3).

    Fields:
        original_name: the column's original, as-uploaded name. Preserved
            for display and never overwritten or normalized in place.
        internal_key: normalized internal key. Uniqueness within a parsed
            dataset is enforced by `ParsedDataset`, not by this type alone.
        ordinal: zero-based position of the column among the dataset's
            columns.
    """

    original_name: str
    internal_key: str
    ordinal: int

    def __post_init__(self) -> None:
        if not self.original_name:
            raise ValueError("ColumnReference.original_name must not be empty")
        if not self.internal_key:
            raise ValueError("ColumnReference.internal_key must not be empty")
        if self.ordinal < 0:
            raise ValueError("ColumnReference.ordinal must not be negative")


@dataclass(frozen=True, slots=True)
class RowReference:
    """Identifies an affected source row without embedding the row itself
    (`docs/domain-model.md` §3).

    Fields:
        row_number: stable internal row number (zero-based), matching the
            row's position within `ParsedDataset.row_references`.
        source_line_number: optional original file line number, when it
            can be determined (e.g. CSV) and may differ from `row_number`
            (e.g. because of blank or header lines).
        fingerprint: optional deterministic row fingerprint (e.g. a content
            hash), usable to detect whether the underlying row changed.
    """

    row_number: int
    source_line_number: int | None = None
    fingerprint: str | None = None

    def __post_init__(self) -> None:
        if self.row_number < 0:
            raise ValueError("RowReference.row_number must not be negative")
