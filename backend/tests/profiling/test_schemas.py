"""Tests for the profiling schemas (PROF-01).

Covers this package's acceptance criteria AC-03..AC-11:
`InferredColumnType`'s closed enumeration, `ProfilingWarning`/
`ProfilingTiming`/`ColumnProfile` positive/negative/boundary cases, and
`DatasetProfile`'s cross-field aggregate invariants (unique column
references, null/distinct counts bounded by the sampled row count, and
the all-null-column boundary case).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from trusttable_backend.domain.parsing import SampleMetadata, SamplingScope
from trusttable_backend.domain.value_objects import ColumnReference
from trusttable_backend.profiling.schemas import (
    ColumnProfile,
    DatasetProfile,
    InferredColumnType,
    ProfilingTiming,
    ProfilingWarning,
)

STARTED_AT = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# AC-03: InferredColumnType
# ---------------------------------------------------------------------------


def test_inferred_column_type_is_a_closed_enumeration() -> None:
    assert {member.value for member in InferredColumnType} == {
        "identifier",
        "numeric",
        "date",
        "categorical",
        "text",
        "boolean",
        "mixed",
        "unknown",
    }


# ---------------------------------------------------------------------------
# AC-04: ProfilingWarning
# ---------------------------------------------------------------------------


def test_profiling_warning_constructs_with_required_fields_only() -> None:
    warning = ProfilingWarning(code="profiling.high_null_ratio", message="90% null")

    assert warning.code == "profiling.high_null_ratio"
    assert warning.column is None


def test_profiling_warning_constructs_with_optional_column() -> None:
    column = ColumnReference(original_name="Qty", internal_key="qty", ordinal=0)
    warning = ProfilingWarning(code="profiling.high_null_ratio", message="90% null", column=column)

    assert warning.column == column


def test_profiling_warning_rejects_empty_message() -> None:
    with pytest.raises(ValueError, match="message"):
        ProfilingWarning(code="profiling.high_null_ratio", message="")


def test_profiling_warning_rejects_non_namespaced_code() -> None:
    with pytest.raises(ValueError, match="namespaced"):
        ProfilingWarning(code="high_null_ratio", message="90% null")


# ---------------------------------------------------------------------------
# AC-05: ProfilingTiming
# ---------------------------------------------------------------------------


def test_profiling_timing_constructs_with_valid_fields() -> None:
    timing = ProfilingTiming(started_at=STARTED_AT, completed_at=STARTED_AT, duration_ms=0)
    assert timing.duration_ms == 0


def test_profiling_timing_rejects_completed_before_started() -> None:
    earlier = datetime(2026, 8, 27, 11, 0, tzinfo=UTC)
    with pytest.raises(ValueError, match="completed_at"):
        ProfilingTiming(started_at=STARTED_AT, completed_at=earlier, duration_ms=0)


def test_profiling_timing_rejects_negative_duration() -> None:
    with pytest.raises(ValueError, match="duration_ms"):
        ProfilingTiming(started_at=STARTED_AT, completed_at=STARTED_AT, duration_ms=-1)


# ---------------------------------------------------------------------------
# AC-06: ColumnProfile
# ---------------------------------------------------------------------------


def make_column_profile(**overrides: object) -> ColumnProfile:
    fields: dict[str, object] = {
        "column": ColumnReference(original_name="Qty", internal_key="qty", ordinal=0),
        "inferred_type": InferredColumnType.NUMERIC,
        "null_count": 0,
        "distinct_count": 5,
        "metrics": {"mean": 3.2},
        "warnings": (),
    }
    fields.update(overrides)
    return ColumnProfile(**fields)  # type: ignore[arg-type]


def test_column_profile_constructs_with_valid_fields() -> None:
    profile = make_column_profile()

    assert profile.inferred_type is InferredColumnType.NUMERIC
    assert profile.metrics == {"mean": 3.2}


def test_column_profile_is_immutable() -> None:
    profile = make_column_profile()

    with pytest.raises(AttributeError):
        profile.null_count = 1  # type: ignore[misc]


def test_column_profile_rejects_negative_null_count() -> None:
    with pytest.raises(ValueError, match="null_count"):
        make_column_profile(null_count=-1)


def test_column_profile_rejects_negative_distinct_count() -> None:
    with pytest.raises(ValueError, match="distinct_count"):
        make_column_profile(distinct_count=-1)


def test_column_profile_accepts_zero_counts_boundary() -> None:
    profile = make_column_profile(null_count=0, distinct_count=0)
    assert profile.null_count == 0
    assert profile.distinct_count == 0


# ---------------------------------------------------------------------------
# AC-07: DatasetProfile
# ---------------------------------------------------------------------------


def make_full_sampling(population_size: int) -> SampleMetadata:
    return SampleMetadata(
        scope=SamplingScope.FULL, population_size=population_size, sample_size=population_size
    )


def make_timing() -> ProfilingTiming:
    return ProfilingTiming(started_at=STARTED_AT, completed_at=STARTED_AT, duration_ms=10)


def make_dataset_profile(**overrides: object) -> DatasetProfile:
    fields: dict[str, object] = {
        "schema_version": "1",
        "dataset_metrics": {"row_count": 10},
        "column_profiles": (make_column_profile(null_count=0, distinct_count=5),),
        "sampling": make_full_sampling(10),
        "warnings": (),
        "timing": make_timing(),
    }
    fields.update(overrides)
    return DatasetProfile(**fields)  # type: ignore[arg-type]


def test_dataset_profile_constructs_with_valid_fields() -> None:
    profile = make_dataset_profile()

    assert profile.schema_version == "1"
    assert len(profile.column_profiles) == 1


def test_dataset_profile_is_immutable() -> None:
    profile = make_dataset_profile()

    with pytest.raises(AttributeError):
        profile.schema_version = "2"  # type: ignore[misc]


def test_dataset_profile_rejects_empty_schema_version() -> None:
    with pytest.raises(ValueError, match="schema_version"):
        make_dataset_profile(schema_version="")


# ---------------------------------------------------------------------------
# AC-08: unique column references
# ---------------------------------------------------------------------------


def test_dataset_profile_rejects_duplicate_internal_key() -> None:
    columns = (
        make_column_profile(
            column=ColumnReference(original_name="Qty", internal_key="qty", ordinal=0),
        ),
        make_column_profile(
            column=ColumnReference(original_name="Qty 2", internal_key="qty", ordinal=1),
        ),
    )
    with pytest.raises(ValueError, match="internal_key"):
        make_dataset_profile(column_profiles=columns, sampling=make_full_sampling(5))


def test_dataset_profile_rejects_duplicate_ordinal() -> None:
    columns = (
        make_column_profile(
            column=ColumnReference(original_name="Qty", internal_key="qty", ordinal=0),
        ),
        make_column_profile(
            column=ColumnReference(original_name="Price", internal_key="price", ordinal=0),
        ),
    )
    with pytest.raises(ValueError, match="ordinal"):
        make_dataset_profile(column_profiles=columns, sampling=make_full_sampling(5))


# ---------------------------------------------------------------------------
# AC-09: null/distinct counts bounded by sampled row count
# ---------------------------------------------------------------------------


def test_dataset_profile_rejects_null_count_exceeding_sample_size() -> None:
    columns = (make_column_profile(null_count=11, distinct_count=0),)
    with pytest.raises(ValueError, match="null_count"):
        make_dataset_profile(column_profiles=columns, sampling=make_full_sampling(10))


def test_dataset_profile_rejects_distinct_count_exceeding_sample_size() -> None:
    columns = (make_column_profile(null_count=0, distinct_count=11),)
    with pytest.raises(ValueError, match="distinct_count"):
        make_dataset_profile(column_profiles=columns, sampling=make_full_sampling(10))


# ---------------------------------------------------------------------------
# AC-10: all-null column profile remains valid
# ---------------------------------------------------------------------------


def test_dataset_profile_accepts_all_null_column_profile() -> None:
    columns = (make_column_profile(null_count=10, distinct_count=0),)
    profile = make_dataset_profile(column_profiles=columns, sampling=make_full_sampling(10))
    assert profile.column_profiles[0].null_count == 10


# ---------------------------------------------------------------------------
# AC-11: reuse of ING-01's SampleMetadata/SamplingScope
# ---------------------------------------------------------------------------


def test_dataset_profile_sampling_is_ing01_sample_metadata() -> None:
    profile = make_dataset_profile()
    assert isinstance(profile.sampling, SampleMetadata)
    assert profile.sampling.scope is SamplingScope.FULL
