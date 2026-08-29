"""Tests for the statistical detectors (DET-02 final, WP-019).

Covers this package's acceptance criteria AC-01..AC-14, AC-17, AC-18:
`SuspiciouslyConstantColumnDetector`/`ExtremeOutliersDetector` metadata,
`supports()`, and `run()` positive/negative/boundary/null cases,
`run_detectors()` interoperation (including the `requires_raw_rows ==
False` scoping case), and a real-file end-to-end check against the
committed `demo-data/sales_demo.csv`.
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
from trusttable_backend.detectors.statistical import (
    ExtremeOutliersDetector,
    SuspiciouslyConstantColumnDetector,
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
# AC-01/AC-03/AC-04: SuspiciouslyConstantColumnDetector metadata/supports
# ---------------------------------------------------------------------------


def test_suspiciously_constant_column_metadata() -> None:
    detector = SuspiciouslyConstantColumnDetector()
    assert detector.metadata.detector_id == "statistical.suspiciously_constant_column"
    assert detector.metadata.category is DetectorCategory.STATISTICAL
    assert detector.metadata.requires_raw_rows is False
    assert detector.metadata.requires_confirmed_context is False


def test_suspiciously_constant_column_config_schema_accepts_empty_configuration() -> None:
    detector = SuspiciouslyConstantColumnDetector()
    detector.config_schema.model_validate({})


def test_suspiciously_constant_column_supports_returns_true() -> None:
    detector = SuspiciouslyConstantColumnDetector()
    dataset_profile = make_dataset_profile((), row_count=0)
    request = DetectorSupportRequest(
        dataset_profile=dataset_profile, confirmed_context=None, security_exposure=NO_EXPOSURE
    )
    assert detector.supports(request) is True


# ---------------------------------------------------------------------------
# AC-05..AC-09: SuspiciouslyConstantColumnDetector.run()
# ---------------------------------------------------------------------------


def test_suspiciously_constant_column_run_no_constant_column() -> None:
    detector = SuspiciouslyConstantColumnDetector()
    column = make_column("status", 0)
    dataset_profile = make_dataset_profile(
        (make_column_profile(column, InferredColumnType.CATEGORICAL, distinct_count=3),),
        row_count=5,
    )
    rows: tuple[Mapping[str, object], ...] = ()
    result = detector.run(make_run_request(dataset_profile, rows))

    assert result.status is DetectorRunStatus.SUCCESS
    assert result.findings == ()
    assert result.evidence == ()


def test_suspiciously_constant_column_run_one_finding() -> None:
    detector = SuspiciouslyConstantColumnDetector()
    column = make_column("constant_col", 0)
    dataset_profile = make_dataset_profile(
        (
            make_column_profile(
                column, InferredColumnType.CATEGORICAL, distinct_count=1, null_count=0
            ),
        ),
        row_count=5,
    )
    result = detector.run(make_run_request(dataset_profile, ()))

    assert result.status is DetectorRunStatus.SUCCESS
    assert len(result.findings) == 1
    finding = result.findings[0]
    assert finding.affected_columns == (column,)
    assert finding.affected_row_references == ()
    assert finding.confidence == 1.0
    assert finding.severity is Severity.MEDIUM
    assert len(result.evidence) == 1
    assert result.evidence[0].evidence_type is EvidenceType.METRIC
    assert finding.evidence_ids == (result.evidence[0].evidence_id,)


def test_suspiciously_constant_column_run_boundary_single_non_blank_value() -> None:
    detector = SuspiciouslyConstantColumnDetector()
    column = make_column("notes", 0)
    dataset_profile = make_dataset_profile(
        (make_column_profile(column, InferredColumnType.TEXT, distinct_count=1, null_count=4),),
        row_count=5,
    )
    result = detector.run(make_run_request(dataset_profile, ()))

    assert result.findings == ()
    assert result.evidence == ()


def test_suspiciously_constant_column_run_ignores_unknown_typed_column() -> None:
    detector = SuspiciouslyConstantColumnDetector()
    column = make_column("empty_col", 0)
    # Artificially force distinct_count == 1 to prove the explicit
    # UNKNOWN-type exclusion, not merely an incidental count mismatch.
    dataset_profile = make_dataset_profile(
        (make_column_profile(column, InferredColumnType.UNKNOWN, distinct_count=1, null_count=3),),
        row_count=5,
    )
    result = detector.run(make_run_request(dataset_profile, ()))

    assert result.findings == ()
    assert result.evidence == ()


def test_suspiciously_constant_column_run_applies_to_categorical_type() -> None:
    detector = SuspiciouslyConstantColumnDetector()
    column = make_column("category", 0)
    dataset_profile = make_dataset_profile(
        (
            make_column_profile(
                column, InferredColumnType.CATEGORICAL, distinct_count=1, null_count=0
            ),
        ),
        row_count=3,
    )
    result = detector.run(make_run_request(dataset_profile, ()))

    assert len(result.findings) == 1


# ---------------------------------------------------------------------------
# AC-02/AC-03/AC-04: ExtremeOutliersDetector metadata/supports
# ---------------------------------------------------------------------------


def test_extreme_outliers_metadata() -> None:
    detector = ExtremeOutliersDetector()
    assert detector.metadata.detector_id == "statistical.extreme_outliers"
    assert detector.metadata.category is DetectorCategory.STATISTICAL
    assert detector.metadata.requires_raw_rows is True
    assert detector.metadata.requires_confirmed_context is False
    assert detector.metadata.applicable_inferred_types == (InferredColumnType.NUMERIC,)


def test_extreme_outliers_config_schema_accepts_empty_configuration() -> None:
    detector = ExtremeOutliersDetector()
    detector.config_schema.model_validate({})


def test_extreme_outliers_supports_returns_true() -> None:
    detector = ExtremeOutliersDetector()
    dataset_profile = make_dataset_profile((), row_count=0)
    request = DetectorSupportRequest(
        dataset_profile=dataset_profile, confirmed_context=None, security_exposure=NO_EXPOSURE
    )
    assert detector.supports(request) is True


# ---------------------------------------------------------------------------
# AC-10..AC-14: ExtremeOutliersDetector.run()
# ---------------------------------------------------------------------------


def test_extreme_outliers_run_no_extreme_count() -> None:
    detector = ExtremeOutliersDetector()
    column = make_column("quantity", 0)
    dataset_profile = make_dataset_profile(
        (
            make_column_profile(
                column,
                InferredColumnType.NUMERIC,
                distinct_count=5,
                metrics={"extreme_count": 0, "q1": 5.0, "q3": 15.0, "iqr": 10.0},
            ),
        ),
        row_count=5,
    )
    rows = tuple({"quantity": "10"} for _ in range(5))
    result = detector.run(make_run_request(dataset_profile, rows))

    assert result.status is DetectorRunStatus.SUCCESS
    assert result.findings == ()
    assert result.evidence == ()


def test_extreme_outliers_run_one_finding() -> None:
    detector = ExtremeOutliersDetector()
    column = make_column("quantity", 0)
    dataset_profile = make_dataset_profile(
        (
            make_column_profile(
                column,
                InferredColumnType.NUMERIC,
                distinct_count=2,
                metrics={"extreme_count": 1, "q1": 10.0, "q3": 10.0, "iqr": 0.0},
            ),
        ),
        row_count=5,
    )
    rows = (
        {"quantity": "10"},
        {"quantity": "10"},
        {"quantity": "10"},
        {"quantity": "10"},
        {"quantity": "100"},
    )
    result = detector.run(make_run_request(dataset_profile, rows))

    assert result.status is DetectorRunStatus.SUCCESS
    assert len(result.findings) == 1
    finding = result.findings[0]
    assert finding.affected_columns == (column,)
    assert {ref.row_number for ref in finding.affected_row_references} == {4}
    assert finding.confidence == 0.7
    assert finding.severity is Severity.MEDIUM
    assert len(result.evidence) == 1
    assert result.evidence[0].evidence_type is EvidenceType.ROW_SET
    assert finding.evidence_ids == (result.evidence[0].evidence_id,)


def test_extreme_outliers_run_boundary_at_fence() -> None:
    detector = ExtremeOutliersDetector()
    column = make_column("unit_price", 0)
    # fence = [0 - 1.5*10, 0 + 1.5*10] = [-15, 15]
    dataset_profile = make_dataset_profile(
        (
            make_column_profile(
                column,
                InferredColumnType.NUMERIC,
                distinct_count=2,
                metrics={"extreme_count": 1, "q1": 0.0, "q3": 0.0, "iqr": 10.0},
            ),
        ),
        row_count=2,
    )
    rows = ({"unit_price": "15"}, {"unit_price": "15.01"})
    result = detector.run(make_run_request(dataset_profile, rows))

    assert len(result.findings) == 1
    assert {ref.row_number for ref in result.findings[0].affected_row_references} == {1}


def test_extreme_outliers_run_ignores_non_numeric_column() -> None:
    detector = ExtremeOutliersDetector()
    column = make_column("notes", 0)
    dataset_profile = make_dataset_profile(
        (
            make_column_profile(
                column,
                InferredColumnType.TEXT,
                distinct_count=1,
                metrics={"extreme_count": 1, "q1": 0.0, "q3": 0.0, "iqr": 0.0},
            ),
        ),
        row_count=1,
    )
    rows = ({"notes": "9999"},)
    result = detector.run(make_run_request(dataset_profile, rows))

    assert result.findings == ()
    assert result.evidence == ()


def test_extreme_outliers_run_two_columns_two_findings() -> None:
    detector = ExtremeOutliersDetector()
    column_a = make_column("quantity", 0)
    column_b = make_column("unit_price", 1)
    dataset_profile = make_dataset_profile(
        (
            make_column_profile(
                column_a,
                InferredColumnType.NUMERIC,
                distinct_count=1,
                metrics={"extreme_count": 1, "q1": 10.0, "q3": 10.0, "iqr": 0.0},
            ),
            make_column_profile(
                column_b,
                InferredColumnType.NUMERIC,
                distinct_count=1,
                metrics={"extreme_count": 1, "q1": 100.0, "q3": 100.0, "iqr": 0.0},
            ),
        ),
        row_count=1,
    )
    rows = ({"quantity": "500", "unit_price": "9999.99"},)
    result = detector.run(make_run_request(dataset_profile, rows))

    assert len(result.findings) == 2
    assert {finding.affected_columns[0] for finding in result.findings} == {column_a, column_b}


# ---------------------------------------------------------------------------
# AC-17/AC-18: run_detectors() interoperation and real-file check
# ---------------------------------------------------------------------------


def test_run_detectors_scopes_rows_correctly_for_both_statistical_detectors() -> None:
    constant_column = make_column("constant_col", 0)
    numeric_column = make_column("quantity", 1)
    dataset_profile = make_dataset_profile(
        (
            make_column_profile(
                constant_column, InferredColumnType.CATEGORICAL, distinct_count=1, null_count=0
            ),
            make_column_profile(
                numeric_column,
                InferredColumnType.NUMERIC,
                distinct_count=2,
                metrics={"extreme_count": 1, "q1": 10.0, "q3": 10.0, "iqr": 0.0},
            ),
        ),
        row_count=2,
    )
    rows = (
        {"constant_col": "manual_entry", "quantity": "10"},
        {"constant_col": "manual_entry", "quantity": "500"},
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
    assert by_id["statistical.suspiciously_constant_column"].status is DetectorRunStatus.SUCCESS
    assert len(by_id["statistical.suspiciously_constant_column"].findings) == 1
    assert by_id["statistical.extreme_outliers"].status is DetectorRunStatus.SUCCESS
    assert len(by_id["statistical.extreme_outliers"].findings) == 1


def test_real_demo_csv_statistical_detectors() -> None:
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

    constant_result = by_id["statistical.suspiciously_constant_column"]
    assert len(constant_result.findings) == 1
    assert constant_result.findings[0].affected_columns[0].original_name == "constant_col"

    # `extreme_outliers` fires on `quantity`/`unit_price` (the injected
    # `numeric_outliers` issue, exactly 1 row each) and, as a genuine,
    # independently-verified consequence of applying a fixed 1.5x-IQR
    # Tukey fence to right-skewed distributions (not an implementation
    # defect — disclosed in this package's Provenance and the detector's
    # `documented_limitations`), also on `discount_pct` (the injected
    # `invalid_percentages` issue's 150 value, 1 row) and `line_total`
    # (a multiplicative measure whose natural upper tail crosses its own
    # fence, 10 rows). `tax_pct` does not fire.
    outliers_result = by_id["statistical.extreme_outliers"]
    by_column = {
        finding.affected_columns[0].original_name: finding for finding in outliers_result.findings
    }
    assert {name: len(f.affected_row_references) for name, f in by_column.items()} == {
        "quantity": 1,
        "unit_price": 1,
        "discount_pct": 1,
        "line_total": 10,
    }
