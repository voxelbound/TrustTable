"""Tests for the cross-field detectors (DET-02 partial, WP-018).

Covers this package's acceptance criteria AC-02, AC-03 (partial), AC-04
(partial), AC-10..AC-15, AC-18 (partial), AC-19 (partial):
`LineTotalMismatchDetector` metadata, `supports()`, `run()` positive/
negative/boundary/null/malformed/configuration-override cases,
`run_detectors()` interoperation (including engine-plumbed configuration
overrides), and a real-file end-to-end check against the committed
`demo-data/sales_demo.csv`.
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
from trusttable_backend.detectors.cross_field import LineTotalMismatchDetector
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
    configuration: Mapping[str, object] | None = None,
) -> DetectorRunRequest:
    row_references = tuple(RowReference(row_number=i) for i in range(len(rows)))
    return DetectorRunRequest(
        dataset_profile=dataset_profile,
        rows=rows,
        row_references=row_references,
        confirmed_context=None,
        configuration=(configuration or {}),
        analysis_timestamp=ANALYSIS_TIMESTAMP,
        security_exposure=NO_EXPOSURE,
    )


def standard_columns() -> tuple[ColumnProfile, ...]:
    return (
        make_column_profile(make_column("quantity", 0), InferredColumnType.NUMERIC),
        make_column_profile(make_column("unit_price", 1), InferredColumnType.NUMERIC),
        make_column_profile(make_column("discount_pct", 2), InferredColumnType.NUMERIC),
        make_column_profile(make_column("tax_pct", 3), InferredColumnType.NUMERIC),
        make_column_profile(make_column("line_total", 4), InferredColumnType.NUMERIC),
    )


# ---------------------------------------------------------------------------
# AC-02/AC-03/AC-04: LineTotalMismatchDetector metadata/supports
# ---------------------------------------------------------------------------


def test_line_total_mismatch_metadata() -> None:
    detector = LineTotalMismatchDetector()
    assert detector.metadata.detector_id == "cross_field.line_total_mismatch"
    assert detector.metadata.category is DetectorCategory.CROSS_FIELD
    assert detector.metadata.requires_raw_rows is True
    assert detector.metadata.requires_confirmed_context is False


def test_line_total_mismatch_config_schema_yields_documented_defaults() -> None:
    detector = LineTotalMismatchDetector()
    config = detector.config_schema.model_validate({})
    dumped = config.model_dump()
    assert dumped == {
        "quantity_column": "quantity",
        "unit_price_column": "unit_price",
        "discount_pct_column": "discount_pct",
        "tax_pct_column": "tax_pct",
        "line_total_column": "line_total",
    }


def test_line_total_mismatch_supports_returns_true() -> None:
    detector = LineTotalMismatchDetector()
    dataset_profile = make_dataset_profile((), row_count=0)
    request = DetectorSupportRequest(
        dataset_profile=dataset_profile, confirmed_context=None, security_exposure=NO_EXPOSURE
    )
    assert detector.supports(request) is True


# ---------------------------------------------------------------------------
# AC-10..AC-15: LineTotalMismatchDetector.run()
# ---------------------------------------------------------------------------


def test_line_total_mismatch_run_required_columns_not_found() -> None:
    detector = LineTotalMismatchDetector()
    dataset_profile = make_dataset_profile(
        (make_column_profile(make_column("quantity", 0), InferredColumnType.NUMERIC),),
        row_count=1,
    )
    rows = ({"quantity": "5"},)
    result = detector.run(make_run_request(dataset_profile, rows))

    assert result.status is DetectorRunStatus.SUCCESS
    assert result.findings == ()
    assert result.evidence == ()
    assert len(result.warnings) == 1
    assert result.warnings[0].code == "cross_field.required_columns_not_found"


def test_line_total_mismatch_run_no_mismatch() -> None:
    detector = LineTotalMismatchDetector()
    dataset_profile = make_dataset_profile(standard_columns(), row_count=1)
    rows = (
        {
            "quantity": "5",
            "unit_price": "192.31",
            "discount_pct": "18",
            "tax_pct": "4",
            "line_total": "820.01",
        },
    )
    result = detector.run(make_run_request(dataset_profile, rows))

    assert result.status is DetectorRunStatus.SUCCESS
    assert result.findings == ()
    assert result.evidence == ()


def test_line_total_mismatch_run_one_finding_two_rows() -> None:
    detector = LineTotalMismatchDetector()
    dataset_profile = make_dataset_profile(standard_columns(), row_count=3)
    rows = (
        {
            "quantity": "5",
            "unit_price": "192.31",
            "discount_pct": "18",
            "tax_pct": "4",
            "line_total": "820.01",
        },
        {
            "quantity": "5",
            "unit_price": "192.31",
            "discount_pct": "18",
            "tax_pct": "4",
            "line_total": "920.01",
        },
        {
            "quantity": "5",
            "unit_price": "344.50",
            "discount_pct": "26",
            "tax_pct": "8",
            "line_total": "1476.62",
        },
    )
    result = detector.run(make_run_request(dataset_profile, rows))

    assert result.status is DetectorRunStatus.SUCCESS
    assert len(result.findings) == 1
    finding = result.findings[0]
    assert {ref.row_number for ref in finding.affected_row_references} == {1, 2}
    assert len(finding.affected_columns) == 5
    assert finding.confidence == 1.0
    assert finding.severity is Severity.HIGH
    assert len(result.evidence) == 1
    assert result.evidence[0].evidence_type is EvidenceType.CROSS_FIELD_COMPARISON
    assert finding.evidence_ids == (result.evidence[0].evidence_id,)


def test_line_total_mismatch_run_boundary_tolerance() -> None:
    detector = LineTotalMismatchDetector()
    dataset_profile = make_dataset_profile(standard_columns(), row_count=2)
    # expected = 1 * 100 * (1 - 0/100) * (1 + 0/100) = 100.00 exactly for both rows.
    rows = (
        # diff == 0.01 (exactly at tolerance): not a mismatch.
        {
            "quantity": "1",
            "unit_price": "100",
            "discount_pct": "0",
            "tax_pct": "0",
            "line_total": "100.01",
        },
        # diff == 0.02 (exceeds tolerance): a mismatch.
        {
            "quantity": "1",
            "unit_price": "100",
            "discount_pct": "0",
            "tax_pct": "0",
            "line_total": "100.02",
        },
    )
    result = detector.run(make_run_request(dataset_profile, rows))

    assert len(result.findings) == 1
    assert {ref.row_number for ref in result.findings[0].affected_row_references} == {1}


def test_line_total_mismatch_run_skips_blank_values() -> None:
    detector = LineTotalMismatchDetector()
    dataset_profile = make_dataset_profile(standard_columns(), row_count=1)
    rows = (
        {
            "quantity": "",
            "unit_price": "192.31",
            "discount_pct": "18",
            "tax_pct": "4",
            "line_total": "",
        },
    )
    result = detector.run(make_run_request(dataset_profile, rows))

    assert result.findings == ()
    assert result.evidence == ()


def test_line_total_mismatch_run_configuration_override() -> None:
    detector = LineTotalMismatchDetector()
    dataset_profile = make_dataset_profile(
        (
            make_column_profile(make_column("qty", 0), InferredColumnType.NUMERIC),
            make_column_profile(make_column("price", 1), InferredColumnType.NUMERIC),
            make_column_profile(make_column("disc_pct", 2), InferredColumnType.NUMERIC),
            make_column_profile(make_column("tax", 3), InferredColumnType.NUMERIC),
            make_column_profile(make_column("total", 4), InferredColumnType.NUMERIC),
        ),
        row_count=1,
    )
    rows = ({"qty": "5", "price": "192.31", "disc_pct": "18", "tax": "4", "total": "920.01"},)
    configuration = {
        "quantity_column": "qty",
        "unit_price_column": "price",
        "discount_pct_column": "disc_pct",
        "tax_pct_column": "tax",
        "line_total_column": "total",
    }
    result = detector.run(make_run_request(dataset_profile, rows, configuration=configuration))

    assert len(result.findings) == 1
    assert {ref.row_number for ref in result.findings[0].affected_row_references} == {0}


# ---------------------------------------------------------------------------
# AC-18: run_detectors() interoperation, including configuration overrides
# ---------------------------------------------------------------------------


def test_run_detectors_applies_configuration_overrides_for_line_total_mismatch() -> None:
    dataset_profile = make_dataset_profile(
        (
            make_column_profile(make_column("qty", 0), InferredColumnType.NUMERIC),
            make_column_profile(make_column("price", 1), InferredColumnType.NUMERIC),
            make_column_profile(make_column("disc_pct", 2), InferredColumnType.NUMERIC),
            make_column_profile(make_column("tax", 3), InferredColumnType.NUMERIC),
            make_column_profile(make_column("total", 4), InferredColumnType.NUMERIC),
        ),
        row_count=1,
    )
    rows = ({"qty": "5", "price": "192.31", "disc_pct": "18", "tax": "4", "total": "920.01"},)
    row_references = (RowReference(row_number=0),)

    results = run_detectors(
        list(DETECTORS),
        dataset_profile=dataset_profile,
        rows=rows,
        row_references=row_references,
        confirmed_context=None,
        security_exposure=NO_EXPOSURE,
        analysis_timestamp=ANALYSIS_TIMESTAMP,
        configuration_overrides={
            "cross_field.line_total_mismatch": {
                "quantity_column": "qty",
                "unit_price_column": "price",
                "discount_pct_column": "disc_pct",
                "tax_pct_column": "tax",
                "line_total_column": "total",
            }
        },
    )

    by_id = {r.detector_id: r for r in results}
    result = by_id["cross_field.line_total_mismatch"]
    assert result.status is DetectorRunStatus.SUCCESS
    assert len(result.findings) == 1


# ---------------------------------------------------------------------------
# AC-19: real-file end-to-end check
# ---------------------------------------------------------------------------


def test_real_demo_csv_line_total_mismatch() -> None:
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

    result = by_id["cross_field.line_total_mismatch"]
    assert result.status is DetectorRunStatus.SUCCESS
    assert len(result.findings) == 1
    finding = result.findings[0]
    assert len(finding.affected_row_references) == 2
    assert finding.severity is Severity.HIGH
    assert finding.confidence == 1.0
