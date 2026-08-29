"""Tests for the consistency detectors (DET-02 partial, WP-016).

Covers this package's acceptance criteria AC-01..AC-13, AC-16, AC-17:
`InconsistentCapitalizationDetector`/`LeadingTrailingWhitespaceDetector`
metadata, `supports()`, and `run()` positive/negative/boundary/null
cases, `run_detectors()` interoperation, and a real-file end-to-end check
against the committed `demo-data/sales_demo.csv`.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, date, datetime
from pathlib import Path

from trusttable_backend.detectors.catalogue import DETECTORS
from trusttable_backend.detectors.consistency import (
    InconsistentCapitalizationDetector,
    LeadingTrailingWhitespaceDetector,
)
from trusttable_backend.detectors.contract import (
    DetectorCategory,
    DetectorRunRequest,
    DetectorRunStatus,
    DetectorSupportRequest,
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
# AC-01/AC-03/AC-04: InconsistentCapitalizationDetector metadata/supports
# ---------------------------------------------------------------------------


def test_inconsistent_capitalization_metadata() -> None:
    detector = InconsistentCapitalizationDetector()
    assert detector.metadata.detector_id == "consistency.inconsistent_capitalization"
    assert detector.metadata.category is DetectorCategory.CONSISTENCY
    assert detector.metadata.requires_raw_rows is True
    assert detector.metadata.requires_confirmed_context is False
    assert detector.metadata.applicable_inferred_types == (
        InferredColumnType.TEXT,
        InferredColumnType.CATEGORICAL,
        InferredColumnType.IDENTIFIER,
    )


def test_inconsistent_capitalization_config_schema_accepts_empty_configuration() -> None:
    detector = InconsistentCapitalizationDetector()
    detector.config_schema.model_validate({})


def test_inconsistent_capitalization_supports_returns_true() -> None:
    detector = InconsistentCapitalizationDetector()
    dataset_profile = make_dataset_profile((), row_count=0)
    request = DetectorSupportRequest(
        dataset_profile=dataset_profile, confirmed_context=None, security_exposure=NO_EXPOSURE
    )
    assert detector.supports(request) is True


# ---------------------------------------------------------------------------
# AC-05..AC-09: InconsistentCapitalizationDetector.run()
# ---------------------------------------------------------------------------


def test_inconsistent_capitalization_run_no_conflict() -> None:
    detector = InconsistentCapitalizationDetector()
    column = make_column("category", 0)
    dataset_profile = make_dataset_profile(
        (make_column_profile(column, InferredColumnType.CATEGORICAL, distinct_count=1),),
        row_count=3,
    )
    rows = ({"category": "Home Goods"}, {"category": "Home Goods"}, {"category": "Home Goods"})
    result = detector.run(make_run_request(dataset_profile, rows))

    assert result.status is DetectorRunStatus.SUCCESS
    assert result.findings == ()
    assert result.evidence == ()


def test_inconsistent_capitalization_run_one_conflicting_group() -> None:
    detector = InconsistentCapitalizationDetector()
    column = make_column("category", 0)
    dataset_profile = make_dataset_profile(
        (make_column_profile(column, InferredColumnType.CATEGORICAL, distinct_count=2),),
        row_count=3,
    )
    rows = ({"category": "Home Goods"}, {"category": "HOME GOODS"}, {"category": "Textiles"})
    result = detector.run(make_run_request(dataset_profile, rows))

    assert result.status is DetectorRunStatus.SUCCESS
    assert len(result.findings) == 1
    finding = result.findings[0]
    assert finding.affected_columns == (column,)
    assert {ref.row_number for ref in finding.affected_row_references} == {0, 1}
    assert finding.confidence == 1.0
    assert finding.severity is Severity.LOW
    assert len(result.evidence) == 1
    assert result.evidence[0].evidence_type is EvidenceType.ROW_SET
    assert finding.evidence_ids == (result.evidence[0].evidence_id,)


def test_inconsistent_capitalization_run_whitespace_only_difference_not_flagged() -> None:
    detector = InconsistentCapitalizationDetector()
    column = make_column("customer_name", 0)
    dataset_profile = make_dataset_profile(
        (make_column_profile(column, InferredColumnType.TEXT, distinct_count=2),),
        row_count=2,
    )
    rows = ({"customer_name": "Alex Chen"}, {"customer_name": "  Alex Chen"})
    result = detector.run(make_run_request(dataset_profile, rows))

    assert result.findings == ()
    assert result.evidence == ()


def test_inconsistent_capitalization_run_two_conflicting_groups() -> None:
    detector = InconsistentCapitalizationDetector()
    column = make_column("category", 0)
    dataset_profile = make_dataset_profile(
        (make_column_profile(column, InferredColumnType.CATEGORICAL, distinct_count=4),),
        row_count=4,
    )
    rows = (
        {"category": "Office Supplies"},
        {"category": "OFFICE SUPPLIES"},
        {"category": "Textiles"},
        {"category": "textiles"},
    )
    result = detector.run(make_run_request(dataset_profile, rows))

    assert len(result.findings) == 2
    assert len(result.evidence) == 2
    all_affected = {
        ref.row_number for finding in result.findings for ref in finding.affected_row_references
    }
    assert all_affected == {0, 1, 2, 3}


def test_inconsistent_capitalization_run_ignores_non_text_family_column() -> None:
    detector = InconsistentCapitalizationDetector()
    column = make_column("quantity", 0)
    dataset_profile = make_dataset_profile(
        (make_column_profile(column, InferredColumnType.NUMERIC, distinct_count=2),),
        row_count=2,
    )
    rows = ({"quantity": "TRUE"}, {"quantity": "true"})
    result = detector.run(make_run_request(dataset_profile, rows))

    assert result.findings == ()
    assert result.evidence == ()


# ---------------------------------------------------------------------------
# AC-02/AC-03/AC-04: LeadingTrailingWhitespaceDetector metadata/supports
# ---------------------------------------------------------------------------


def test_leading_trailing_whitespace_metadata() -> None:
    detector = LeadingTrailingWhitespaceDetector()
    assert detector.metadata.detector_id == "consistency.leading_trailing_whitespace"
    assert detector.metadata.category is DetectorCategory.CONSISTENCY
    assert detector.metadata.requires_raw_rows is True
    assert detector.metadata.requires_confirmed_context is False
    assert detector.metadata.applicable_inferred_types == (
        InferredColumnType.TEXT,
        InferredColumnType.CATEGORICAL,
        InferredColumnType.IDENTIFIER,
    )


def test_leading_trailing_whitespace_config_schema_accepts_empty_configuration() -> None:
    detector = LeadingTrailingWhitespaceDetector()
    detector.config_schema.model_validate({})


def test_leading_trailing_whitespace_supports_returns_true() -> None:
    detector = LeadingTrailingWhitespaceDetector()
    dataset_profile = make_dataset_profile((), row_count=0)
    request = DetectorSupportRequest(
        dataset_profile=dataset_profile, confirmed_context=None, security_exposure=NO_EXPOSURE
    )
    assert detector.supports(request) is True


# ---------------------------------------------------------------------------
# AC-10..AC-13: LeadingTrailingWhitespaceDetector.run()
# ---------------------------------------------------------------------------


def test_leading_trailing_whitespace_run_no_issue() -> None:
    detector = LeadingTrailingWhitespaceDetector()
    column = make_column("customer_name", 0)
    dataset_profile = make_dataset_profile(
        (
            make_column_profile(
                column,
                InferredColumnType.TEXT,
                distinct_count=2,
                metrics={"whitespace_issue_count": 0},
            ),
        ),
        row_count=2,
    )
    rows = ({"customer_name": "Alex Chen"}, {"customer_name": "Jordan Lee"})
    result = detector.run(make_run_request(dataset_profile, rows))

    assert result.status is DetectorRunStatus.SUCCESS
    assert result.findings == ()
    assert result.evidence == ()


def test_leading_trailing_whitespace_run_one_column_affected() -> None:
    detector = LeadingTrailingWhitespaceDetector()
    column = make_column("customer_name", 0)
    dataset_profile = make_dataset_profile(
        (
            make_column_profile(
                column,
                InferredColumnType.TEXT,
                distinct_count=2,
                metrics={"whitespace_issue_count": 2},
            ),
        ),
        row_count=3,
    )
    rows = (
        {"customer_name": "  Alex Chen"},
        {"customer_name": "Jordan Lee  "},
        {"customer_name": "Sam Rivera"},
    )
    result = detector.run(make_run_request(dataset_profile, rows))

    assert result.status is DetectorRunStatus.SUCCESS
    assert len(result.findings) == 1
    finding = result.findings[0]
    assert finding.affected_columns == (column,)
    assert {ref.row_number for ref in finding.affected_row_references} == {0, 1}
    assert finding.confidence == 1.0
    assert finding.severity is Severity.LOW
    assert len(result.evidence) == 1
    assert result.evidence[0].evidence_type is EvidenceType.ROW_SET
    assert finding.evidence_ids == (result.evidence[0].evidence_id,)


def test_leading_trailing_whitespace_run_two_columns_affected() -> None:
    detector = LeadingTrailingWhitespaceDetector()
    column_a = make_column("customer_name", 0)
    column_b = make_column("notes", 1)
    dataset_profile = make_dataset_profile(
        (
            make_column_profile(
                column_a,
                InferredColumnType.TEXT,
                distinct_count=1,
                metrics={"whitespace_issue_count": 1},
            ),
            make_column_profile(
                column_b,
                InferredColumnType.TEXT,
                distinct_count=1,
                metrics={"whitespace_issue_count": 1},
            ),
        ),
        row_count=1,
    )
    rows = ({"customer_name": " Alex Chen", "notes": "hello "},)
    result = detector.run(make_run_request(dataset_profile, rows))

    assert len(result.findings) == 2
    assert {finding.affected_columns[0] for finding in result.findings} == {column_a, column_b}


def test_leading_trailing_whitespace_run_leading_trailing_and_both_sides() -> None:
    detector = LeadingTrailingWhitespaceDetector()
    column = make_column("customer_name", 0)
    dataset_profile = make_dataset_profile(
        (
            make_column_profile(
                column,
                InferredColumnType.TEXT,
                distinct_count=3,
                metrics={"whitespace_issue_count": 3},
            ),
        ),
        row_count=3,
    )
    rows = (
        {"customer_name": " Leading"},
        {"customer_name": "Trailing "},
        {"customer_name": " Both "},
    )
    result = detector.run(make_run_request(dataset_profile, rows))

    assert len(result.findings) == 1
    assert {ref.row_number for ref in result.findings[0].affected_row_references} == {0, 1, 2}


# ---------------------------------------------------------------------------
# AC-16/AC-17: run_detectors() interoperation and real-file check
# ---------------------------------------------------------------------------


def test_run_detectors_scopes_rows_correctly_for_both_consistency_detectors() -> None:
    category_column = make_column("category", 0)
    name_column = make_column("customer_name", 1)
    dataset_profile = make_dataset_profile(
        (
            make_column_profile(category_column, InferredColumnType.CATEGORICAL, distinct_count=2),
            make_column_profile(
                name_column,
                InferredColumnType.TEXT,
                distinct_count=1,
                metrics={"whitespace_issue_count": 1},
            ),
        ),
        row_count=2,
    )
    rows = (
        {"category": "Home Goods", "customer_name": "Alex Chen"},
        {"category": "HOME GOODS", "customer_name": " Alex Chen"},
    )
    row_references = tuple(RowReference(row_number=i) for i in range(2))

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
    assert by_id["consistency.inconsistent_capitalization"].status is DetectorRunStatus.SUCCESS
    assert len(by_id["consistency.inconsistent_capitalization"].findings) == 1
    assert by_id["consistency.leading_trailing_whitespace"].status is DetectorRunStatus.SUCCESS
    assert len(by_id["consistency.leading_trailing_whitespace"].findings) == 1


def test_real_demo_csv_consistency_detectors() -> None:
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

    capitalization_result = by_id["consistency.inconsistent_capitalization"]
    assert len(capitalization_result.findings) == 2
    row_counts = sorted(
        len(finding.affected_row_references) for finding in capitalization_result.findings
    )
    assert row_counts == [35, 48]
    for finding in capitalization_result.findings:
        assert finding.affected_columns[0].original_name == "category"

    whitespace_result = by_id["consistency.leading_trailing_whitespace"]
    assert len(whitespace_result.findings) == 1
    finding = whitespace_result.findings[0]
    assert finding.affected_columns[0].original_name == "customer_name"
    assert len(finding.affected_row_references) == 2
