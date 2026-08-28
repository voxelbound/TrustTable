"""Detector execution engine (`DET-01`), matching
`docs/detector-framework.md` §10 (Execution): determine supported
detectors, provide only declared inputs, isolate detector failures,
record timing, collect evidence/findings, preserve deterministic order,
and report skipped detectors and reasons.

Time/resource-boundary enforcement (§10, item 3) is measurement-only in
this package: the engine records real elapsed duration around each
`run()` call and isolates exceptions via `try`/`except`, but cannot
interrupt a detector that never returns. True preemptive cancellation
needs a worker/thread execution boundary, which this package does not
build — disclosed here rather than silently claimed as solved.
"""

from __future__ import annotations

import dataclasses
import time
from collections.abc import Mapping, Sequence
from datetime import datetime

from pydantic import ValidationError

from ..domain.value_objects import RowReference
from ..profiling.schemas import DatasetProfile
from .contract import (
    Detector,
    DetectorRunRequest,
    DetectorRunResult,
    DetectorRunStatus,
    DetectorSupportRequest,
    DetectorWarning,
    ExecutionMetrics,
    SafeFailure,
    SecurityExposureState,
)


def _failed_result(
    detector: Detector, *, error: BaseException, duration_ms: int
) -> DetectorRunResult:
    return DetectorRunResult(
        detector_id=detector.metadata.detector_id,
        detector_version=detector.metadata.version,
        status=DetectorRunStatus.FAILED,
        findings=(),
        evidence=(),
        warnings=(),
        execution_metrics=ExecutionMetrics(duration_ms=duration_ms),
        safe_failure=SafeFailure(
            error_type=type(error).__name__,
            safe_message=f"{detector.metadata.detector_id} raised an exception during execution",
        ),
    )


def _skipped_result(detector: Detector) -> DetectorRunResult:
    return DetectorRunResult(
        detector_id=detector.metadata.detector_id,
        detector_version=detector.metadata.version,
        status=DetectorRunStatus.SKIPPED,
        findings=(),
        evidence=(),
        warnings=(
            DetectorWarning(
                code="detector.skipped_not_applicable",
                message=(f"{detector.metadata.detector_id} skipped: supports() returned False"),
            ),
        ),
        execution_metrics=ExecutionMetrics(duration_ms=0),
    )


def run_detectors(
    detectors: Sequence[Detector],
    *,
    dataset_profile: DatasetProfile,
    rows: Sequence[Mapping[str, object]],
    row_references: Sequence[RowReference],
    confirmed_context: Mapping[str, object] | None,
    security_exposure: SecurityExposureState,
    analysis_timestamp: datetime,
    configuration_overrides: Mapping[str, Mapping[str, object]] | None = None,
) -> tuple[DetectorRunResult, ...]:
    """Run `detectors` in the given (deterministic) order, returning one
    `DetectorRunResult` per detector in the same order.

    Each detector receives only the inputs it declares
    (`metadata.requires_raw_rows`/`requires_confirmed_context`): a
    detector that does not request raw rows receives empty `rows`/
    `row_references` tuples regardless of what the caller supplied, and a
    detector that does not request confirmed context always receives
    `None`.
    """
    if len(rows) != len(row_references):
        raise ValueError("run_detectors: rows and row_references must have the same length")

    overrides = configuration_overrides or {}
    results: list[DetectorRunResult] = []

    for detector in detectors:
        metadata = detector.metadata
        support_request = DetectorSupportRequest(
            dataset_profile=dataset_profile,
            confirmed_context=(confirmed_context if metadata.requires_confirmed_context else None),
            security_exposure=security_exposure,
        )

        start = time.perf_counter()
        try:
            supported = detector.supports(support_request)
        except Exception as exc:  # noqa: BLE001 - isolated per docs/detector-framework.md §10
            duration_ms = round((time.perf_counter() - start) * 1000)
            results.append(_failed_result(detector, error=exc, duration_ms=duration_ms))
            continue

        if not supported:
            results.append(_skipped_result(detector))
            continue

        effective_configuration: Mapping[str, object] = {
            **metadata.default_configuration,
            **overrides.get(metadata.detector_id, {}),
        }
        try:
            validated_configuration = detector.config_schema.model_validate(
                effective_configuration
            ).model_dump()
        except ValidationError as exc:
            results.append(_failed_result(detector, error=exc, duration_ms=0))
            continue

        run_request = DetectorRunRequest(
            dataset_profile=dataset_profile,
            rows=(tuple(rows) if metadata.requires_raw_rows else ()),
            row_references=(tuple(row_references) if metadata.requires_raw_rows else ()),
            confirmed_context=(confirmed_context if metadata.requires_confirmed_context else None),
            configuration=validated_configuration,
            analysis_timestamp=analysis_timestamp,
            security_exposure=security_exposure,
        )

        start = time.perf_counter()
        try:
            result = detector.run(run_request)
        except Exception as exc:  # noqa: BLE001 - isolated per docs/detector-framework.md §10
            duration_ms = round((time.perf_counter() - start) * 1000)
            results.append(_failed_result(detector, error=exc, duration_ms=duration_ms))
            continue
        duration_ms = round((time.perf_counter() - start) * 1000)

        # The engine, not the detector, owns recorded timing (docs/detector-framework.md
        # §10 "record timing" is an execution-engine responsibility, distinct from
        # "isolate detector failures").
        results.append(
            dataclasses.replace(result, execution_metrics=ExecutionMetrics(duration_ms=duration_ms))
        )

    return tuple(results)
