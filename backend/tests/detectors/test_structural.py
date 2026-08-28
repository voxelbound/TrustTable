"""Tests for the structural detectors (DET-02 partial).

Covers this package's acceptance criteria AC-01..AC-12, AC-16:
`ExactDuplicateRowsDetector`/`EmptyColumnDetector` metadata, `supports()`,
and `run()` positive/negative/boundary/null cases, plus a real-file
end-to-end check against the committed `demo-data/sales_demo.csv`.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, date, datetime
from pathlib import Path

from trusttable_backend.detectors.catalogue import DETECTORS
from trusttable_backend.detectors.contract import (
    DetectorCategory,
    DetectorRunRequest,
    DetectorRunStatus,
    DetectorSupportRequest,
    SecurityExposureState,
)
from trusttable_backend.detectors.engine import run_detectors
from trusttable_backend.detectors.structural import EmptyColumnDetector, ExactDuplicateRowsDetector
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

REPO_ROOT = Path(__file__).resolve().parents[3]
DEMO_CSV_PATH = REPO_ROOT / "demo-data" / "sales_demo.csv"

ANALYSIS_TIMESTAMP = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)
NO_EXPOSURE = SecurityExposureState(model_provider_enabled=False, sample_transmission_enabled=False)


def make_column(name: str, ordinal: int) -> ColumnReference:
    return ColumnReference(original_name=name, internal_key=name, ordinal=ordinal)


def make_column_profile(
    column: ColumnReference, inferred_type: InferredColumnType, **overrides: object
) -> ColumnProfile:
    fields: dict[str, object] = {
        "column": column,
        "inferred_type": inferred_type,
        "null_count": 0,
        "distinct_count": 1,
        "metrics": {},
        "warnings": (),
    }
    fields.update(overrides)
    return ColumnProfile(**fields)  # type: ignore[arg-type]


def make_dataset_profile(
    column_profiles: tuple[ColumnProfile, ...], row_count: int
) -> DatasetProfile:
    return DatasetProfile(
        schema_version="1",
        dataset_metrics={"row_count": row_count},
        column_profiles=column_profiles,
        sampling=SampleMetadata(
            scope=SamplingScope.FULL, population_size=row_count, sample_size=row_count
        ),
        warnings=(),
        timing=ProfilingTiming(
            started_at=ANALYSIS_TIMESTAMP, completed_at=ANALYSIS_TIMESTAMP, duration_ms=1
        ),
    )


def make_run_request(
    dataset_profile: DatasetProfile,
    rows: tuple[Mapping[str, object], ...],
) -> DetectorRunRequest:
    row_references = tuple(RowReference(row_number=i) for i in range(len(rows)))
    return DetectorRunRequest(
        dataset_profile=dataset_profile,
        rows=rows,
        row_references=row_references,
        confirmed_context=None,
        configuration={},
        analysis_timestamp=ANALYSIS_TIMESTAMP,
        security_exposure=NO_EXPOSURE,
    )


# ---------------------------------------------------------------------------
# AC-01/AC-03/AC-04: ExactDuplicateRowsDetector metadata/supports
# ---------------------------------------------------------------------------


def test_exact_duplicate_rows_metadata() -> None:
    detector = ExactDuplicateRowsDetector()
    assert detector.metadata.detector_id == "structural.exact_duplicate_rows"
    assert detector.metadata.category is DetectorCategory.STRUCTURAL
    assert detector.metadata.requires_raw_rows is True
    assert detector.metadata.requires_confirmed_context is False


def test_exact_duplicate_rows_config_schema_accepts_empty_configuration() -> None:
    detector = ExactDuplicateRowsDetector()
    detector.config_schema.model_validate({})


def test_exact_duplicate_rows_supports_returns_true() -> None:
    detector = ExactDuplicateRowsDetector()
    dataset_profile = make_dataset_profile((), row_count=0)
    request = DetectorSupportRequest(
        dataset_profile=dataset_profile, confirmed_context=None, security_exposure=NO_EXPOSURE
    )
    assert detector.supports(request) is True


# ---------------------------------------------------------------------------
# AC-05..AC-08: ExactDuplicateRowsDetector.run()
# ---------------------------------------------------------------------------


def test_exact_duplicate_rows_run_no_duplicates() -> None:
    detector = ExactDuplicateRowsDetector()
    dataset_profile = make_dataset_profile((), row_count=2)
    rows = ({"id": "1", "name": "a"}, {"id": "2", "name": "b"})
    result = detector.run(make_run_request(dataset_profile, rows))

    assert result.status is DetectorRunStatus.SUCCESS
    assert result.findings == ()
    assert result.evidence == ()


def test_exact_duplicate_rows_run_one_duplicate_pair() -> None:
    detector = ExactDuplicateRowsDetector()
    dataset_profile = make_dataset_profile((), row_count=3)
    rows = ({"id": "1", "name": "a"}, {"id": "1", "name": "a"}, {"id": "2", "name": "b"})
    result = detector.run(make_run_request(dataset_profile, rows))

    assert result.status is DetectorRunStatus.SUCCESS
    assert len(result.findings) == 1
    finding = result.findings[0]
    assert len(finding.affected_row_references) == 2
    assert finding.confidence == 1.0
    assert finding.severity is Severity.MEDIUM
    assert len(result.evidence) == 1
    assert finding.evidence_ids == (result.evidence[0].evidence_id,)


def test_exact_duplicate_rows_run_two_separate_groups() -> None:
    detector = ExactDuplicateRowsDetector()
    dataset_profile = make_dataset_profile((), row_count=4)
    rows = (
        {"id": "1", "name": "a"},
        {"id": "1", "name": "a"},
        {"id": "2", "name": "b"},
        {"id": "2", "name": "b"},
    )
    result = detector.run(make_run_request(dataset_profile, rows))

    assert len(result.findings) == 1
    finding = result.findings[0]
    assert len(finding.affected_row_references) == 4
    assert result.evidence[0].structured_payload["duplicate_group_count"] == 2
    assert result.evidence[0].structured_payload["duplicate_row_count"] == 2


def test_exact_duplicate_rows_run_none_and_empty_string_not_conflated() -> None:
    detector = ExactDuplicateRowsDetector()
    dataset_profile = make_dataset_profile((), row_count=2)
    rows = ({"id": None, "name": "a"}, {"id": "", "name": "a"})
    result = detector.run(make_run_request(dataset_profile, rows))

    assert result.findings == ()


# ---------------------------------------------------------------------------
# AC-02/AC-03/AC-09: EmptyColumnDetector metadata/supports
# ---------------------------------------------------------------------------


def test_empty_column_metadata() -> None:
    detector = EmptyColumnDetector()
    assert detector.metadata.detector_id == "structural.empty_column"
    assert detector.metadata.category is DetectorCategory.STRUCTURAL
    assert detector.metadata.requires_raw_rows is False
    assert detector.metadata.requires_confirmed_context is False


def test_empty_column_config_schema_accepts_empty_configuration() -> None:
    detector = EmptyColumnDetector()
    detector.config_schema.model_validate({})


def test_empty_column_supports_returns_true() -> None:
    detector = EmptyColumnDetector()
    dataset_profile = make_dataset_profile((), row_count=0)
    request = DetectorSupportRequest(
        dataset_profile=dataset_profile, confirmed_context=None, security_exposure=NO_EXPOSURE
    )
    assert detector.supports(request) is True


# ---------------------------------------------------------------------------
# AC-10..AC-12: EmptyColumnDetector.run()
# ---------------------------------------------------------------------------


def test_empty_column_run_no_empty_columns() -> None:
    detector = EmptyColumnDetector()
    column = make_column("qty", 0)
    dataset_profile = make_dataset_profile(
        (make_column_profile(column, InferredColumnType.NUMERIC),), row_count=1
    )
    result = detector.run(make_run_request(dataset_profile, ()))

    assert result.status is DetectorRunStatus.SUCCESS
    assert result.findings == ()
    assert result.evidence == ()


def test_empty_column_run_one_empty_column() -> None:
    detector = EmptyColumnDetector()
    column = make_column("empty_col", 0)
    dataset_profile = make_dataset_profile(
        (make_column_profile(column, InferredColumnType.UNKNOWN, null_count=3, distinct_count=0),),
        row_count=3,
    )
    result = detector.run(make_run_request(dataset_profile, ()))

    assert len(result.findings) == 1
    finding = result.findings[0]
    assert finding.affected_columns == (column,)
    assert finding.confidence == 1.0
    assert finding.severity is Severity.MEDIUM
    assert len(result.evidence) == 1
    assert finding.evidence_ids == (result.evidence[0].evidence_id,)


def test_empty_column_run_two_empty_columns() -> None:
    detector = EmptyColumnDetector()
    column_a = make_column("empty_a", 0)
    column_b = make_column("empty_b", 1)
    dataset_profile = make_dataset_profile(
        (
            make_column_profile(
                column_a, InferredColumnType.UNKNOWN, null_count=3, distinct_count=0
            ),
            make_column_profile(
                column_b, InferredColumnType.UNKNOWN, null_count=3, distinct_count=0
            ),
        ),
        row_count=3,
    )
    result = detector.run(make_run_request(dataset_profile, ()))

    assert len(result.findings) == 2
    assert {f.affected_columns[0] for f in result.findings} == {column_a, column_b}
    assert len(result.evidence) == 2


# ---------------------------------------------------------------------------
# AC-15/AC-16: run_detectors() interoperation and real-file check
# ---------------------------------------------------------------------------


def test_run_detectors_scopes_rows_correctly_for_both_detectors() -> None:
    column = make_column("empty_col", 0)
    dataset_profile = make_dataset_profile(
        (make_column_profile(column, InferredColumnType.UNKNOWN, null_count=2, distinct_count=0),),
        row_count=2,
    )
    rows = ({"empty_col": None}, {"empty_col": None})
    row_references = (RowReference(row_number=0), RowReference(row_number=1))

    results = run_detectors(
        list(DETECTORS),
        dataset_profile=dataset_profile,
        rows=rows,
        row_references=row_references,
        confirmed_context=None,
        security_exposure=NO_EXPOSURE,
        analysis_timestamp=ANALYSIS_TIMESTAMP,
    )

    by_id = {r.detector_id: r for r in results}
    assert by_id["structural.empty_column"].status is DetectorRunStatus.SUCCESS
    assert len(by_id["structural.empty_column"].findings) == 1
    assert by_id["structural.exact_duplicate_rows"].status is DetectorRunStatus.SUCCESS
    assert len(by_id["structural.exact_duplicate_rows"].findings) == 1


def test_real_demo_csv_structural_detectors() -> None:
    content = DEMO_CSV_PATH.read_bytes()
    parsed = parse_csv(content)
    columns = parsed.parsed_dataset.columns

    dataset_profile = compute_dataset_profile(
        columns, parsed.rows, parsed.parsed_dataset.sampling, as_of=date(2099, 1, 1)
    )
    mapping_rows = tuple(
        {column.internal_key: row[column.ordinal] for column in columns} for row in parsed.rows
    )

    results = run_detectors(
        list(DETECTORS),
        dataset_profile=dataset_profile,
        rows=mapping_rows,
        row_references=parsed.parsed_dataset.row_references,
        confirmed_context=None,
        security_exposure=NO_EXPOSURE,
        analysis_timestamp=ANALYSIS_TIMESTAMP,
    )
    by_id = {r.detector_id: r for r in results}

    duplicate_result = by_id["structural.exact_duplicate_rows"]
    assert len(duplicate_result.findings) == 1
    assert duplicate_result.evidence[0].structured_payload["duplicate_row_count"] == 1

    empty_column_result = by_id["structural.empty_column"]
    assert len(empty_column_result.findings) == 1
    assert empty_column_result.findings[0].affected_columns[0].original_name == "empty_col"
