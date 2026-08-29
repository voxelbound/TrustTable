"""Detector interface (`DET-01`) and the complete `DET-02` detector
catalogue: the framework-independent detector contract, registration,
execution engine, and all twelve real detectors across the structural,
completeness, consistency, validity, cross-field, and statistical
categories, matching `docs/detector-framework.md`
§2/§3/§4/§5/§6/§9/§10/§13/§16.

`DET-SEC-01` (prompt-injection detector) is a later package that extends
`catalogue.DETECTORS` additively; a future analysis-orchestration
package (`API-01`) calls `run_detectors()`.
"""

from __future__ import annotations

from .catalogue import DETECTORS
from .completeness import ExcessiveMissingValuesDetector, MissingLikelyIdentifierDetector
from .consistency import InconsistentCapitalizationDetector, LeadingTrailingWhitespaceDetector
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
from .cross_field import LineTotalMismatchDetector
from .engine import run_detectors
from .registry import register_detectors
from .statistical import ExtremeOutliersDetector, SuspiciouslyConstantColumnDetector
from .structural import EmptyColumnDetector, ExactDuplicateRowsDetector
from .validity import (
    FutureDatesDetector,
    InvalidPercentagesDetector,
    NegativeLikelyNonNegativeValuesDetector,
)

__all__ = [
    "DETECTORS",
    "Detector",
    "DetectorCategory",
    "DetectorMetadata",
    "DetectorRunRequest",
    "DetectorRunResult",
    "DetectorRunStatus",
    "DetectorSupportRequest",
    "DetectorWarning",
    "EmptyColumnDetector",
    "ExactDuplicateRowsDetector",
    "ExcessiveMissingValuesDetector",
    "ExecutionMetrics",
    "ExtremeOutliersDetector",
    "FindingCandidate",
    "FutureDatesDetector",
    "InconsistentCapitalizationDetector",
    "InvalidPercentagesDetector",
    "LeadingTrailingWhitespaceDetector",
    "LineTotalMismatchDetector",
    "MissingLikelyIdentifierDetector",
    "NegativeLikelyNonNegativeValuesDetector",
    "PerformanceClass",
    "SafeFailure",
    "SecurityExposureState",
    "SuspiciouslyConstantColumnDetector",
    "register_detectors",
    "run_detectors",
]
