"""Value-evidence producers (`DET-03` closure package 2,
`docs/decision-log.md` D-061).

Three detectors state what can be *seen* in the data as neutral
`Observation`s of the one kind `value_evidence`, never as findings:

- `structural.mixed_types`: a column whose non-blank values have more than one
  shape (boolean-like, ISO-date-like, numeric-like, other);
- `consistency.inconsistent_date_formats`: a column whose date-like values are
  written in more than one recognised format family;
- `completeness.concentrated_missingness`: a column whose missing values sit
  mostly in one unbroken run of consecutive rows.

None of them produces a `FindingCandidate`, so none can reach trust scoring,
finding priority, remediation guidance or rule generation; none says that a
pattern is wrong or what a column means. Evidence is counts, ratios, ordinals,
fixed labels and at most `MAX_OBSERVATION_ROW_REFERENCES` example row
references: no cell value is ever copied into an observation. A column name is
shown only in the display summary, truncated, as the existing detectors do.

Framework-independent per `docs/architecture.md` §3's "Detectors" layer rule;
`pydantic.BaseModel` is used only for `config_schema`.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from datetime import date
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

from ..domain.observation import MAX_OBSERVATION_ROW_REFERENCES, Observation, ObservationKind
from ..domain.parsing import SamplingScope
from ..domain.value_objects import ColumnReference, RowReference
from ..profiling.schemas import InferredColumnType
from ..profiling.type_inference import VALUE_SHAPES, classify_value_shape
from .contract import (
    DetectorCategory,
    DetectorMetadata,
    DetectorRunRequest,
    DetectorRunResult,
    DetectorRunStatus,
    DetectorSupportRequest,
    ExecutionMetrics,
    PerformanceClass,
)

#: The detectors in this module. Each states observations only and never
#: produces a `FindingCandidate`, so none has built-in guidance or a rule
#: proposal: guidance and rules are written for findings. Registry-wide tests use
#: this set to tell them apart from the finding-producing detectors.
OBSERVATION_ONLY_DETECTOR_IDS: Final[frozenset[str]] = frozenset(
    {
        "structural.mixed_types",
        "consistency.inconsistent_date_formats",
        "completeness.concentrated_missingness",
    }
)

_MAX_NAME_DISPLAY: Final[int] = 60
#: Values longer than this are never read as dates (bounds all matching work).
_MAX_DATE_VALUE_LENGTH: Final[int] = 40


class _EmptyConfig(BaseModel):
    """No configurable parameters."""


def _display_name(column: ColumnReference) -> str:
    return column.original_name[:_MAX_NAME_DISPLAY]


def _is_missing(value: object) -> bool:
    """`None` and `""` are missing, matching profiling's non-blank convention."""
    return value is None or value == ""


def _is_blank(value: object) -> bool:
    """No content at all: `None`, `""` or whitespace only."""
    return value is None or (isinstance(value, str) and not value.strip())


def _result(metadata: DetectorMetadata, observations: Sequence[Observation]) -> DetectorRunResult:
    return DetectorRunResult(
        detector_id=metadata.detector_id,
        detector_version=metadata.version,
        status=DetectorRunStatus.SUCCESS,
        findings=(),
        evidence=(),
        warnings=(),
        execution_metrics=ExecutionMetrics(duration_ms=0),
        observations=tuple(observations),
    )


# --------------------------------------------------------------------------- #
# structural.mixed_types
# --------------------------------------------------------------------------- #


class MixedTypesDetector:
    """`structural.mixed_types` — states, per column the profile classed as
    `MIXED`, how many non-blank values have each shape.

    Shapes come from the exact predicates and precedence type inference uses
    (`classify_value_shape`), so the observation always agrees with the
    profile. The dominant shape is the most frequent one (ties broken by the
    fixed shape order); the example rows are the first rows whose value has a
    different shape. The observation does not say which shape is correct.
    """

    metadata = DetectorMetadata(
        detector_id="structural.mixed_types",
        version="1",
        name="Mixed value types",
        category=DetectorCategory.STRUCTURAL,
        description=(
            "States how many values of a column have each shape when the column mixes "
            "boolean-like, date-like, numeric-like and other values."
        ),
        applicable_inferred_types=(InferredColumnType.MIXED,),
        required_profile_fields=("column_profiles[].inferred_type",),
        requires_raw_rows=True,
        requires_confirmed_context=False,
        default_configuration={},
        performance_class=PerformanceClass.LINEAR_BY_ROW,
        documented_limitations=(
            "An observation only: it does not say which shape is the intended one.",
            "Shapes are the profile's own coarse classes; ISO dates only, no other date format.",
            "At most 20 example rows are referenced; the counts are exact.",
        ),
    )
    config_schema: type[BaseModel] = _EmptyConfig

    def supports(self, request: DetectorSupportRequest) -> bool:
        del request  # Dataset-level, structurally always applicable.
        return True

    def run(self, request: DetectorRunRequest) -> DetectorRunResult:
        observations: list[Observation] = []
        for profile in request.dataset_profile.column_profiles:
            if profile.inferred_type is not InferredColumnType.MIXED:
                continue
            key = profile.column.internal_key
            counts = dict.fromkeys(VALUE_SHAPES, 0)
            shapes: list[tuple[int, str]] = []
            for index, row in enumerate(request.rows):
                value = row.get(key)
                if not isinstance(value, str) or value == "":
                    continue
                shape = classify_value_shape(value)
                counts[shape] += 1
                shapes.append((index, shape))
            present = [shape for shape in VALUE_SHAPES if counts[shape]]
            if len(present) < 2:
                continue
            dominant = max(
                VALUE_SHAPES,
                key=lambda shape: (counts[shape], -VALUE_SHAPES.index(shape)),
            )
            example_indices = [index for index, shape in shapes if shape != dominant][
                :MAX_OBSERVATION_ROW_REFERENCES
            ]
            non_blank = sum(counts.values())
            breakdown = ", ".join(f"{counts[shape]} {shape}-like" for shape in present)
            observations.append(
                Observation(
                    observation_id=f"structural.mixed_types.observation.{key}",
                    kind=ObservationKind.VALUE_EVIDENCE,
                    producer_detector_id=self.metadata.detector_id,
                    producer_version=self.metadata.version,
                    summary=(
                        f"Column '{_display_name(profile.column)}' has {non_blank} non-blank "
                        f"value(s) of more than one shape: {breakdown}."
                    ),
                    affected_columns=(profile.column,),
                    affected_row_references=tuple(
                        request.row_references[index] for index in example_indices
                    ),
                    scope=SamplingScope.FULL,
                    structured_payload={
                        "non_blank_count": non_blank,
                        "shape_counts": {shape: counts[shape] for shape in present},
                        "dominant_shape": dominant,
                    },
                )
            )
        return _result(self.metadata, observations)


# --------------------------------------------------------------------------- #
# consistency.inconsistent_date_formats
# --------------------------------------------------------------------------- #

_MONTH_FULL_NAMES: Final[tuple[str, ...]] = (
    "january",
    "february",
    "march",
    "april",
    "may",
    "june",
    "july",
    "august",
    "september",
    "october",
    "november",
    "december",
)

#: English month name or three-letter abbreviation (plus `sept`) to its number.
_MONTH_NUMBER: Final[dict[str, int]] = {
    **{name: number for number, name in enumerate(_MONTH_FULL_NAMES, start=1)},
    **{name[:3]: number for number, name in enumerate(_MONTH_FULL_NAMES, start=1)},
    "sept": 9,
}

_ISO = re.compile(r"(\d{4})-(\d{2})-(\d{2})")
_YEAR_FIRST_SLASH = re.compile(r"(\d{4})/(\d{1,2})/(\d{1,2})")
_NUMERIC_SLASH = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})")
_NUMERIC_DOT = re.compile(r"(\d{1,2})\.(\d{1,2})\.(\d{4})")
_NUMERIC_DASH = re.compile(r"(\d{1,2})-(\d{1,2})-(\d{4})")
_DAY_MONTH_NAME = re.compile(r"(\d{1,2}) ([A-Za-z]{3,9}) (\d{4})")
_MONTH_NAME_DAY = re.compile(r"([A-Za-z]{3,9}) (\d{1,2}),? (\d{4})")

#: The closed, ordered set of format family labels. Day-first versus
#: month-first is **not** decided for the numeric families.
DATE_FORMAT_FAMILIES: Final[tuple[str, ...]] = (
    "iso_year_month_day",
    "slash_year_first",
    "slash_numeric",
    "dot_numeric",
    "dash_numeric",
    "day_month_name_year",
    "month_name_day_year",
)


def _valid_ymd(year: int, month: int, day: int) -> bool:
    try:
        date(year, month, day)
    except ValueError:
        return False
    return True


def _valid_either_order(first: int, second: int, year: int) -> bool:
    """A numeric `a?b?year` value is date-like when it is a real date read
    either day-first or month-first."""
    return _valid_ymd(year, second, first) or _valid_ymd(year, first, second)


def date_format_family(value: str) -> str | None:
    """The recognised date format family of one value, or `None` when the
    value is not date-like. Anchored full matches only, no nested quantifiers
    (linear), and values over `_MAX_DATE_VALUE_LENGTH` are never matched."""
    text = value.strip()
    if not text or len(text) > _MAX_DATE_VALUE_LENGTH:
        return None
    if (m := _ISO.fullmatch(text)) is not None:
        return "iso_year_month_day" if _valid_ymd(*map(int, m.groups())) else None
    if (m := _YEAR_FIRST_SLASH.fullmatch(text)) is not None:
        return "slash_year_first" if _valid_ymd(*map(int, m.groups())) else None
    for pattern, family in (
        (_NUMERIC_SLASH, "slash_numeric"),
        (_NUMERIC_DOT, "dot_numeric"),
        (_NUMERIC_DASH, "dash_numeric"),
    ):
        if (m := pattern.fullmatch(text)) is not None:
            first, second, year = (int(part) for part in m.groups())
            return family if _valid_either_order(first, second, year) else None
    if (m := _DAY_MONTH_NAME.fullmatch(text)) is not None:
        day_text, name_text, year_text = m.groups()
        month = _MONTH_NUMBER.get(name_text.lower())
        if month is not None and _valid_ymd(int(year_text), month, int(day_text)):
            return "day_month_name_year"
        return None
    if (m := _MONTH_NAME_DAY.fullmatch(text)) is not None:
        name_text, day_text, year_text = m.groups()
        month = _MONTH_NUMBER.get(name_text.lower())
        if month is not None and _valid_ymd(int(year_text), month, int(day_text)):
            return "month_name_day_year"
        return None
    return None


class _DateFormatsConfig(BaseModel):
    """`minimum_date_like_ratio` is the share of a column's non-blank values
    that must be date-like before its formats are compared."""

    model_config = ConfigDict(extra="forbid")

    minimum_date_like_ratio: float = Field(default=0.5, gt=0.0, le=1.0, allow_inf_nan=False)


class InconsistentDateFormatsDetector:
    """`consistency.inconsistent_date_formats` — states, per column whose
    non-blank values are mostly date-like, the count of each recognised date
    format family when more than one is present.

    The families are a closed, documented set (`DATE_FORMAT_FAMILIES`); a
    numeric `a/b/yyyy`, `a.b.yyyy` or `a-b-yyyy` is date-like when it is a real
    date read day-first or month-first, and which of the two is **not**
    decided. English month names only. The example rows are the first
    date-like rows outside the dominant family. The observation does not say
    which format is correct.
    """

    metadata = DetectorMetadata(
        detector_id="consistency.inconsistent_date_formats",
        version="1",
        name="Inconsistent date formats",
        category=DetectorCategory.CONSISTENCY,
        description=(
            "States how many date-like values of a column are written in each recognised "
            "date format when more than one format is present."
        ),
        applicable_inferred_types=(),
        required_profile_fields=("column_profiles[].column",),
        requires_raw_rows=True,
        requires_confirmed_context=False,
        default_configuration={"minimum_date_like_ratio": 0.5},
        performance_class=PerformanceClass.LINEAR_BY_ROW,
        documented_limitations=(
            "An observation only: it does not say which format is the intended one.",
            "Day-first and month-first readings of a numeric date are not distinguished.",
            "A closed set of seven format families and English month names only.",
            "At most 20 example rows are referenced; the counts are exact.",
        ),
    )
    config_schema: type[BaseModel] = _DateFormatsConfig

    def supports(self, request: DetectorSupportRequest) -> bool:
        del request  # Dataset-level, structurally always applicable.
        return True

    def run(self, request: DetectorRunRequest) -> DetectorRunResult:
        threshold = float(request.configuration["minimum_date_like_ratio"])  # type: ignore[arg-type]
        observations: list[Observation] = []
        for profile in request.dataset_profile.column_profiles:
            key = profile.column.internal_key
            counts: dict[str, int] = {}
            families: list[tuple[int, str]] = []
            non_blank = 0
            for index, row in enumerate(request.rows):
                value = row.get(key)
                if not isinstance(value, str) or value == "":
                    continue
                non_blank += 1
                family = date_format_family(value)
                if family is None:
                    continue
                counts[family] = counts.get(family, 0) + 1
                families.append((index, family))
            date_like = len(families)
            if len(counts) < 2 or non_blank == 0 or date_like / non_blank < threshold:
                continue
            dominant = max(
                DATE_FORMAT_FAMILIES,
                key=lambda family: (counts.get(family, 0), -DATE_FORMAT_FAMILIES.index(family)),
            )
            example_indices = [index for index, family in families if family != dominant][
                :MAX_OBSERVATION_ROW_REFERENCES
            ]
            present = [family for family in DATE_FORMAT_FAMILIES if family in counts]
            breakdown = ", ".join(f"{counts[family]} {family}" for family in present)
            observations.append(
                Observation(
                    observation_id=f"consistency.inconsistent_date_formats.observation.{key}",
                    kind=ObservationKind.VALUE_EVIDENCE,
                    producer_detector_id=self.metadata.detector_id,
                    producer_version=self.metadata.version,
                    summary=(
                        f"Column '{_display_name(profile.column)}' has {date_like} date-like "
                        f"value(s) of {len(present)} different formats: {breakdown}."
                    ),
                    affected_columns=(profile.column,),
                    affected_row_references=tuple(
                        request.row_references[index] for index in example_indices
                    ),
                    scope=SamplingScope.FULL,
                    structured_payload={
                        "non_blank_count": non_blank,
                        "date_like_count": date_like,
                        "format_counts": {family: counts[family] for family in present},
                        "dominant_format": dominant,
                        "minimum_date_like_ratio": threshold,
                    },
                )
            )
        return _result(self.metadata, observations)


# --------------------------------------------------------------------------- #
# completeness.concentrated_missingness
# --------------------------------------------------------------------------- #


class _ConcentratedMissingnessConfig(BaseModel):
    """A column is reported when its longest unbroken run of missing rows is at
    least `minimum_run_length` long and holds at least `concentration_ratio` of
    its missing values."""

    model_config = ConfigDict(extra="forbid")

    minimum_run_length: int = Field(default=5, ge=2)
    concentration_ratio: float = Field(default=0.8, gt=0.0, le=1.0, allow_inf_nan=False)


class ConcentratedMissingnessDetector:
    """`completeness.concentrated_missingness` — states, per column, that most
    of its missing values sit in one unbroken run of consecutive rows.

    Rows that are blank in **every** column are left out of the comparison
    first (`completeness.fully_empty_rows` owns them), so trailing blank lines
    do not appear as a block in every column. A column with no value at all
    belongs to `structural.empty_column` and is skipped. The observation
    reports counts, the run's length and its first and last row numbers; it
    does not say why the values are missing.
    """

    metadata = DetectorMetadata(
        detector_id="completeness.concentrated_missingness",
        version="1",
        name="Concentrated missingness",
        category=DetectorCategory.COMPLETENESS,
        description=(
            "States that most of a column's missing values sit in one unbroken run of "
            "consecutive rows."
        ),
        applicable_inferred_types=(),
        required_profile_fields=("column_profiles[].column",),
        requires_raw_rows=True,
        requires_confirmed_context=False,
        default_configuration={"minimum_run_length": 5, "concentration_ratio": 0.8},
        performance_class=PerformanceClass.LINEAR_BY_ROW,
        documented_limitations=(
            "An observation only: it does not say why the values are missing.",
            "Only one unbroken run of consecutive rows is measured; scattered or periodic "
            "gaps are not reported.",
            "Rows blank in every column are excluded; empty columns are left to "
            "structural.empty_column.",
            "At most 20 example rows are referenced; the counts are exact.",
        ),
    )
    config_schema: type[BaseModel] = _ConcentratedMissingnessConfig

    def supports(self, request: DetectorSupportRequest) -> bool:
        del request  # Dataset-level, structurally always applicable.
        return True

    def run(self, request: DetectorRunRequest) -> DetectorRunResult:
        minimum_run = int(request.configuration["minimum_run_length"])  # type: ignore[call-overload]
        ratio_threshold = float(request.configuration["concentration_ratio"])  # type: ignore[arg-type]
        columns = request.dataset_profile.column_profiles
        keys = [profile.column.internal_key for profile in columns]

        kept = [
            index
            for index, row in enumerate(request.rows)
            if not all(_is_blank(row.get(key)) for key in keys)
        ]
        excluded = len(request.rows) - len(kept)
        observations: list[Observation] = []
        if len(kept) < minimum_run:
            return _result(self.metadata, observations)

        for profile in columns:
            key = profile.column.internal_key
            missing_flags = [_is_missing(request.rows[index].get(key)) for index in kept]
            missing_count = sum(missing_flags)
            if missing_count < minimum_run or missing_count == len(kept):
                continue

            best_start = best_length = 0
            run_start = run_length = 0
            for position, is_missing in enumerate(missing_flags):
                if is_missing:
                    if run_length == 0:
                        run_start = position
                    run_length += 1
                    if run_length > best_length:
                        best_start, best_length = run_start, run_length
                else:
                    run_length = 0
            share = best_length / missing_count
            if best_length < minimum_run or share < ratio_threshold:
                continue

            run_rows: list[RowReference] = [
                request.row_references[kept[position]]
                for position in range(best_start, best_start + best_length)
            ]
            observations.append(
                Observation(
                    observation_id=f"completeness.concentrated_missingness.observation.{key}",
                    kind=ObservationKind.VALUE_EVIDENCE,
                    producer_detector_id=self.metadata.detector_id,
                    producer_version=self.metadata.version,
                    summary=(
                        f"Column '{_display_name(profile.column)}' is missing in "
                        f"{missing_count} of {len(kept)} row(s); {best_length} of them are one "
                        f"unbroken run from row {run_rows[0].row_number} to row "
                        f"{run_rows[-1].row_number}."
                    ),
                    affected_columns=(profile.column,),
                    affected_row_references=tuple(run_rows[:MAX_OBSERVATION_ROW_REFERENCES]),
                    scope=SamplingScope.FULL,
                    structured_payload={
                        "row_count": len(kept),
                        "excluded_blank_row_count": excluded,
                        "missing_count": missing_count,
                        "longest_run_length": best_length,
                        "run_share": round(share, 4),
                        "first_row_number": run_rows[0].row_number,
                        "last_row_number": run_rows[-1].row_number,
                        "minimum_run_length": minimum_run,
                        "concentration_ratio": ratio_threshold,
                    },
                )
            )
        return _result(self.metadata, observations)
