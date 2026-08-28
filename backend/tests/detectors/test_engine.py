"""Tests for the detector execution engine (DET-01).

Covers this package's acceptance criteria AC-17..AC-21: `run_detectors()`
skips unsupported detectors without calling `run()`, isolates
`supports()`/`run()` exceptions and continues with subsequent detectors,
withholds undeclared inputs (raw rows, confirmed context), records
real engine-measured timing (overriding whatever a detector itself
returns), and preserves deterministic input order.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime

import pytest
from pydantic import BaseModel

from trusttable_backend.detectors.contract import (
    DetectorCategory,
    DetectorMetadata,
    DetectorRunRequest,
    DetectorRunResult,
    DetectorRunStatus,
    DetectorSupportRequest,
    ExecutionMetrics,
    FindingCandidate,
    PerformanceClass,
    SecurityExposureState,
)
from trusttable_backend.detectors.engine import run_detectors
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


class _EmptyConfig(BaseModel):
    pass


class _ThresholdConfig(BaseModel):
    threshold: float


def make_dataset_profile() -> DatasetProfile:
    column = ColumnReference(original_name="Qty", internal_key="qty", ordinal=0)
    column_profile = ColumnProfile(
        column=column,
        inferred_type=InferredColumnType.NUMERIC,
        null_count=0,
        distinct_count=2,
        metrics={},
        warnings=(),
    )
    return DatasetProfile(
        schema_version="1",
        dataset_metrics={"row_count": 2},
        column_profiles=(column_profile,),
        sampling=SampleMetadata(scope=SamplingScope.FULL, population_size=2, sample_size=2),
        warnings=(),
        timing=ProfilingTiming(
            started_at=ANALYSIS_TIMESTAMP, completed_at=ANALYSIS_TIMESTAMP, duration_ms=1
        ),
    )


def make_metadata(**overrides: object) -> DetectorMetadata:
    fields: dict[str, object] = {
        "detector_id": "structural.stub",
        "version": "1",
        "name": "Stub detector",
        "category": DetectorCategory.STRUCTURAL,
        "description": "A scripted test double.",
        "applicable_inferred_types": (),
        "required_profile_fields": (),
        "requires_raw_rows": False,
        "requires_confirmed_context": False,
        "default_configuration": {},
        "performance_class": PerformanceClass.LINEAR_BY_ROW,
        "documented_limitations": (),
    }
    fields.update(overrides)
    return DetectorMetadata(**fields)  # type: ignore[arg-type]


def make_success_result(detector_id: str, *, duration_ms: int = 0) -> DetectorRunResult:
    evidence = Evidence(
        evidence_id="ev-1",
        evidence_type=EvidenceType.ROW_SET,
        calculation_version="1",
        structured_payload={},
        affected_columns=(),
        affected_row_references=(),
        scope=SamplingScope.FULL,
        display_safe_summary="found something",
    )
    finding = FindingCandidate(
        detector_id=detector_id,
        detector_version="1",
        category=DetectorCategory.STRUCTURAL,
        severity=Severity.LOW,
        confidence=1.0,
        calculated_observation="observed",
        affected_columns=(),
        affected_row_references=(),
        evidence_ids=("ev-1",),
        default_remediation_template_key=None,
        default_validation_rule_template_key=None,
    )
    return DetectorRunResult(
        detector_id=detector_id,
        detector_version="1",
        status=DetectorRunStatus.SUCCESS,
        findings=(finding,),
        evidence=(evidence,),
        warnings=(),
        execution_metrics=ExecutionMetrics(duration_ms=duration_ms),
    )


class ScriptedDetector:
    """A `Detector`-shaped test double whose `supports()`/`run()` outcomes
    are scripted, and which records the exact request objects it received
    for assertion.
    """

    def __init__(
        self,
        *,
        detector_id: str = "structural.stub",
        requires_raw_rows: bool = False,
        requires_confirmed_context: bool = False,
        config_schema: type[BaseModel] = _EmptyConfig,
        default_configuration: dict[str, object] | None = None,
        supports_result: bool | BaseException = True,
        run_result: DetectorRunResult | BaseException | None = None,
        run_sleep_seconds: float = 0.0,
    ) -> None:
        self.metadata = make_metadata(
            detector_id=detector_id,
            requires_raw_rows=requires_raw_rows,
            requires_confirmed_context=requires_confirmed_context,
            default_configuration=default_configuration or {},
        )
        self.config_schema = config_schema
        self._supports_result = supports_result
        self._run_result = run_result or make_success_result(detector_id)
        self._run_sleep_seconds = run_sleep_seconds
        self.received_support_request: DetectorSupportRequest | None = None
        self.received_run_request: DetectorRunRequest | None = None
        self.run_called = False

    def supports(self, request: DetectorSupportRequest) -> bool:
        self.received_support_request = request
        if isinstance(self._supports_result, BaseException):
            raise self._supports_result
        return self._supports_result

    def run(self, request: DetectorRunRequest) -> DetectorRunResult:
        self.run_called = True
        self.received_run_request = request
        if self._run_sleep_seconds:
            time.sleep(self._run_sleep_seconds)
        if isinstance(self._run_result, BaseException):
            raise self._run_result
        return self._run_result


def run_kwargs(**overrides: object) -> dict[str, object]:
    fields: dict[str, object] = {
        "dataset_profile": make_dataset_profile(),
        "rows": ({"qty": 1}, {"qty": 2}),
        "row_references": (RowReference(row_number=0), RowReference(row_number=1)),
        "confirmed_context": {"probable_domain": "sales"},
        "security_exposure": SecurityExposureState(
            model_provider_enabled=False, sample_transmission_enabled=False
        ),
        "analysis_timestamp": ANALYSIS_TIMESTAMP,
    }
    fields.update(overrides)
    return fields


# ---------------------------------------------------------------------------
# AC-17: skip unsupported detectors without calling run()
# ---------------------------------------------------------------------------


def test_run_detectors_skips_unsupported_detector_without_calling_run() -> None:
    detector = ScriptedDetector(detector_id="structural.skip_me", supports_result=False)

    results = run_detectors(
        [detector],
        **run_kwargs(),  # type: ignore[arg-type]
    )

    assert detector.run_called is False
    assert results[0].status is DetectorRunStatus.SKIPPED
    assert results[0].warnings[0].code == "detector.skipped_not_applicable"


# ---------------------------------------------------------------------------
# AC-18: isolate supports()/run() exceptions and continue
# ---------------------------------------------------------------------------


def test_run_detectors_isolates_supports_exception_and_continues() -> None:
    raising = ScriptedDetector(
        detector_id="structural.raises_in_supports", supports_result=RuntimeError("boom")
    )
    succeeding = ScriptedDetector(detector_id="structural.succeeds")

    results = run_detectors([raising, succeeding], **run_kwargs())  # type: ignore[arg-type]

    assert results[0].status is DetectorRunStatus.FAILED
    assert results[0].safe_failure is not None
    assert results[0].safe_failure.error_type == "RuntimeError"
    assert results[1].status is DetectorRunStatus.SUCCESS


def test_run_detectors_isolates_run_exception_and_continues() -> None:
    raising = ScriptedDetector(
        detector_id="structural.raises_in_run", run_result=RuntimeError("boom")
    )
    succeeding = ScriptedDetector(detector_id="structural.succeeds")

    results = run_detectors([raising, succeeding], **run_kwargs())  # type: ignore[arg-type]

    assert results[0].status is DetectorRunStatus.FAILED
    assert results[0].safe_failure is not None
    assert results[0].findings == ()
    assert results[1].status is DetectorRunStatus.SUCCESS


def test_run_detectors_isolates_invalid_effective_configuration() -> None:
    detector = ScriptedDetector(
        detector_id="structural.bad_config",
        config_schema=_ThresholdConfig,
        default_configuration={},
    )

    results = run_detectors([detector], **run_kwargs())  # type: ignore[arg-type]

    assert results[0].status is DetectorRunStatus.FAILED
    assert detector.run_called is False


# ---------------------------------------------------------------------------
# AC-19: withhold undeclared inputs
# ---------------------------------------------------------------------------


def test_run_detectors_withholds_rows_and_context_when_not_declared() -> None:
    detector = ScriptedDetector(
        detector_id="structural.no_rows_no_context",
        requires_raw_rows=False,
        requires_confirmed_context=False,
    )

    run_detectors([detector], **run_kwargs())  # type: ignore[arg-type]

    assert detector.received_run_request is not None
    assert detector.received_run_request.rows == ()
    assert detector.received_run_request.row_references == ()
    assert detector.received_run_request.confirmed_context is None


def test_run_detectors_provides_rows_and_context_when_declared() -> None:
    kwargs = run_kwargs()
    detector = ScriptedDetector(
        detector_id="structural.wants_rows_and_context",
        requires_raw_rows=True,
        requires_confirmed_context=True,
    )

    run_detectors([detector], **kwargs)  # type: ignore[arg-type]

    assert detector.received_run_request is not None
    assert detector.received_run_request.rows == kwargs["rows"]
    assert detector.received_run_request.row_references == kwargs["row_references"]
    assert detector.received_run_request.confirmed_context == kwargs["confirmed_context"]


def test_run_detectors_withholds_confirmed_context_from_support_request_too() -> None:
    detector = ScriptedDetector(
        detector_id="structural.no_context", requires_confirmed_context=False
    )

    run_detectors([detector], **run_kwargs())  # type: ignore[arg-type]

    assert detector.received_support_request is not None
    assert detector.received_support_request.confirmed_context is None


# ---------------------------------------------------------------------------
# AC-20: engine-owned timing
# ---------------------------------------------------------------------------


def test_run_detectors_records_measured_duration() -> None:
    detector = ScriptedDetector(detector_id="structural.slow", run_sleep_seconds=0.02)

    results = run_detectors([detector], **run_kwargs())  # type: ignore[arg-type]

    assert results[0].execution_metrics.duration_ms > 0


def test_run_detectors_overrides_detector_reported_duration() -> None:
    misreported = make_success_result("structural.misreports_duration", duration_ms=999_999)
    detector = ScriptedDetector(
        detector_id="structural.misreports_duration", run_result=misreported
    )

    results = run_detectors([detector], **run_kwargs())  # type: ignore[arg-type]

    assert results[0].execution_metrics.duration_ms != 999_999
    assert results[0].execution_metrics.duration_ms >= 0


# ---------------------------------------------------------------------------
# AC-21: deterministic order
# ---------------------------------------------------------------------------


def test_run_detectors_preserves_input_order_across_mixed_outcomes() -> None:
    skipped = ScriptedDetector(detector_id="structural.b_skipped", supports_result=False)
    failed = ScriptedDetector(detector_id="structural.a_failed", run_result=RuntimeError("x"))
    succeeded = ScriptedDetector(detector_id="structural.c_succeeded")

    results = run_detectors([skipped, failed, succeeded], **run_kwargs())  # type: ignore[arg-type]

    assert [r.detector_id for r in results] == [
        "structural.b_skipped",
        "structural.a_failed",
        "structural.c_succeeded",
    ]
    assert [r.status for r in results] == [
        DetectorRunStatus.SKIPPED,
        DetectorRunStatus.FAILED,
        DetectorRunStatus.SUCCESS,
    ]


def test_run_detectors_accepts_empty_detector_sequence_boundary() -> None:
    assert run_detectors([], **run_kwargs()) == ()  # type: ignore[arg-type]


def test_run_detectors_rejects_rows_row_references_length_mismatch() -> None:
    with pytest.raises(ValueError, match="rows and row_references"):
        run_detectors(
            [ScriptedDetector()],
            **run_kwargs(  # type: ignore[arg-type]
                rows=({"qty": 1}, {"qty": 2}), row_references=(RowReference(row_number=0),)
            ),
        )
