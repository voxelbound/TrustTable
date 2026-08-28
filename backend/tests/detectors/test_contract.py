"""Tests for the detector contract types (DET-01).

Covers this package's acceptance criteria AC-01..AC-13: `DetectorCategory`/
`PerformanceClass`'s closed enumerations, `DetectorMetadata`/
`SecurityExposureState`/`DetectorSupportRequest`/`DetectorRunRequest`/
`FindingCandidate`/`DetectorWarning`/`ExecutionMetrics`/`SafeFailure`/
`DetectorRunResult` positive, negative, and boundary cases.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from trusttable_backend.detectors.contract import (
    DetectorCategory,
    DetectorMetadata,
    DetectorRunRequest,
    DetectorRunResult,
    DetectorRunStatus,
    DetectorSupportRequest,
    DetectorWarning,
    ExecutionMetrics,
    FindingCandidate,
    PerformanceClass,
    SafeFailure,
    SecurityExposureState,
)
from trusttable_backend.domain.evidence import Evidence, EvidenceType
from trusttable_backend.domain.parsing import SampleMetadata, SamplingScope
from trusttable_backend.domain.value_objects import ColumnReference, RowReference, Severity
from trusttable_backend.profiling.schemas import (
    ColumnProfile,
    DatasetProfile,
    InferredColumnType,
    ProfilingTiming,
)

ANALYSIS_TIMESTAMP = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)


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


def make_dataset_profile(**overrides: object) -> DatasetProfile:
    fields: dict[str, object] = {
        "schema_version": "1",
        "dataset_metrics": {"row_count": 10},
        "column_profiles": (make_column_profile(),),
        "sampling": SampleMetadata(scope=SamplingScope.FULL, population_size=10, sample_size=10),
        "warnings": (),
        "timing": ProfilingTiming(
            started_at=ANALYSIS_TIMESTAMP, completed_at=ANALYSIS_TIMESTAMP, duration_ms=10
        ),
    }
    fields.update(overrides)
    return DatasetProfile(**fields)  # type: ignore[arg-type]


def make_metadata(**overrides: object) -> DetectorMetadata:
    fields: dict[str, object] = {
        "detector_id": "structural.exact_duplicate_rows",
        "version": "1",
        "name": "Exact duplicate rows",
        "category": DetectorCategory.STRUCTURAL,
        "description": "Flags rows that are byte-identical to another row.",
        "applicable_inferred_types": (),
        "required_profile_fields": ("dataset_metrics.duplicate_row_count",),
        "requires_raw_rows": False,
        "requires_confirmed_context": False,
        "default_configuration": {},
        "performance_class": PerformanceClass.LINEAR_BY_ROW,
        "documented_limitations": (),
    }
    fields.update(overrides)
    return DetectorMetadata(**fields)  # type: ignore[arg-type]


def make_exposure(**overrides: object) -> SecurityExposureState:
    fields: dict[str, object] = {
        "model_provider_enabled": False,
        "sample_transmission_enabled": False,
    }
    fields.update(overrides)
    return SecurityExposureState(**fields)  # type: ignore[arg-type]


def make_evidence(**overrides: object) -> Evidence:
    fields: dict[str, object] = {
        "evidence_id": "ev-1",
        "evidence_type": EvidenceType.ROW_SET,
        "calculation_version": "1",
        "structured_payload": {"row_count": 2},
        "affected_columns": (),
        "affected_row_references": (),
        "scope": SamplingScope.FULL,
        "display_safe_summary": "2 duplicate rows found",
    }
    fields.update(overrides)
    return Evidence(**fields)  # type: ignore[arg-type]


def make_finding(**overrides: object) -> FindingCandidate:
    fields: dict[str, object] = {
        "detector_id": "structural.exact_duplicate_rows",
        "detector_version": "1",
        "category": DetectorCategory.STRUCTURAL,
        "severity": Severity.MEDIUM,
        "confidence": 1.0,
        "calculated_observation": "2 rows are exact duplicates",
        "affected_columns": (),
        "affected_row_references": (),
        "evidence_ids": ("ev-1",),
        "default_remediation_template_key": None,
        "default_validation_rule_template_key": None,
    }
    fields.update(overrides)
    return FindingCandidate(**fields)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# AC-01: DetectorCategory
# ---------------------------------------------------------------------------


def test_detector_category_is_a_closed_enumeration() -> None:
    assert {member.value for member in DetectorCategory} == {
        "structural",
        "completeness",
        "consistency",
        "validity",
        "statistical",
        "cross_field",
        "ai_processing_security",
    }


# ---------------------------------------------------------------------------
# AC-02: PerformanceClass
# ---------------------------------------------------------------------------


def test_performance_class_is_a_closed_enumeration() -> None:
    assert {member.value for member in PerformanceClass} == {
        "constant_or_metadata_only",
        "linear_by_row",
        "linear_by_value_length",
        "grouped_aggregation",
        "pairwise_candidate",
        "sampled_expensive",
    }


# ---------------------------------------------------------------------------
# AC-04: DetectorMetadata
# ---------------------------------------------------------------------------


def test_detector_metadata_constructs_with_valid_fields() -> None:
    metadata = make_metadata()

    assert metadata.detector_id == "structural.exact_duplicate_rows"
    assert metadata.category is DetectorCategory.STRUCTURAL
    assert metadata.performance_class is PerformanceClass.LINEAR_BY_ROW


def test_detector_metadata_is_immutable() -> None:
    metadata = make_metadata()

    with pytest.raises(AttributeError):
        metadata.version = "2"  # type: ignore[misc]


def test_detector_metadata_rejects_empty_detector_id() -> None:
    with pytest.raises(ValueError, match="detector_id"):
        make_metadata(detector_id="")


def test_detector_metadata_rejects_non_namespaced_detector_id() -> None:
    with pytest.raises(ValueError, match="namespaced"):
        make_metadata(detector_id="exactduplicaterows")


def test_detector_metadata_rejects_empty_version() -> None:
    with pytest.raises(ValueError, match="version"):
        make_metadata(version="")


def test_detector_metadata_rejects_empty_name() -> None:
    with pytest.raises(ValueError, match="name"):
        make_metadata(name="")


def test_detector_metadata_rejects_empty_description() -> None:
    with pytest.raises(ValueError, match="description"):
        make_metadata(description="")


def test_detector_metadata_rejects_empty_required_profile_field_entry() -> None:
    with pytest.raises(ValueError, match="required_profile_fields"):
        make_metadata(required_profile_fields=("",))


def test_detector_metadata_accepts_empty_applicable_inferred_types_for_dataset_level_detector() -> (
    None
):
    metadata = make_metadata(applicable_inferred_types=())
    assert metadata.applicable_inferred_types == ()


# ---------------------------------------------------------------------------
# AC-05: SecurityExposureState
# ---------------------------------------------------------------------------


def test_security_exposure_state_constructs_with_valid_fields() -> None:
    exposure = make_exposure(model_provider_enabled=True, sample_transmission_enabled=True)

    assert exposure.model_provider_enabled is True
    assert exposure.sample_transmission_enabled is True


def test_security_exposure_state_rejects_sample_transmission_without_model_provider() -> None:
    with pytest.raises(ValueError, match="model_provider_enabled"):
        make_exposure(model_provider_enabled=False, sample_transmission_enabled=True)


def test_security_exposure_state_allows_model_provider_without_sample_transmission() -> None:
    exposure = make_exposure(model_provider_enabled=True, sample_transmission_enabled=False)
    assert exposure.sample_transmission_enabled is False


# ---------------------------------------------------------------------------
# AC-06/AC-07: DetectorSupportRequest, DetectorRunRequest
# ---------------------------------------------------------------------------


def test_detector_support_request_constructs_with_documented_fields() -> None:
    request = DetectorSupportRequest(
        dataset_profile=make_dataset_profile(),
        confirmed_context=None,
        security_exposure=make_exposure(),
    )

    assert request.confirmed_context is None


def test_detector_run_request_constructs_with_documented_fields() -> None:
    row_ref = RowReference(row_number=0)
    request = DetectorRunRequest(
        dataset_profile=make_dataset_profile(),
        rows=({"qty": 1},),
        row_references=(row_ref,),
        confirmed_context=None,
        configuration={},
        analysis_timestamp=ANALYSIS_TIMESTAMP,
        security_exposure=make_exposure(),
    )

    assert request.rows == ({"qty": 1},)
    assert request.row_references == (row_ref,)
    assert request.analysis_timestamp == ANALYSIS_TIMESTAMP


def test_detector_run_request_rejects_rows_row_references_length_mismatch() -> None:
    with pytest.raises(ValueError, match="rows and row_references"):
        DetectorRunRequest(
            dataset_profile=make_dataset_profile(),
            rows=({"qty": 1}, {"qty": 2}),
            row_references=(RowReference(row_number=0),),
            confirmed_context=None,
            configuration={},
            analysis_timestamp=ANALYSIS_TIMESTAMP,
            security_exposure=make_exposure(),
        )


def test_detector_run_request_accepts_empty_rows_boundary() -> None:
    request = DetectorRunRequest(
        dataset_profile=make_dataset_profile(),
        rows=(),
        row_references=(),
        confirmed_context=None,
        configuration={},
        analysis_timestamp=ANALYSIS_TIMESTAMP,
        security_exposure=make_exposure(),
    )
    assert request.rows == ()


# ---------------------------------------------------------------------------
# AC-08: FindingCandidate
# ---------------------------------------------------------------------------


def test_finding_candidate_constructs_with_valid_fields() -> None:
    finding = make_finding()

    assert finding.severity is Severity.MEDIUM
    assert finding.confidence == 1.0
    assert finding.evidence_ids == ("ev-1",)


def test_finding_candidate_rejects_confidence_above_one() -> None:
    with pytest.raises(ValueError, match="confidence"):
        make_finding(confidence=1.1)


def test_finding_candidate_rejects_confidence_below_zero() -> None:
    with pytest.raises(ValueError, match="confidence"):
        make_finding(confidence=-0.1)


def test_finding_candidate_accepts_confidence_boundary_values() -> None:
    assert make_finding(confidence=0.0).confidence == 0.0
    assert make_finding(confidence=1.0).confidence == 1.0


def test_finding_candidate_rejects_empty_calculated_observation() -> None:
    with pytest.raises(ValueError, match="calculated_observation"):
        make_finding(calculated_observation="")


def test_finding_candidate_rejects_empty_evidence_ids() -> None:
    with pytest.raises(ValueError, match="evidence_ids"):
        make_finding(evidence_ids=())


# ---------------------------------------------------------------------------
# AC-09: DetectorWarning
# ---------------------------------------------------------------------------


def test_detector_warning_constructs_with_required_fields_only() -> None:
    warning = DetectorWarning(code="detector.skipped_not_applicable", message="not applicable")
    assert warning.column is None


def test_detector_warning_constructs_with_optional_column() -> None:
    column = ColumnReference(original_name="Qty", internal_key="qty", ordinal=0)
    warning = DetectorWarning(code="detector.skipped_not_applicable", message="x", column=column)
    assert warning.column == column


def test_detector_warning_rejects_empty_message() -> None:
    with pytest.raises(ValueError, match="message"):
        DetectorWarning(code="detector.skipped_not_applicable", message="")


def test_detector_warning_rejects_non_namespaced_code() -> None:
    with pytest.raises(ValueError, match="namespaced"):
        DetectorWarning(code="skipped", message="x")


# ---------------------------------------------------------------------------
# AC-10: ExecutionMetrics
# ---------------------------------------------------------------------------


def test_execution_metrics_rejects_negative_duration() -> None:
    with pytest.raises(ValueError, match="duration_ms"):
        ExecutionMetrics(duration_ms=-1)


def test_execution_metrics_accepts_zero_duration_boundary() -> None:
    assert ExecutionMetrics(duration_ms=0).duration_ms == 0


# ---------------------------------------------------------------------------
# AC-11: SafeFailure
# ---------------------------------------------------------------------------


def test_safe_failure_rejects_empty_error_type() -> None:
    with pytest.raises(ValueError, match="error_type"):
        SafeFailure(error_type="", safe_message="x")


def test_safe_failure_rejects_empty_safe_message() -> None:
    with pytest.raises(ValueError, match="safe_message"):
        SafeFailure(error_type="ValueError", safe_message="")


# ---------------------------------------------------------------------------
# AC-12/AC-13: DetectorRunResult
# ---------------------------------------------------------------------------


def test_detector_run_result_success_constructs_with_no_safe_failure() -> None:
    result = DetectorRunResult(
        detector_id="structural.exact_duplicate_rows",
        detector_version="1",
        status=DetectorRunStatus.SUCCESS,
        findings=(make_finding(),),
        evidence=(make_evidence(),),
        warnings=(),
        execution_metrics=ExecutionMetrics(duration_ms=5),
    )
    assert result.safe_failure is None
    assert result.findings[0].evidence_ids == ("ev-1",)


def test_detector_run_result_failed_requires_safe_failure() -> None:
    with pytest.raises(ValueError, match="safe_failure"):
        DetectorRunResult(
            detector_id="structural.exact_duplicate_rows",
            detector_version="1",
            status=DetectorRunStatus.FAILED,
            findings=(),
            evidence=(),
            warnings=(),
            execution_metrics=ExecutionMetrics(duration_ms=5),
            safe_failure=None,
        )


def test_detector_run_result_failed_rejects_nonempty_findings() -> None:
    with pytest.raises(ValueError, match="findings and evidence"):
        DetectorRunResult(
            detector_id="structural.exact_duplicate_rows",
            detector_version="1",
            status=DetectorRunStatus.FAILED,
            findings=(make_finding(),),
            evidence=(make_evidence(),),
            warnings=(),
            execution_metrics=ExecutionMetrics(duration_ms=5),
            safe_failure=SafeFailure(error_type="ValueError", safe_message="x"),
        )


def test_detector_run_result_success_rejects_safe_failure_set() -> None:
    with pytest.raises(ValueError, match="safe_failure"):
        DetectorRunResult(
            detector_id="structural.exact_duplicate_rows",
            detector_version="1",
            status=DetectorRunStatus.SUCCESS,
            findings=(),
            evidence=(),
            warnings=(),
            execution_metrics=ExecutionMetrics(duration_ms=5),
            safe_failure=SafeFailure(error_type="ValueError", safe_message="x"),
        )


def test_detector_run_result_rejects_finding_evidence_id_not_in_result() -> None:
    with pytest.raises(ValueError, match="evidence_id"):
        DetectorRunResult(
            detector_id="structural.exact_duplicate_rows",
            detector_version="1",
            status=DetectorRunStatus.SUCCESS,
            findings=(make_finding(evidence_ids=("missing-ev",)),),
            evidence=(make_evidence(),),
            warnings=(),
            execution_metrics=ExecutionMetrics(duration_ms=5),
        )


def test_detector_run_result_skipped_accepts_empty_findings_and_evidence() -> None:
    result = DetectorRunResult(
        detector_id="structural.exact_duplicate_rows",
        detector_version="1",
        status=DetectorRunStatus.SKIPPED,
        findings=(),
        evidence=(),
        warnings=(DetectorWarning(code="detector.skipped_not_applicable", message="x"),),
        execution_metrics=ExecutionMetrics(duration_ms=0),
    )
    assert result.status is DetectorRunStatus.SKIPPED
