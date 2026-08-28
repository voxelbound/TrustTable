"""Type inference (`PROF-02`): classifies each column of an already-parsed
dataset into one of `PROF-01`'s `InferredColumnType` values.

Bridges `ING-02` (raw parsed rows, a plain `tuple[tuple[str | None, ...],
...]`) and `PROF-01` (`ColumnProfile`/`InferredColumnType`). No metric
calculation — `ColumnProfile.metrics` is always `{}` from this module;
`PROF-03` (core profiling) is the package that calculates and populates
real metrics.

The classification precedence, token set, and thresholds below are a new,
disclosed, reversible design (see the work package's Provenance) — no
authoritative document fixes a type-inference algorithm; the backlog
names the categories to handle ("identifiers, dates, mixed types, and
ambiguous columns"), not the method.

`IDENTIFIER`/`CATEGORICAL` are deliberately cheap, coarse, disclosed
signals, not confident semantic verdicts (`docs/domain-model.md` §8
`DatasetContext.candidate_keys` is the later, confidence-scored,
confirmable/correctable layer that makes the real "is this the dataset's
key column" judgment). A large, fully-unique free-form text column will
also classify `IDENTIFIER` here — an accepted, tested limitation, not a
defect: `docs/product-requirements.md` §10 names `likely identifier`/
`high cardinality` as `PROF-03` `Text:` metrics, which must be computed
for `IDENTIFIER`/`CATEGORICAL` columns too (not gated to `TEXT` alone) so
this layer's coarse label remains correctable downstream.

Framework-independent: no FastAPI/SQLAlchemy/pydantic import. Stdlib only
(`datetime`, `re`).
"""

from __future__ import annotations

import re
from datetime import date
from typing import Final

from ..domain.value_objects import ColumnReference
from .schemas import ColumnProfile, InferredColumnType, ProfilingWarning

_BOOLEAN_TOKENS: Final[frozenset[str]] = frozenset({"true", "false", "yes", "no"})
_ISO_DATE_PATTERN: Final[re.Pattern[str]] = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_CATEGORICAL_DISTINCT_RATIO: Final[float] = 0.5
"""A column classifies as `CATEGORICAL` when at most this fraction of its
non-blank values are distinct — i.e. each distinct value recurs, on
average, at least once more. A scale-invariant ratio (not an absolute
count), chosen as the natural majority/repeat-dominance point rather than
fit to any particular dataset: it behaves identically at 10 rows or
10,000,000 rows, unlike an absolute cap."""

_IDENTIFIER_MIN_VALUES: Final[int] = 2
"""A column needs at least this many non-blank values to be classified as
`IDENTIFIER` — a single value proves nothing about uniqueness."""


def infer_column_types(
    columns: tuple[ColumnReference, ...],
    rows: tuple[tuple[str | None, ...], ...],
) -> tuple[ColumnProfile, ...]:
    """Classify every column, returning one `ColumnProfile` per column in
    the same order as `columns`.

    `rows` is expected to be `ING-02`'s `CsvParseResult.rows` shape: one
    tuple per row, one `str | None` per column, in header/ordinal order.
    """
    return tuple(
        _infer_column_profile(column, tuple(row[column.ordinal] for row in rows))
        for column in columns
    )


def _is_boolean_token(value: str) -> bool:
    return value.strip().lower() in _BOOLEAN_TOKENS


def _is_iso_date(value: str) -> bool:
    stripped = value.strip()
    if not _ISO_DATE_PATTERN.match(stripped):
        return False
    try:
        date.fromisoformat(stripped)
    except ValueError:
        return False
    return True


def _is_numeric(value: str) -> bool:
    try:
        float(value.strip())
    except ValueError:
        return False
    return True


def _infer_column_profile(column: ColumnReference, values: tuple[str | None, ...]) -> ColumnProfile:
    non_blank = [value for value in values if value is not None and value != ""]
    null_count = len(values) - len(non_blank)
    distinct_count = len(set(non_blank))

    inferred_type, warnings = _classify(non_blank, distinct_count, column)

    return ColumnProfile(
        column=column,
        inferred_type=inferred_type,
        null_count=null_count,
        distinct_count=distinct_count,
        metrics={},
        warnings=warnings,
    )


def _classify(
    non_blank: list[str], distinct_count: int, column: ColumnReference
) -> tuple[InferredColumnType, tuple[ProfilingWarning, ...]]:
    total = len(non_blank)
    if total == 0:
        return InferredColumnType.UNKNOWN, ()

    boolean_matches = sum(1 for value in non_blank if _is_boolean_token(value))
    date_matches = sum(1 for value in non_blank if _is_iso_date(value))
    numeric_matches = sum(1 for value in non_blank if _is_numeric(value))

    if boolean_matches == total:
        return InferredColumnType.BOOLEAN, ()
    if date_matches == total:
        return InferredColumnType.DATE, ()
    if numeric_matches == total:
        return InferredColumnType.NUMERIC, ()

    if boolean_matches > 0 or date_matches > 0 or numeric_matches > 0:
        warning = ProfilingWarning(
            code="profiling.mixed_column_type",
            message=(
                f"Column has a mix of value shapes: {boolean_matches} boolean-like, "
                f"{date_matches} date-like, {numeric_matches} numeric-like, out of "
                f"{total} non-blank values"
            ),
            column=column,
        )
        return InferredColumnType.MIXED, (warning,)

    if total >= _IDENTIFIER_MIN_VALUES and distinct_count == total:
        return InferredColumnType.IDENTIFIER, ()

    if (distinct_count / total) <= _CATEGORICAL_DISTINCT_RATIO:
        return InferredColumnType.CATEGORICAL, ()

    return InferredColumnType.TEXT, ()
