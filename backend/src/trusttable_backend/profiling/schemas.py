"""Profiling schemas (`PROF-01`): versioned dataset and column profile
contracts, matching `docs/domain-model.md` §7 (`DatasetProfile`) and the
"column profiles" concept implied by §7's field list and
`docs/detector-framework.md` §5's "relevant column profiles" input.

Framework-independent: no FastAPI/SQLAlchemy/pydantic import, no
computation. `PROF-02` (type inference) and `PROF-03` (core profiling)
populate real inferred types and metrics; this module only defines the
shapes.

`sampling` reuses `domain.parsing.SampleMetadata`/`SamplingScope`
directly rather than inventing a duplicate "calculation scope: full or
sampled" / "sampling method" concept. `dataset_metrics` and
`ColumnProfile.metrics` are intentionally open (`Mapping[str, object]`) —
`PROF-03`'s backlog item is explicitly the package that calculates and
names the actual metric keys.

Stdlib only (`dataclasses`, `datetime`, `enum`, `collections.abc.Mapping`).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from ..domain.parsing import SampleMetadata
from ..domain.value_objects import ColumnReference


class InferredColumnType(StrEnum):
    """Closed set of high-level inferred column types.

    Not a literal `docs/domain-model.md` list (none exists yet) — drawn
    from `PROF-02`'s own backlog wording ("identifiers, dates, mixed
    types, and ambiguous columns") plus the standard categories `PROF-03`
    names ("numeric, text, categorical, and date"), plus `boolean` and
    `unknown` as natural closures. `PROF-02` may extend this enum
    additively if real-world columns need finer distinctions.
    """

    IDENTIFIER = "identifier"
    NUMERIC = "numeric"
    DATE = "date"
    CATEGORICAL = "categorical"
    TEXT = "text"
    BOOLEAN = "boolean"
    MIXED = "mixed"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ProfilingWarning:
    """A non-fatal condition observed while profiling.

    Mirrors `domain.parsing.ParsingWarning`'s exact shape (namespaced
    `code`, `message`, optional column reference) in a distinct,
    profiling-specific type — parsing warnings and profiling warnings are
    semantically different lifecycle events, so they are kept as separate
    types rather than a single shared one.
    """

    code: str
    message: str
    column: ColumnReference | None = None

    def __post_init__(self) -> None:
        if not self.message:
            raise ValueError("ProfilingWarning.message must not be empty")
        if "." not in self.code:
            raise ValueError("ProfilingWarning.code must be namespaced (contain '.')")


@dataclass(frozen=True, slots=True)
class ProfilingTiming:
    """Timing metadata for one profiling run (`docs/domain-model.md` §7
    "timing metadata"). Not a literally-specified shape — a new, minimal
    type, consistent with `ING-01`'s `WorksheetMetadata`/`SampleMetadata`
    precedent for undocumented-but-implied types.
    """

    started_at: datetime
    completed_at: datetime
    duration_ms: int

    def __post_init__(self) -> None:
        if self.completed_at < self.started_at:
            raise ValueError("ProfilingTiming.completed_at must not precede started_at")
        if self.duration_ms < 0:
            raise ValueError("ProfilingTiming.duration_ms must not be negative")


@dataclass(frozen=True, slots=True)
class ColumnProfile:
    """Deterministic per-column profiling facts.

    A new type (no `docs/domain-model.md` section is literally titled
    "ColumnProfile") modeled from §7's "column profiles" field and
    `docs/detector-framework.md` §5's "relevant column profiles" input,
    kept intentionally minimal so `PROF-02`/`PROF-03` can extend it
    additively.
    """

    column: ColumnReference
    inferred_type: InferredColumnType
    null_count: int
    distinct_count: int
    metrics: Mapping[str, object]
    warnings: tuple[ProfilingWarning, ...] = ()

    def __post_init__(self) -> None:
        if self.null_count < 0:
            raise ValueError("ColumnProfile.null_count must not be negative")
        if self.distinct_count < 0:
            raise ValueError("ColumnProfile.distinct_count must not be negative")


@dataclass(frozen=True, slots=True)
class DatasetProfile:
    """Deterministic statistical and structural facts about a dataset
    (`docs/domain-model.md` §7). Fields follow §7's exact field list,
    reusing `domain.parsing.SampleMetadata` for "calculation scope: full
    or sampled" + "sampling method" together.
    """

    schema_version: str
    dataset_metrics: Mapping[str, object]
    column_profiles: tuple[ColumnProfile, ...]
    sampling: SampleMetadata
    warnings: tuple[ProfilingWarning, ...]
    timing: ProfilingTiming

    def __post_init__(self) -> None:
        if not self.schema_version:
            raise ValueError("DatasetProfile.schema_version must not be empty")

        internal_keys = [profile.column.internal_key for profile in self.column_profiles]
        if len(internal_keys) != len(set(internal_keys)):
            raise ValueError("DatasetProfile.column_profiles must have unique internal_key values")

        ordinals = [profile.column.ordinal for profile in self.column_profiles]
        if len(ordinals) != len(set(ordinals)):
            raise ValueError("DatasetProfile.column_profiles must have unique ordinal values")

        for profile in self.column_profiles:
            if profile.null_count > self.sampling.sample_size:
                raise ValueError(
                    "DatasetProfile.column_profiles entries must not have null_count "
                    "exceeding sampling.sample_size"
                )
            if profile.distinct_count > self.sampling.sample_size:
                raise ValueError(
                    "DatasetProfile.column_profiles entries must not have distinct_count "
                    "exceeding sampling.sample_size"
                )
