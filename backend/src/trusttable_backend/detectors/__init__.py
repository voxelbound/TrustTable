"""Detector interface (`DET-01`) and the growing real detector catalogue
(`DET-02`, partial): the framework-independent detector contract,
registration, execution engine, and (so far) two real structural
detectors, two real completeness detectors, two real consistency
detectors, two real validity detectors, plus the invalid-percentages/
line-total-mismatch pair, matching
`docs/detector-framework.md` §2/§3/§4/§5/§6/§9/§10/§13/§16.

`DET-02`'s remaining 2 detectors and `DET-SEC-01` (prompt-injection
detector) are later packages that extend `catalogue.DETECTORS`
additively; a future analysis-orchestration package (`API-01`) calls
`run_detectors()`.
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
    "register_detectors",
    "run_detectors",
]
