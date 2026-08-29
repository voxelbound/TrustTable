"""Tests for the validity detectors (DET-02 partial, WP-017/WP-018).

Covers WP-017's acceptance criteria AC-01..AC-13, AC-16, AC-17:
`FutureDatesDetector`/`NegativeLikelyNonNegativeValuesDetector`
metadata, `supports()`, and `run()` positive/negative/boundary/null
cases, `run_detectors()` interoperation, and a real-file end-to-end check
against the committed `demo-data/sales_demo.csv`. Also covers WP-018's
`InvalidPercentagesDetector` acceptance criteria AC-01 (partial), AC-03
(partial), AC-04 (partial), AC-05..AC-09, and extends the real-file check
toward AC-19.
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
from trusttable_backend.detectors.validity import (
    FutureDatesDetector,
    InvalidPercentagesDetector,
    NegativeLikelyNonNegativeValuesDetector,
)
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

ANALYSIS_TIMESTAMP = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)
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
# AC-01/AC-03/AC-04: FutureDatesDetector metadata/supports
# ---------------------------------------------------------------------------


def test_future_dates_metadata() -> None:
    detector = FutureDatesDetector()
    assert detector.metadata.detector_id == "validity.future_dates"
    assert detector.metadata.category is DetectorCategory.VALIDITY
    assert detector.metadata.requires_raw_rows is True
    assert detector.metadata.requires_confirmed_context is False
    assert detector.metadata.applicable_inferred_types == (InferredColumnType.DATE,)


def test_future_dates_config_schema_accepts_empty_configuration() -> None:
    detector = FutureDatesDetector()
    detector.config_schema.model_validate({})


def test_future_dates_supports_returns_true() -> None:
    detector = FutureDatesDetector()
    dataset_profile = make_dataset_profile((), row_count=0)
    request = DetectorSupportRequest(
        dataset_profile=dataset_profile, confirmed_context=None, security_exposure=NO_EXPOSURE
    )
    assert detector.supports(request) is True


# ---------------------------------------------------------------------------
# AC-05..AC-08: FutureDatesDetector.run()
# ---------------------------------------------------------------------------


def test_future_dates_run_no_future_dates() -> None:
    detector = FutureDatesDetector()
    column = make_column("order_date", 0)
    dataset_profile = make_dataset_profile(
        (make_column_profile(column, InferredColumnType.DATE, distinct_count=2),),
        row_count=2,
    )
    rows = ({"order_date": "2026-01-01"}, {"order_date": "2026-08-24"})
    result = detector.run(make_run_request(dataset_profile, rows))

    assert result.status is DetectorRunStatus.SUCCESS
    assert result.findings == ()
    assert result.evidence == ()


def test_future_dates_run_one_column_two_future_rows() -> None:
    detector = FutureDatesDetector()
    column = make_column("order_date", 0)
    dataset_profile = make_dataset_profile(
        (make_column_profile(column, InferredColumnType.DATE, distinct_count=3),),
        row_count=3,
    )
    rows = (
        {"order_date": "2026-01-01"},
        {"order_date": "2026-11-22"},
        {"order_date": "2027-03-12"},
    )
    result = detector.run(make_run_request(dataset_profile, rows))

    assert result.status is DetectorRunStatus.SUCCESS
    assert len(result.findings) == 1
    finding = result.findings[0]
    assert finding.affected_columns == (column,)
    assert {ref.row_number for ref in finding.affected_row_references} == {1, 2}
    assert finding.confidence == 1.0
    assert finding.severity is Severity.MEDIUM
    assert len(result.evidence) == 1
    assert result.evidence[0].evidence_type is EvidenceType.ROW_SET
    assert finding.evidence_ids == (result.evidence[0].evidence_id,)


def test_future_dates_run_exact_reference_date_not_future() -> None:
    detector = FutureDatesDetector()
    column = make_column("order_date", 0)
    dataset_profile = make_dataset_profile(
        (make_column_profile(column, InferredColumnType.DATE, distinct_count=1),),
        row_count=1,
    )
    rows = ({"order_date": "2026-08-24"},)
    result = detector.run(make_run_request(dataset_profile, rows))

    assert result.findings == ()
    assert result.evidence == ()


def test_future_dates_run_ignores_non_date_column() -> None:
    detector = FutureDatesDetector()
    column = make_column("notes", 0)
    dataset_profile = make_dataset_profile(
        (make_column_profile(column, InferredColumnType.TEXT, distinct_count=1),),
        row_count=1,
    )
    rows = ({"notes": "2099-01-01"},)
    result = detector.run(make_run_request(dataset_profile, rows))

    assert result.findings == ()
    assert result.evidence == ()


# ---------------------------------------------------------------------------
# AC-02/AC-03/AC-04: NegativeLikelyNonNegativeValuesDetector metadata/supports
# ---------------------------------------------------------------------------


def test_negative_likely_non_negative_values_metadata() -> None:
    detector = NegativeLikelyNonNegativeValuesDetector()
    assert detector.metadata.detector_id == "validity.negative_likely_non_negative_values"
    assert detector.metadata.category is DetectorCategory.VALIDITY
    assert detector.metadata.requires_raw_rows is True
    assert detector.metadata.requires_confirmed_context is False
    assert detector.metadata.applicable_inferred_types == (InferredColumnType.NUMERIC,)


def test_negative_likely_non_negative_values_config_schema_accepts_empty_configuration() -> None:
    detector = NegativeLikelyNonNegativeValuesDetector()
    detector.config_schema.model_validate({})


def test_negative_likely_non_negative_values_supports_returns_true() -> None:
    detector = NegativeLikelyNonNegativeValuesDetector()
    dataset_profile = make_dataset_profile((), row_count=0)
    request = DetectorSupportRequest(
        dataset_profile=dataset_profile, confirmed_context=None, security_exposure=NO_EXPOSURE
    )
    assert detector.supports(request) is True


# ---------------------------------------------------------------------------
# AC-09..AC-13: NegativeLikelyNonNegativeValuesDetector.run()
# ---------------------------------------------------------------------------


def test_negative_likely_non_negative_values_run_no_negative_count() -> None:
    detector = NegativeLikelyNonNegativeValuesDetector()
    column = make_column("quantity", 0)
    dataset_profile = make_dataset_profile(
        (
            make_column_profile(
                column,
                InferredColumnType.NUMERIC,
                distinct_count=5,
                metrics={"negative_count": 0},
            ),
        ),
        row_count=5,
    )
    rows = tuple({"quantity": "10"} for _ in range(5))
    result = detector.run(make_run_request(dataset_profile, rows))

    assert result.status is DetectorRunStatus.SUCCESS
    assert result.findings == ()
    assert result.evidence == ()


def test_negative_likely_non_negative_values_run_one_finding() -> None:
    detector = NegativeLikelyNonNegativeValuesDetector()
    column = make_column("quantity", 0)
    dataset_profile = make_dataset_profile(
        (
            make_column_profile(
                column,
                InferredColumnType.NUMERIC,
                distinct_count=10,
                metrics={"negative_count": 2},
            ),
        ),
        row_count=100,
    )
    rows = tuple({"quantity": ("-4" if i == 10 else "-7" if i == 20 else "5")} for i in range(100))
    result = detector.run(make_run_request(dataset_profile, rows))

    assert result.status is DetectorRunStatus.SUCCESS
    assert len(result.findings) == 1
    finding = result.findings[0]
    assert finding.affected_columns == (column,)
    assert {ref.row_number for ref in finding.affected_row_references} == {10, 20}
    assert finding.confidence == 0.7
    assert finding.severity is Severity.MEDIUM
    assert len(result.evidence) == 1
    assert result.evidence[0].evidence_type is EvidenceType.ROW_SET
    assert finding.evidence_ids == (result.evidence[0].evidence_id,)


def test_negative_likely_non_negative_values_run_boundary_at_and_below_threshold() -> None:
    detector = NegativeLikelyNonNegativeValuesDetector()
    column_at = make_column("col_at", 0)
    column_below = make_column("col_below", 1)
    dataset_profile = make_dataset_profile(
        (
            make_column_profile(
                column_at,
                InferredColumnType.NUMERIC,
                distinct_count=50,
                metrics={"negative_count": 10},
            ),
            make_column_profile(
                column_below,
                InferredColumnType.NUMERIC,
                distinct_count=50,
                metrics={"negative_count": 9},
            ),
        ),
        row_count=100,
    )
    rows = tuple(
        {
            "col_at": ("-1" if i < 10 else "1"),
            "col_below": ("-1" if i < 9 else "1"),
        }
        for i in range(100)
    )
    result = detector.run(make_run_request(dataset_profile, rows))

    fired_columns = {finding.affected_columns[0] for finding in result.findings}
    assert fired_columns == {column_below}


def test_negative_likely_non_negative_values_run_two_columns_two_findings() -> None:
    detector = NegativeLikelyNonNegativeValuesDetector()
    column_a = make_column("quantity", 0)
    column_b = make_column("tax_pct", 1)
    dataset_profile = make_dataset_profile(
        (
            make_column_profile(
                column_a,
                InferredColumnType.NUMERIC,
                distinct_count=5,
                metrics={"negative_count": 1},
            ),
            make_column_profile(
                column_b,
                InferredColumnType.NUMERIC,
                distinct_count=5,
                metrics={"negative_count": 1},
            ),
        ),
        row_count=100,
    )
    rows = tuple(
        {
            "quantity": ("-4" if i == 0 else "5"),
            "tax_pct": ("-5" if i == 50 else "10"),
        }
        for i in range(100)
    )
    result = detector.run(make_run_request(dataset_profile, rows))

    assert len(result.findings) == 2
    assert {finding.affected_columns[0] for finding in result.findings} == {column_a, column_b}


def test_negative_likely_non_negative_values_run_ignores_non_numeric_column() -> None:
    detector = NegativeLikelyNonNegativeValuesDetector()
    column = make_column("notes", 0)
    dataset_profile = make_dataset_profile(
        (
            make_column_profile(
                column,
                InferredColumnType.TEXT,
                distinct_count=1,
                metrics={"negative_count": 1},
            ),
        ),
        row_count=1,
    )
    rows = ({"notes": "-5"},)
    result = detector.run(make_run_request(dataset_profile, rows))

    assert result.findings == ()
    assert result.evidence == ()


# ---------------------------------------------------------------------------
# WP-018 AC-01/AC-03/AC-04: InvalidPercentagesDetector metadata/supports
# ---------------------------------------------------------------------------


def test_invalid_percentages_metadata() -> None:
    detector = InvalidPercentagesDetector()
    assert detector.metadata.detector_id == "validity.invalid_percentages"
    assert detector.metadata.category is DetectorCategory.VALIDITY
    assert detector.metadata.requires_raw_rows is True
    assert detector.metadata.requires_confirmed_context is False
    assert detector.metadata.applicable_inferred_types == (InferredColumnType.NUMERIC,)


def test_invalid_percentages_config_schema_accepts_empty_configuration() -> None:
    detector = InvalidPercentagesDetector()
    detector.config_schema.model_validate({})


def test_invalid_percentages_supports_returns_true() -> None:
    detector = InvalidPercentagesDetector()
    dataset_profile = make_dataset_profile((), row_count=0)
    request = DetectorSupportRequest(
        dataset_profile=dataset_profile, confirmed_context=None, security_exposure=NO_EXPOSURE
    )
    assert detector.supports(request) is True


# ---------------------------------------------------------------------------
# WP-018 AC-05..AC-09: InvalidPercentagesDetector.run()
# ---------------------------------------------------------------------------


def test_invalid_percentages_run_no_out_of_range_values() -> None:
    detector = InvalidPercentagesDetector()
    column = make_column("discount_pct", 0)
    dataset_profile = make_dataset_profile(
        (make_column_profile(column, InferredColumnType.NUMERIC, distinct_count=3),),
        row_count=3,
    )
    rows = ({"discount_pct": "0"}, {"discount_pct": "50"}, {"discount_pct": "100"})
    result = detector.run(make_run_request(dataset_profile, rows))

    assert result.status is DetectorRunStatus.SUCCESS
    assert result.findings == ()
    assert result.evidence == ()


def test_invalid_percentages_run_one_column_two_out_of_range_rows() -> None:
    detector = InvalidPercentagesDetector()
    column = make_column("discount_pct", 0)
    dataset_profile = make_dataset_profile(
        (make_column_profile(column, InferredColumnType.NUMERIC, distinct_count=3),),
        row_count=3,
    )
    rows = ({"discount_pct": "50"}, {"discount_pct": "150"}, {"discount_pct": "-5"})
    result = detector.run(make_run_request(dataset_profile, rows))

    assert result.status is DetectorRunStatus.SUCCESS
    assert len(result.findings) == 1
    finding = result.findings[0]
    assert finding.affected_columns == (column,)
    assert {ref.row_number for ref in finding.affected_row_references} == {1, 2}
    assert finding.confidence == 1.0
    assert finding.severity is Severity.MEDIUM
    assert len(result.evidence) == 1
    assert result.evidence[0].evidence_type is EvidenceType.ROW_SET
    assert finding.evidence_ids == (result.evidence[0].evidence_id,)


def test_invalid_percentages_run_boundary_values() -> None:
    detector = InvalidPercentagesDetector()
    column = make_column("tax_pct", 0)
    dataset_profile = make_dataset_profile(
        (make_column_profile(column, InferredColumnType.NUMERIC, distinct_count=4),),
        row_count=4,
    )
    rows = (
        {"tax_pct": "0"},
        {"tax_pct": "100"},
        {"tax_pct": "100.01"},
        {"tax_pct": "-0.01"},
    )
    result = detector.run(make_run_request(dataset_profile, rows))

    assert len(result.findings) == 1
    assert {ref.row_number for ref in result.findings[0].affected_row_references} == {2, 3}


def test_invalid_percentages_run_ignores_non_matching_column_name() -> None:
    detector = InvalidPercentagesDetector()
    column = make_column("quantity", 0)
    dataset_profile = make_dataset_profile(
        (make_column_profile(column, InferredColumnType.NUMERIC, distinct_count=1),),
        row_count=1,
    )
    rows = ({"quantity": "500"},)
    result = detector.run(make_run_request(dataset_profile, rows))

    assert result.findings == ()
    assert result.evidence == ()


def test_invalid_percentages_run_ignores_non_numeric_column() -> None:
    detector = InvalidPercentagesDetector()
    column = make_column("discount_pct", 0)
    dataset_profile = make_dataset_profile(
        (make_column_profile(column, InferredColumnType.TEXT, distinct_count=1),),
        row_count=1,
    )
    rows = ({"discount_pct": "150"},)
    result = detector.run(make_run_request(dataset_profile, rows))

    assert result.findings == ()
    assert result.evidence == ()


def test_invalid_percentages_run_two_columns_two_findings() -> None:
    detector = InvalidPercentagesDetector()
    column_a = make_column("discount_pct", 0)
    column_b = make_column("tax_pct", 1)
    dataset_profile = make_dataset_profile(
        (
            make_column_profile(column_a, InferredColumnType.NUMERIC, distinct_count=1),
            make_column_profile(column_b, InferredColumnType.NUMERIC, distinct_count=1),
        ),
        row_count=1,
    )
    rows = ({"discount_pct": "150", "tax_pct": "-5"},)
    result = detector.run(make_run_request(dataset_profile, rows))

    assert len(result.findings) == 2
    assert {finding.affected_columns[0] for finding in result.findings} == {column_a, column_b}


# ---------------------------------------------------------------------------
# AC-16/AC-17: run_detectors() interoperation and real-file check
# ---------------------------------------------------------------------------


def test_run_detectors_scopes_rows_correctly_for_both_validity_detectors() -> None:
    date_column = make_column("order_date", 0)
    numeric_column = make_column("quantity", 1)
    dataset_profile = make_dataset_profile(
        (
            make_column_profile(date_column, InferredColumnType.DATE, distinct_count=1),
            make_column_profile(
                numeric_column,
                InferredColumnType.NUMERIC,
                distinct_count=10,
                metrics={"negative_count": 1},
            ),
        ),
        row_count=100,
    )
    rows = tuple(
        {
            "order_date": ("2027-01-01" if i == 0 else "2026-01-01"),
            "quantity": ("-4" if i == 5 else "5"),
        }
        for i in range(100)
    )
    row_references = tuple(RowReference(row_number=i) for i in range(100))

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
    assert by_id["validity.future_dates"].status is DetectorRunStatus.SUCCESS
    assert len(by_id["validity.future_dates"].findings) == 1
    assert by_id["validity.negative_likely_non_negative_values"].status is DetectorRunStatus.SUCCESS
    assert len(by_id["validity.negative_likely_non_negative_values"].findings) == 1


def test_real_demo_csv_validity_detectors() -> None:
    content = DEMO_CSV_PATH.read_bytes()
    parsed = parse_csv(content)
    columns = parsed.parsed_dataset.columns

    dataset_profile = compute_dataset_profile(
        columns, parsed.rows, parsed.parsed_dataset.sampling, as_of=date(2026, 8, 24)
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

    future_dates_result = by_id["validity.future_dates"]
    assert len(future_dates_result.findings) == 1
    finding = future_dates_result.findings[0]
    assert finding.affected_columns[0].original_name == "order_date"
    assert len(finding.affected_row_references) == 2

    negative_result = by_id["validity.negative_likely_non_negative_values"]
    assert len(negative_result.findings) == 3
    by_column = {
        finding.affected_columns[0].original_name: finding for finding in negative_result.findings
    }
    assert set(by_column) == {"quantity", "line_total", "tax_pct"}
    assert len(by_column["quantity"].affected_row_references) == 2
    assert len(by_column["line_total"].affected_row_references) == 3
    assert len(by_column["tax_pct"].affected_row_references) == 1

    invalid_percentages_result = by_id["validity.invalid_percentages"]
    assert len(invalid_percentages_result.findings) == 2
    by_pct_column = {
        finding.affected_columns[0].original_name: finding
        for finding in invalid_percentages_result.findings
    }
    assert set(by_pct_column) == {"discount_pct", "tax_pct"}
    assert len(by_pct_column["discount_pct"].affected_row_references) == 1
    assert len(by_pct_column["tax_pct"].affected_row_references) == 1
