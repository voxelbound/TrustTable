"""Detector interface (`DET-01`): the framework-independent detector
contract, registration, and execution engine matching
`docs/detector-framework.md` §2/§3/§4/§5/§6/§9/§10/§13.

No real detector exists in this package. `DET-02` (initial detector set)
and `DET-SEC-01` (prompt-injection detector) implement `Detector` and
call `register_detectors()`; a future analysis-orchestration package
(`API-01`) calls `run_detectors()`.
"""

from __future__ import annotations

from .contract import (
    Detector,
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
from .engine import run_detectors
from .registry import register_detectors

__all__ = [
    "Detector",
    "DetectorCategory",
    "DetectorMetadata",
    "DetectorRunRequest",
    "DetectorRunResult",
    "DetectorRunStatus",
    "DetectorSupportRequest",
    "DetectorWarning",
    "ExecutionMetrics",
    "FindingCandidate",
    "PerformanceClass",
    "SafeFailure",
    "SecurityExposureState",
    "register_detectors",
    "run_detectors",
]
