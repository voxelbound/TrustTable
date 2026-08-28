"""Core profiling (`PROF-03`): calculates the deterministic dataset- and
column-level metrics named in `docs/product-requirements.md` §10,
populating `PROF-01`'s `DatasetProfile.dataset_metrics` and
`ColumnProfile.metrics` for the first time.

Calls `PROF-02`'s `infer_column_types` unchanged for classification —
this module never alters `inferred_type`/`null_count`/`distinct_count`/
per-column warnings, it only adds metrics on top.

Metric families (all disclosed, reversible design choices — no document
fixes exact algorithms or thresholds beyond §10's metric names; see the
work package's Provenance for the full rationale):

- Common (every column, regardless of type): ``source_type``,
  ``uniqueness_ratio``, ``representative_values``.
- Numeric (``NUMERIC`` only): min/max/mean/median/stdev, quartiles, IQR,
  median absolute deviation, zero/negative counts, a Tukey-fence extreme
  count.
- Date (``DATE`` only): min/max, invalid-parse count (always 0 — PROF-02
  requires 100% ISO match to classify DATE at all), a future-date count
  against an explicit ``as_of`` parameter, and the largest gap in days
  between consecutive distinct dates.
- Text-family (``TEXT``, ``CATEGORICAL``, and ``IDENTIFIER`` — per
  PROF-02 r3's forward-compatibility requirement, not ``TEXT`` alone):
  length bounds, whitespace-issue count, empty-string count, normalized
  distinct count, ``high_cardinality``/``likely_identifier`` flags
  (computed independently of ``inferred_type``), and a bounded, coarse
  ``instruction_like_value_count`` — explicitly NOT the
  `security.possible_llm_prompt_injection` detector (`DET-SEC-01`); no
  evidence object, severity, or finding is produced here.
- Dataset-level: row/column count, a coarse content-byte
  ``memory_estimate_bytes`` proxy, duplicate-row count, empty-row count,
  empty-column count.

Framework-independent: no FastAPI/SQLAlchemy/pydantic import. Stdlib only
(`statistics`, `datetime`, `re`, `collections.abc`).
"""

from __future__ import annotations

import re
import statistics
from collections import Counter
from dataclasses import replace
from datetime import UTC, date, datetime
from typing import Final

from ..domain.parsing import SampleMetadata
from ..domain.value_objects import ColumnReference
from .schemas import ColumnProfile, DatasetProfile, InferredColumnType, ProfilingTiming
from .type_inference import infer_column_types

_REPRESENTATIVE_VALUES_LIMIT: Final[int] = 5
"""Common metric: at most this many `(value, count)` pairs are recorded,
in descending-count, first-seen-order tie-break order."""

_HIGH_CARDINALITY_RATIO: Final[float] = 0.9
"""A text-family column is flagged `high_cardinality` when at least this
fraction of its non-blank values are distinct."""

_LIKELY_IDENTIFIER_RATIO: Final[float] = 0.98
"""A text-family column is flagged `likely_identifier` when at least this
fraction of its non-blank values are distinct — independent of PROF-02's
coarse `inferred_type`, per WP-010's forward-compatibility requirement."""

_LIKELY_IDENTIFIER_MIN_VALUES: Final[int] = 2
"""`likely_identifier` requires at least this many non-blank values —
mirrors PROF-02's `_IDENTIFIER_MIN_VALUES` reasoning: a single value
proves nothing about uniqueness."""

_EXTREME_FENCE_MULTIPLIER: Final[float] = 1.5
"""Standard Tukey outlier fence: values outside
`[q1 - k * iqr, q3 + k * iqr]` count as `extreme_count`."""

_TEXT_FAMILY_TYPES: Final[frozenset[InferredColumnType]] = frozenset(
    {
        InferredColumnType.TEXT,
        InferredColumnType.CATEGORICAL,
        InferredColumnType.IDENTIFIER,
    }
)

_INSTRUCTION_LIKE_PATTERN: Final[re.Pattern[str]] = re.compile(
    r"\b(ignore|disregard)\s+(all\s+)?(previous|prior)\s+instructions\b"
    r"|\byou\s+are\s+now\b"
    r"|\bnew\s+instructions\s*:",
    re.IGNORECASE,
)
"""A small, bounded, literal set of imperative override phrases. A coarse
profiling-level indicator only — not the `security.possible_llm_prompt_injection`
detector (`DET-SEC-01`), which owns evidence/severity/exposure semantics."""


def compute_dataset_profile(
    columns: tuple[ColumnReference, ...],
    rows: tuple[tuple[str | None, ...], ...],
    sampling: SampleMetadata,
    *,
    as_of: date | None = None,
) -> DatasetProfile:
    """Compute a complete, invariant-valid `DatasetProfile` for `rows`.

    `as_of` is the reference date for the `future_date_count` date metric;
    defaults to `date.today()` when not supplied (the only wall-clock
    read in this module — tests should always pass an explicit value for
    determinism).
    """
    started_at = datetime.now(UTC)
    reference_date = as_of if as_of is not None else date.today()

    base_profiles = infer_column_types(columns, rows)
    column_profiles = tuple(
        replace(profile, metrics=_column_metrics(profile, columns, rows, reference_date))
        for profile in base_profiles
    )

    dataset_metrics = _dataset_metrics(columns, rows, column_profiles)

    completed_at = datetime.now(UTC)
    timing = ProfilingTiming(
        started_at=started_at,
        completed_at=completed_at,
        duration_ms=max(0, int((completed_at - started_at).total_seconds() * 1000)),
    )

    return DatasetProfile(
        schema_version="1",
        dataset_metrics=dataset_metrics,
        column_profiles=column_profiles,
        sampling=sampling,
        warnings=(),
        timing=timing,
    )


def _column_values(
    column: ColumnReference, rows: tuple[tuple[str | None, ...], ...]
) -> tuple[str, ...]:
    values: list[str] = []
    for row in rows:
        value = row[column.ordinal]
        if value is not None and value != "":
            values.append(value)
    return tuple(values)


def _column_metrics(
    profile: ColumnProfile,
    columns: tuple[ColumnReference, ...],
    rows: tuple[tuple[str | None, ...], ...],
    as_of: date,
) -> dict[str, object]:
    non_blank = _column_values(profile.column, rows)
    metrics: dict[str, object] = dict(_common_metrics(non_blank))

    if profile.inferred_type is InferredColumnType.NUMERIC:
        metrics.update(_numeric_metrics(non_blank))
    elif profile.inferred_type is InferredColumnType.DATE:
        metrics.update(_date_metrics(non_blank, as_of))
    elif profile.inferred_type in _TEXT_FAMILY_TYPES:
        metrics.update(_text_metrics(non_blank))

    return metrics


def _common_metrics(non_blank: tuple[str, ...]) -> dict[str, object]:
    non_null_count = len(non_blank)
    distinct_count = len(set(non_blank))
    uniqueness_ratio = (distinct_count / non_null_count) if non_null_count else 0.0
    return {
        "source_type": "string",
        "uniqueness_ratio": uniqueness_ratio,
        "representative_values": _representative_values(non_blank),
    }


def _representative_values(non_blank: tuple[str, ...]) -> tuple[tuple[str, int], ...]:
    if not non_blank:
        return ()
    first_seen: dict[str, int] = {}
    counts: Counter[str] = Counter()
    for index, value in enumerate(non_blank):
        counts[value] += 1
        first_seen.setdefault(value, index)
    ranked = sorted(counts.items(), key=lambda item: (-item[1], first_seen[item[0]]))
    return tuple(ranked[:_REPRESENTATIVE_VALUES_LIMIT])


def _numeric_metrics(non_blank: tuple[str, ...]) -> dict[str, object]:
    values = [float(value.strip()) for value in non_blank]
    minimum = min(values)
    maximum = max(values)
    mean = statistics.mean(values)
    median = statistics.median(values)
    stdev = statistics.stdev(values) if len(values) >= 2 else 0.0

    if len(values) >= 2:
        q1, _, q3 = statistics.quantiles(values, n=4, method="inclusive")
    else:
        q1 = q3 = values[0]
    iqr = q3 - q1
    mad = statistics.median([abs(value - median) for value in values])

    zero_count = sum(1 for value in values if value == 0.0)
    negative_count = sum(1 for value in values if value < 0.0)
    lower_fence = q1 - _EXTREME_FENCE_MULTIPLIER * iqr
    upper_fence = q3 + _EXTREME_FENCE_MULTIPLIER * iqr
    extreme_count = sum(1 for value in values if value < lower_fence or value > upper_fence)

    return {
        "min": minimum,
        "max": maximum,
        "mean": mean,
        "median": median,
        "stdev": stdev,
        "q1": q1,
        "q2": median,
        "q3": q3,
        "iqr": iqr,
        "mad": mad,
        "zero_count": zero_count,
        "negative_count": negative_count,
        "extreme_count": extreme_count,
    }


def _date_metrics(non_blank: tuple[str, ...], as_of: date) -> dict[str, object]:
    parsed = sorted({date.fromisoformat(value.strip()) for value in non_blank})
    minimum = min(parsed)
    maximum = max(parsed)
    future_date_count = sum(1 for value in non_blank if date.fromisoformat(value.strip()) > as_of)
    if len(parsed) >= 2:
        max_gap_days = max((parsed[i + 1] - parsed[i]).days for i in range(len(parsed) - 1))
    else:
        max_gap_days = 0

    return {
        "min": minimum.isoformat(),
        "max": maximum.isoformat(),
        "invalid_parse_count": 0,
        "future_date_count": future_date_count,
        "max_gap_days": max_gap_days,
    }


def _text_metrics(non_blank: tuple[str, ...]) -> dict[str, object]:
    total = len(non_blank)
    distinct_count = len(set(non_blank))
    lengths = [len(value) for value in non_blank]
    whitespace_issue_count = sum(1 for value in non_blank if value != value.strip())
    empty_string_count = sum(1 for value in non_blank if value.strip() == "" and value != "")
    normalized_distinct_count = len({value.strip().lower() for value in non_blank})

    ratio = (distinct_count / total) if total else 0.0
    high_cardinality = ratio >= _HIGH_CARDINALITY_RATIO
    likely_identifier = ratio >= _LIKELY_IDENTIFIER_RATIO and total >= _LIKELY_IDENTIFIER_MIN_VALUES

    instruction_like_value_count = sum(
        1 for value in non_blank if _INSTRUCTION_LIKE_PATTERN.search(value)
    )

    return {
        "min_length": min(lengths) if lengths else 0,
        "max_length": max(lengths) if lengths else 0,
        "whitespace_issue_count": whitespace_issue_count,
        "empty_string_count": empty_string_count,
        "normalized_distinct_count": normalized_distinct_count,
        "high_cardinality": high_cardinality,
        "likely_identifier": likely_identifier,
        "instruction_like_value_count": instruction_like_value_count,
    }


def _dataset_metrics(
    columns: tuple[ColumnReference, ...],
    rows: tuple[tuple[str | None, ...], ...],
    column_profiles: tuple[ColumnProfile, ...],
) -> dict[str, object]:
    row_count = len(rows)
    column_count = len(columns)

    memory_estimate_bytes = sum(
        len(value.encode("utf-8")) for row in rows for value in row if value is not None
    )

    distinct_row_count = len({row for row in rows})
    duplicate_row_count = row_count - distinct_row_count

    empty_row_count = sum(1 for row in rows if all(value is None or value == "" for value in row))

    empty_column_count = sum(
        1 for profile in column_profiles if profile.inferred_type is InferredColumnType.UNKNOWN
    )

    return {
        "row_count": row_count,
        "column_count": column_count,
        "memory_estimate_bytes": memory_estimate_bytes,
        "duplicate_row_count": duplicate_row_count,
        "empty_row_count": empty_row_count,
        "empty_column_count": empty_column_count,
    }
