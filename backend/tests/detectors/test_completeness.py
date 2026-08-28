"""Tests for the completeness detectors (DET-02 partial, WP-015).

Covers this package's acceptance criteria AC-01..AC-13, AC-16, AC-17:
`ExcessiveMissingValuesDetector`/`MissingLikelyIdentifierDetector`
metadata, `supports()`, and `run()` positive/negative/boundary/null
cases, `run_detectors()` interoperation, and a real-file end-to-end check
against the committed `demo-data/sales_demo.csv`.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, date, datetime
from pathlib import Path

from trusttable_backend.detectors.catalogue import DETECTORS
from trusttable_backend.detectors.completeness import (
    ExcessiveMissingValuesDetector,
    MissingLikelyIdentifierDetector,
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


def make_rows(
    column_name: str, row_count: int, missing_indices: set[int]
) -> tuple[Mapping[str, object], ...]:
    return tuple(
        {column_name: (None if i in missing_indices else "value")} for i in range(row_count)
    )


# ---------------------------------------------------------------------------
# AC-01/AC-03/AC-04: ExcessiveMissingValuesDetector metadata/supports
# ---------------------------------------------------------------------------


def test_excessive_missing_values_metadata() -> None:
    detector = ExcessiveMissingValuesDetector()
    assert detector.metadata.detector_id == "completeness.excessive_missing_values"
    assert detector.metadata.category is DetectorCategory.COMPLETENESS
    assert detector.metadata.requires_raw_rows is True
    assert detector.metadata.requires_confirmed_context is False


def test_excessive_missing_values_config_schema_accepts_empty_configuration() -> None:
    detector = ExcessiveMissingValuesDetector()
    detector.config_schema.model_validate({})


def test_excessive_missing_values_supports_returns_true() -> None:
    detector = ExcessiveMissingValuesDetector()
    dataset_profile = make_dataset_profile((), row_count=0)
    request = DetectorSupportRequest(
        dataset_profile=dataset_profile, confirmed_context=None, security_exposure=NO_EXPOSURE
    )
    assert detector.supports(request) is True


# ---------------------------------------------------------------------------
# AC-05..AC-09: ExcessiveMissingValuesDetector.run()
# ---------------------------------------------------------------------------


def test_excessive_missing_values_run_no_column_reaches_threshold() -> None:
    detector = ExcessiveMissingValuesDetector()
    column = make_column("qty", 0)
    dataset_profile = make_dataset_profile(
        (
            make_column_profile(
                column, InferredColumnType.NUMERIC, null_count=0, distinct_count=100
            ),
        ),
        row_count=100,
    )
    rows = make_rows("qty", 100, set())
    result = detector.run(make_run_request(dataset_profile, rows))

    assert result.status is DetectorRunStatus.SUCCESS
    assert result.findings == ()
    assert result.evidence == ()


def test_excessive_missing_values_run_one_column_above_threshold() -> None:
    detector = ExcessiveMissingValuesDetector()
    column = make_column("qty", 0)
    missing_indices = {10, 20, 30, 40, 50}
    dataset_profile = make_dataset_profile(
        (
            make_column_profile(
                column,
                InferredColumnType.NUMERIC,
                null_count=len(missing_indices),
                distinct_count=95,
            ),
        ),
        row_count=100,
    )
    rows = make_rows("qty", 100, missing_indices)
    result = detector.run(make_run_request(dataset_profile, rows))

    assert result.status is DetectorRunStatus.SUCCESS
    assert len(result.findings) == 1
    finding = result.findings[0]
    assert finding.affected_columns == (column,)
    assert {ref.row_number for ref in finding.affected_row_references} == missing_indices
    assert finding.confidence == 1.0
    assert finding.severity is Severity.MEDIUM
    assert len(result.evidence) == 1
    assert result.evidence[0].evidence_type is EvidenceType.ROW_SET
    assert finding.evidence_ids == (result.evidence[0].evidence_id,)


def test_excessive_missing_values_run_boundary_at_and_below_threshold() -> None:
    detector = ExcessiveMissingValuesDetector()
    column_at = make_column("col_at", 0)
    column_below = make_column("col_below", 1)
    dataset_profile = make_dataset_profile(
        (
            make_column_profile(
                column_at, InferredColumnType.NUMERIC, null_count=10, distinct_count=990
            ),
            make_column_profile(
                column_below, InferredColumnType.NUMERIC, null_count=9, distinct_count=991
            ),
        ),
        row_count=1000,
    )
    rows = tuple(
        {
            "col_at": (None if i < 10 else "value"),
            "col_below": (None if i < 9 else "value"),
        }
        for i in range(1000)
    )
    result = detector.run(make_run_request(dataset_profile, rows))

    fired_columns = {finding.affected_columns[0] for finding in result.findings}
    assert fired_columns == {column_at}


def test_excessive_missing_values_run_excludes_fully_empty_unknown_column() -> None:
    detector = ExcessiveMissingValuesDetector()
    column = make_column("empty_col", 0)
    dataset_profile = make_dataset_profile(
        (make_column_profile(column, InferredColumnType.UNKNOWN, null_count=10, distinct_count=0),),
        row_count=10,
    )
    rows = make_rows("empty_col", 10, set(range(10)))
    result = detector.run(make_run_request(dataset_profile, rows))

    assert result.findings == ()
    assert result.evidence == ()


def test_excessive_missing_values_run_treats_none_and_empty_string_identically() -> None:
    detector = ExcessiveMissingValuesDetector()
    column = make_column("qty", 0)
    dataset_profile = make_dataset_profile(
        (make_column_profile(column, InferredColumnType.NUMERIC, null_count=2, distinct_count=8),),
        row_count=10,
    )
    rows = tuple({"qty": {0: None, 1: ""}.get(i, "value")} for i in range(10))
    result = detector.run(make_run_request(dataset_profile, rows))

    assert len(result.findings) == 1
    assert {ref.row_number for ref in result.findings[0].affected_row_references} == {0, 1}


# ---------------------------------------------------------------------------
# AC-02/AC-03/AC-04: MissingLikelyIdentifierDetector metadata/supports
# ---------------------------------------------------------------------------


def test_missing_likely_identifier_metadata() -> None:
    detector = MissingLikelyIdentifierDetector()
    assert detector.metadata.detector_id == "completeness.missing_likely_identifier"
    assert detector.metadata.category is DetectorCategory.COMPLETENESS
    assert detector.metadata.requires_raw_rows is True
    assert detector.metadata.requires_confirmed_context is False


def test_missing_likely_identifier_config_schema_accepts_empty_configuration() -> None:
    detector = MissingLikelyIdentifierDetector()
    detector.config_schema.model_validate({})


def test_missing_likely_identifier_supports_returns_true() -> None:
    detector = MissingLikelyIdentifierDetector()
    dataset_profile = make_dataset_profile((), row_count=0)
    request = DetectorSupportRequest(
        dataset_profile=dataset_profile, confirmed_context=None, security_exposure=NO_EXPOSURE
    )
    assert detector.supports(request) is True


# ---------------------------------------------------------------------------
# AC-10..AC-13: MissingLikelyIdentifierDetector.run()
# ---------------------------------------------------------------------------


def test_missing_likely_identifier_run_no_likely_identifier_column() -> None:
    detector = MissingLikelyIdentifierDetector()
    column = make_column("category", 0)
    dataset_profile = make_dataset_profile(
        (
            make_column_profile(
                column,
                InferredColumnType.CATEGORICAL,
                null_count=3,
                distinct_count=2,
                metrics={"likely_identifier": False},
            ),
        ),
        row_count=10,
    )
    rows = make_rows("category", 10, {0, 1, 2})
    result = detector.run(make_run_request(dataset_profile, rows))

    assert result.status is DetectorRunStatus.SUCCESS
    assert result.findings == ()
    assert result.evidence == ()


def test_missing_likely_identifier_run_no_missing_values() -> None:
    detector = MissingLikelyIdentifierDetector()
    column = make_column("order_id", 0)
    dataset_profile = make_dataset_profile(
        (
            make_column_profile(
                column,
                InferredColumnType.TEXT,
                null_count=0,
                distinct_count=10,
                metrics={"likely_identifier": True},
            ),
        ),
        row_count=10,
    )
    rows = make_rows("order_id", 10, set())
    result = detector.run(make_run_request(dataset_profile, rows))

    assert result.findings == ()
    assert result.evidence == ()


def test_missing_likely_identifier_run_one_finding() -> None:
    detector = MissingLikelyIdentifierDetector()
    column = make_column("order_id", 0)
    missing_indices = {3, 7}
    dataset_profile = make_dataset_profile(
        (
            make_column_profile(
                column,
                InferredColumnType.TEXT,
                null_count=len(missing_indices),
                distinct_count=8,
                metrics={"likely_identifier": True},
            ),
        ),
        row_count=10,
    )
    rows = make_rows("order_id", 10, missing_indices)
    result = detector.run(make_run_request(dataset_profile, rows))

    assert result.status is DetectorRunStatus.SUCCESS
    assert len(result.findings) == 1
    finding = result.findings[0]
    assert finding.affected_columns == (column,)
    assert {ref.row_number for ref in finding.affected_row_references} == missing_indices
    assert finding.confidence == 1.0
    assert finding.severity is Severity.HIGH
    assert len(result.evidence) == 1
    assert result.evidence[0].evidence_type is EvidenceType.ROW_SET
    assert finding.evidence_ids == (result.evidence[0].evidence_id,)


def test_missing_likely_identifier_run_two_columns_two_findings() -> None:
    detector = MissingLikelyIdentifierDetector()
    column_a = make_column("order_id", 0)
    column_b = make_column("invoice_id", 1)
    dataset_profile = make_dataset_profile(
        (
            make_column_profile(
                column_a,
                InferredColumnType.TEXT,
                null_count=1,
                distinct_count=9,
                metrics={"likely_identifier": True},
            ),
            make_column_profile(
                column_b,
                InferredColumnType.TEXT,
                null_count=1,
                distinct_count=9,
                metrics={"likely_identifier": True},
            ),
        ),
        row_count=10,
    )
    rows = tuple(
        {
            "order_id": (None if i == 0 else "value"),
            "invoice_id": (None if i == 5 else "value"),
        }
        for i in range(10)
    )
    result = detector.run(make_run_request(dataset_profile, rows))

    assert len(result.findings) == 2
    assert {finding.affected_columns[0] for finding in result.findings} == {column_a, column_b}


# ---------------------------------------------------------------------------
# AC-16/AC-17: run_detectors() interoperation and real-file check
# ---------------------------------------------------------------------------


def test_run_detectors_scopes_rows_correctly_for_both_completeness_detectors() -> None:
    # row_count=200 keeps `order_id`'s single missing row (0.5%) below the
    # excessive_missing_values threshold (1%) while `qty`'s 2/200 (1.0%)
    # reaches it — isolating each detector's firing to its own condition.
    row_count = 200
    qty_column = make_column("qty", 0)
    id_column = make_column("order_id", 1)
    dataset_profile = make_dataset_profile(
        (
            make_column_profile(
                qty_column, InferredColumnType.NUMERIC, null_count=2, distinct_count=198
            ),
            make_column_profile(
                id_column,
                InferredColumnType.TEXT,
                null_count=1,
                distinct_count=199,
                metrics={"likely_identifier": True},
            ),
        ),
        row_count=row_count,
    )
    rows = tuple(
        {
            "qty": (None if i in {0, 1} else "value"),
            "order_id": (None if i == 5 else f"id-{i}"),
        }
        for i in range(row_count)
    )
    row_references = tuple(RowReference(row_number=i) for i in range(row_count))

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
    assert by_id["completeness.excessive_missing_values"].status is DetectorRunStatus.SUCCESS
    assert len(by_id["completeness.excessive_missing_values"].findings) == 1
    assert by_id["completeness.missing_likely_identifier"].status is DetectorRunStatus.SUCCESS
    assert len(by_id["completeness.missing_likely_identifier"].findings) == 1


def test_real_demo_csv_completeness_detectors() -> None:
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

    # `notes` is blank ("") in every row except the one DEMO-01
    # prompt-injection row (299/300 = 99.7% missing) — a genuine,
    # correctly-detected excessive-missing-values condition discovered
    # during implementation, not an injected DET-02 issue type.
    missing_values_result = by_id["completeness.excessive_missing_values"]
    assert len(missing_values_result.findings) == 3
    by_column = {
        finding.affected_columns[0].original_name: finding
        for finding in missing_values_result.findings
    }
    assert set(by_column) == {"quantity", "line_total", "notes"}
    assert len(by_column["quantity"].affected_row_references) == 3
    assert len(by_column["line_total"].affected_row_references) == 3
    assert len(by_column["notes"].affected_row_references) == 299

    missing_identifier_result = by_id["completeness.missing_likely_identifier"]
    assert len(missing_identifier_result.findings) == 1
    finding = missing_identifier_result.findings[0]
    assert finding.affected_columns[0].original_name == "order_id"
    assert len(finding.affected_row_references) == 1
