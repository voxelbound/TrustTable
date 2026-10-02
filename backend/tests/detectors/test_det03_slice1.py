"""Tests for `DET-03` slice 1: `completeness.fully_empty_rows` and
`consistency.inconsistent_booleans`.

Follows `docs/detector-framework.md` §15's detector test contract: positive,
negative, threshold boundary, null/empty input, malformed input,
deterministic repeatability and a known false-positive example for each
detector, plus registry interoperation and an end-to-end analysis.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime

import pytest

from trusttable_backend.detectors.catalogue import DETECTORS
from trusttable_backend.detectors.completeness import FullyEmptyRowsDetector
from trusttable_backend.detectors.consistency import InconsistentBooleansDetector
from trusttable_backend.detectors.contract import (
    DetectorCategory,
    DetectorRunRequest,
    DetectorRunStatus,
    SecurityExposureState,
)
from trusttable_backend.detectors.engine import run_detectors
from trusttable_backend.domain.evidence import EvidenceType
from trusttable_backend.domain.parsing import SampleMetadata, SamplingScope
from trusttable_backend.domain.value_objects import ColumnReference, RowReference, Severity
from trusttable_backend.parsers.csv_parser import parse_csv
from trusttable_backend.profiling.metrics import compute_dataset_profile
from trusttable_backend.profiling.schemas import (
    ColumnProfile,
    DatasetProfile,
    InferredColumnType,
    ProfilingTiming,
)

ANALYSIS_TIMESTAMP = datetime(2026, 10, 2, 12, 0, tzinfo=UTC)
NO_EXPOSURE = SecurityExposureState(model_provider_enabled=False, sample_transmission_enabled=False)


def make_column(name: str, ordinal: int = 0) -> ColumnReference:
    return ColumnReference(original_name=name, internal_key=name, ordinal=ordinal)


def make_profile(
    names: tuple[str, ...],
    row_count: int,
    inferred_type: InferredColumnType = InferredColumnType.CATEGORICAL,
) -> DatasetProfile:
    profiles = tuple(
        ColumnProfile(
            column=make_column(name, ordinal),
            inferred_type=inferred_type,
            null_count=0,
            distinct_count=min(1, row_count),
            metrics={},
            warnings=(),
        )
        for ordinal, name in enumerate(names)
    )
    return DatasetProfile(
        schema_version="1",
        dataset_metrics={"row_count": row_count},
        column_profiles=profiles,
        sampling=SampleMetadata(
            scope=SamplingScope.FULL, population_size=row_count, sample_size=row_count
        ),
        warnings=(),
        timing=ProfilingTiming(
            started_at=ANALYSIS_TIMESTAMP, completed_at=ANALYSIS_TIMESTAMP, duration_ms=1
        ),
    )


def make_request(
    profile: DatasetProfile, rows: tuple[Mapping[str, object], ...]
) -> DetectorRunRequest:
    return DetectorRunRequest(
        dataset_profile=profile,
        rows=rows,
        row_references=tuple(RowReference(row_number=i) for i in range(len(rows))),
        confirmed_context=None,
        configuration={},
        analysis_timestamp=ANALYSIS_TIMESTAMP,
        security_exposure=NO_EXPOSURE,
    )


# ---------------------------------------------------------------------------
# completeness.fully_empty_rows
# ---------------------------------------------------------------------------


def test_fully_empty_rows_metadata_and_config() -> None:
    detector = FullyEmptyRowsDetector()
    assert detector.metadata.detector_id == "completeness.fully_empty_rows"
    assert detector.metadata.category is DetectorCategory.COMPLETENESS
    assert detector.metadata.requires_raw_rows is True
    assert detector.metadata.requires_confirmed_context is False
    detector.config_schema.model_validate({})


def test_fully_empty_rows_flags_rows_blank_in_every_column() -> None:
    profile = make_profile(("a", "b"), row_count=4)
    rows = (
        {"a": "x", "b": "1"},
        {"a": None, "b": None},
        {"a": "", "b": "   "},
        {"a": "y", "b": None},
    )

    result = FullyEmptyRowsDetector().run(make_request(profile, rows))

    assert result.status is DetectorRunStatus.SUCCESS
    (finding,) = result.findings
    (evidence,) = result.evidence
    assert [ref.row_number for ref in finding.affected_row_references] == [1, 2]
    assert finding.severity is Severity.LOW
    assert finding.confidence == 1.0
    assert finding.affected_columns == ()
    assert finding.evidence_ids == (evidence.evidence_id,)
    assert evidence.evidence_type is EvidenceType.ROW_SET
    assert evidence.structured_payload == {
        "empty_row_count": 2,
        "column_count": 2,
        "total_row_count": 4,
    }


def test_fully_empty_rows_boundary_one_value_is_not_empty() -> None:
    profile = make_profile(("a", "b"), row_count=2)
    rows = ({"a": "x", "b": None}, {"a": None, "b": "0"})

    result = FullyEmptyRowsDetector().run(make_request(profile, rows))

    assert result.findings == ()
    assert result.evidence == ()


def test_fully_empty_rows_placeholders_are_not_blank() -> None:
    """Known false-positive guard: 'N/A' and '-' are content, not blanks."""
    profile = make_profile(("a", "b"), row_count=1)

    result = FullyEmptyRowsDetector().run(make_request(profile, ({"a": "N/A", "b": "-"},)))

    assert result.findings == ()


@pytest.mark.parametrize(
    ("names", "rows"),
    [((), ()), (("a",), ()), ((), ({"a": None},))],
)
def test_fully_empty_rows_null_and_empty_inputs_produce_no_finding(
    names: tuple[str, ...], rows: tuple[Mapping[str, object], ...]
) -> None:
    result = FullyEmptyRowsDetector().run(make_request(make_profile(names, len(rows)), rows))

    assert result.status is DetectorRunStatus.SUCCESS
    assert result.findings == ()


def test_fully_empty_rows_ignores_non_string_cells_without_failing() -> None:
    """Malformed input: a stored non-string value is content, never an error."""
    profile = make_profile(("a",), row_count=2)

    result = FullyEmptyRowsDetector().run(make_request(profile, ({"a": 0}, {"a": None})))

    assert [ref.row_number for ref in result.findings[0].affected_row_references] == [1]


def test_fully_empty_rows_is_repeatable() -> None:
    profile = make_profile(("a",), row_count=2)
    request = make_request(profile, ({"a": None}, {"a": "x"}))

    assert FullyEmptyRowsDetector().run(request) == FullyEmptyRowsDetector().run(request)


# ---------------------------------------------------------------------------
# consistency.inconsistent_booleans
# ---------------------------------------------------------------------------


def _booleans(
    values: tuple[object, ...],
) -> tuple[DatasetProfile, tuple[Mapping[str, object], ...]]:
    rows = tuple({"flag": value} for value in values)
    return make_profile(("flag",), row_count=len(rows)), rows


def test_inconsistent_booleans_metadata_and_config() -> None:
    detector = InconsistentBooleansDetector()
    assert detector.metadata.detector_id == "consistency.inconsistent_booleans"
    assert detector.metadata.category is DetectorCategory.CONSISTENCY
    assert detector.metadata.requires_raw_rows is True
    assert detector.metadata.documented_limitations
    detector.config_schema.model_validate({})


def test_inconsistent_booleans_flags_mixed_spelling_families() -> None:
    profile, rows = _booleans(("Y", "yes", "TRUE", "N", None, ""))

    result = InconsistentBooleansDetector().run(make_request(profile, rows))

    (finding,) = result.findings
    (evidence,) = result.evidence
    assert [ref.row_number for ref in finding.affected_row_references] == [0, 1, 2, 3]
    assert finding.severity is Severity.LOW
    assert finding.confidence == 0.9
    assert [column.original_name for column in finding.affected_columns] == ["flag"]
    assert evidence.structured_payload == {
        "spelling_families": ["true/false", "y/n", "yes/no"],
        "distinct_spellings": ["N", "TRUE", "Y", "yes"],
        "affected_row_count": 4,
    }
    # Only closed-vocabulary tokens ever reach the evidence text.
    assert "TRUE" in finding.calculated_observation


def test_inconsistent_booleans_numeric_and_word_families_mix() -> None:
    profile, rows = _booleans(("1", "0", "yes"))

    result = InconsistentBooleansDetector().run(make_request(profile, rows))

    assert len(result.findings) == 1


@pytest.mark.parametrize(
    "values",
    [
        ("Y", "N", "Y"),  # one family
        ("1", "0", "1"),  # plain 0/1 flags
        ("yes", "YES", "No"),  # casing only: capitalization detector's territory
        ("true", "true"),
        ("Y", "N", "Maybe"),  # not every value is boolean: a status column
        ("Y", "yes", "Unknown"),  # mixed families but not a boolean column
        ("Y",),
        (),
        (None, "", "  "),
    ],
)
def test_inconsistent_booleans_does_not_flag_consistent_or_non_boolean_columns(
    values: tuple[object, ...],
) -> None:
    profile, rows = _booleans(values)

    result = InconsistentBooleansDetector().run(make_request(profile, rows))

    assert result.status is DetectorRunStatus.SUCCESS
    assert result.findings == ()
    assert result.evidence == ()


@pytest.mark.parametrize(
    "inferred_type",
    [
        InferredColumnType.NUMERIC,
        InferredColumnType.DATE,
        InferredColumnType.IDENTIFIER,
        InferredColumnType.UNKNOWN,
    ],
)
def test_inconsistent_booleans_skips_out_of_scope_column_types(
    inferred_type: InferredColumnType,
) -> None:
    rows: tuple[Mapping[str, object], ...] = ({"flag": "Y"}, {"flag": "yes"})
    profile = make_profile(("flag",), row_count=2, inferred_type=inferred_type)

    result = InconsistentBooleansDetector().run(make_request(profile, rows))

    assert result.findings == ()


def test_inconsistent_booleans_ignores_non_string_cells_without_failing() -> None:
    profile, rows = _booleans((1, "Y", "yes", None))

    result = InconsistentBooleansDetector().run(make_request(profile, rows))

    assert [ref.row_number for ref in result.findings[0].affected_row_references] == [1, 2]


def test_inconsistent_booleans_flags_each_column_independently() -> None:
    profile = make_profile(("a", "b"), row_count=2)
    rows = ({"a": "Y", "b": "Y"}, {"a": "yes", "b": "N"})

    result = InconsistentBooleansDetector().run(make_request(profile, rows))

    assert [f.affected_columns[0].original_name for f in result.findings] == ["a"]


def test_inconsistent_booleans_is_repeatable() -> None:
    profile, rows = _booleans(("Y", "yes"))
    request = make_request(profile, rows)

    assert InconsistentBooleansDetector().run(request) == InconsistentBooleansDetector().run(
        request
    )


# ---------------------------------------------------------------------------
# Registry interoperation and an end-to-end analysis
# ---------------------------------------------------------------------------


def test_both_detectors_are_registered_with_unique_ids() -> None:
    ids = [detector.metadata.detector_id for detector in DETECTORS]
    assert len(ids) == len(set(ids))
    assert {"completeness.fully_empty_rows", "consistency.inconsistent_booleans"} <= set(ids)


def test_end_to_end_parse_profile_detect_reports_both_problems() -> None:
    csv_bytes = b"id,active,note\n1,Y,a\n2,yes,b\n,,\n3,TRUE,c\n4,N,d\n"
    parsed = parse_csv(csv_bytes)
    profile = compute_dataset_profile(
        parsed.parsed_dataset.columns,
        parsed.rows,
        parsed.parsed_dataset.sampling,
        as_of=ANALYSIS_TIMESTAMP.date(),
    )
    keyed = tuple(
        {column.internal_key: row[column.ordinal] for column in parsed.parsed_dataset.columns}
        for row in parsed.rows
    )

    results = run_detectors(
        list(DETECTORS),
        dataset_profile=profile,
        rows=keyed,
        row_references=parsed.parsed_dataset.row_references,
        confirmed_context=None,
        security_exposure=NO_EXPOSURE,
        analysis_timestamp=ANALYSIS_TIMESTAMP,
    )

    by_detector = {result.detector_id: result.findings for result in results if result.findings}
    assert "completeness.fully_empty_rows" in by_detector
    assert "consistency.inconsistent_booleans" in by_detector
    (empty_rows,) = by_detector["completeness.fully_empty_rows"]
    assert [ref.row_number for ref in empty_rows.affected_row_references] == [2]
    (booleans,) = by_detector["consistency.inconsistent_booleans"]
    assert [column.original_name for column in booleans.affected_columns] == ["active"]
