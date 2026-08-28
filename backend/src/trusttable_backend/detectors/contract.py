"""Detector contract (`DET-01`), matching `docs/detector-framework.md`
§2 (Detector contract), §3 (Metadata), §4 (Categories), §5 (Input model),
§6 (Output model), and §13 (Performance classes).

Framework-independent per `docs/architecture.md` §3's rule for the
"Detectors" layer ("detector modules do not import FastAPI"). `pydantic`
is used for exactly one purpose — `Detector.config_schema: type[BaseModel]`
— matching §2's own conceptual interface; no FastAPI or SQLAlchemy import
exists anywhere in this module.

No real detector exists in this package. `DET-02` (initial detector set)
and `DET-SEC-01` (prompt-injection detector) implement `Detector` against
these shapes; `registry.py`/`engine.py` (also `DET-01`) register and run
them.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from pydantic import BaseModel

from ..domain.evidence import Evidence
from ..domain.value_objects import ColumnReference, RowReference, Severity
from ..profiling.schemas import DatasetProfile, InferredColumnType


class DetectorCategory(StrEnum):
    """Closed set of detector categories (`docs/detector-framework.md` §4)."""

    STRUCTURAL = "structural"
    COMPLETENESS = "completeness"
    CONSISTENCY = "consistency"
    VALIDITY = "validity"
    STATISTICAL = "statistical"
    CROSS_FIELD = "cross_field"
    AI_PROCESSING_SECURITY = "ai_processing_security"


class PerformanceClass(StrEnum):
    """Closed set of detector performance classes
    (`docs/detector-framework.md` §13).
    """

    CONSTANT_OR_METADATA_ONLY = "constant_or_metadata_only"
    LINEAR_BY_ROW = "linear_by_row"
    LINEAR_BY_VALUE_LENGTH = "linear_by_value_length"
    GROUPED_AGGREGATION = "grouped_aggregation"
    PAIRWISE_CANDIDATE = "pairwise_candidate"
    SAMPLED_EXPENSIVE = "sampled_expensive"


@dataclass(frozen=True, slots=True)
class DetectorMetadata:
    """Every detector's declared metadata (`docs/detector-framework.md` §3).

    `applicable_inferred_types` uses an empty tuple as the documented
    convention for a dataset-level detector that is not restricted to
    particular column types (e.g. an exact-duplicate-rows detector).
    """

    detector_id: str
    version: str
    name: str
    category: DetectorCategory
    description: str
    applicable_inferred_types: tuple[InferredColumnType, ...]
    required_profile_fields: tuple[str, ...]
    requires_raw_rows: bool
    requires_confirmed_context: bool
    default_configuration: Mapping[str, object]
    performance_class: PerformanceClass
    documented_limitations: tuple[str, ...]

    def __post_init__(self) -> None:
        if not self.detector_id:
            raise ValueError("DetectorMetadata.detector_id must not be empty")
        if "." not in self.detector_id:
            raise ValueError("DetectorMetadata.detector_id must be namespaced (contain '.')")
        if not self.version:
            raise ValueError("DetectorMetadata.version must not be empty")
        if not self.name:
            raise ValueError("DetectorMetadata.name must not be empty")
        if not self.description:
            raise ValueError("DetectorMetadata.description must not be empty")
        if any(not field for field in self.required_profile_fields):
            raise ValueError("DetectorMetadata.required_profile_fields entries must not be empty")


@dataclass(frozen=True, slots=True)
class SecurityExposureState:
    """A bounded projection of `docs/domain-model.md` §5 Analysis's
    exposure-relevant fields ("model provider", "sample-transmission
    setting"), needed by `docs/detector-framework.md` §5's "security
    exposure state" detector input and §14's "severity considers actual
    model exposure" requirement. Not the full `Analysis` aggregate
    (deferred to `DB-01`/`API-01`) — a minimal, disclosed, forward-
    compatible slice.
    """

    model_provider_enabled: bool
    sample_transmission_enabled: bool

    def __post_init__(self) -> None:
        if self.sample_transmission_enabled and not self.model_provider_enabled:
            raise ValueError(
                "SecurityExposureState.sample_transmission_enabled requires model_provider_enabled"
            )


@dataclass(frozen=True, slots=True)
class DetectorSupportRequest:
    """Eligibility-checking input for `Detector.supports()`
    (`docs/detector-framework.md` §2/§5). Lighter than
    `DetectorRunRequest` — no bounded rows/row-reference mapping/
    configuration/analysis timestamp, none of which are needed merely to
    decide applicability.

    `confirmed_context` is an open `Mapping[str, object] | None`
    placeholder: `DatasetContext` (`CTX-01`) does not exist yet (v0.2).
    """

    dataset_profile: DatasetProfile
    confirmed_context: Mapping[str, object] | None
    security_exposure: SecurityExposureState


@dataclass(frozen=True, slots=True)
class DetectorRunRequest:
    """Full input for `Detector.run()` (`docs/detector-framework.md`
    §2/§5). `rows`/`row_references` are bounded source rows and their
    row-reference mapping (1:1, same order) — engine-scoped to empty
    tuples when the detector does not declare `requires_raw_rows`.
    """

    dataset_profile: DatasetProfile
    rows: tuple[Mapping[str, object], ...]
    row_references: tuple[RowReference, ...]
    confirmed_context: Mapping[str, object] | None
    configuration: Mapping[str, object]
    analysis_timestamp: datetime
    security_exposure: SecurityExposureState

    def __post_init__(self) -> None:
        if len(self.rows) != len(self.row_references):
            raise ValueError("DetectorRunRequest.rows and row_references must have the same length")


class DetectorRunStatus(StrEnum):
    """Closed set of detector run outcomes."""

    SUCCESS = "success"
    SKIPPED = "skipped"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class FindingCandidate:
    """One finding candidate a detector run produces
    (`docs/detector-framework.md` §6). Not the full `Finding` aggregate
    (`docs/domain-model.md` §12 — a later package assigns a finding ID,
    review state, and created timestamp); this is exactly what a detector
    itself is responsible for calculating.
    """

    detector_id: str
    detector_version: str
    category: DetectorCategory
    severity: Severity
    confidence: float
    calculated_observation: str
    affected_columns: tuple[ColumnReference, ...]
    affected_row_references: tuple[RowReference, ...]
    evidence_ids: tuple[str, ...]
    default_remediation_template_key: str | None
    default_validation_rule_template_key: str | None

    def __post_init__(self) -> None:
        if not self.detector_id:
            raise ValueError("FindingCandidate.detector_id must not be empty")
        if not self.detector_version:
            raise ValueError("FindingCandidate.detector_version must not be empty")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("FindingCandidate.confidence must be between 0 and 1")
        if not self.calculated_observation:
            raise ValueError("FindingCandidate.calculated_observation must not be empty")
        if not self.evidence_ids:
            raise ValueError(
                "FindingCandidate.evidence_ids must not be empty "
                "(docs/domain-model.md #12: every finding has at least one evidence object)"
            )


@dataclass(frozen=True, slots=True)
class DetectorWarning:
    """A non-fatal condition observed while running a detector. Mirrors
    `parsers.ParsingWarning`/`profiling.ProfilingWarning`'s exact shape
    (namespaced `code`, `message`, optional column reference) in a
    distinct, detector-specific type, consistent with those packages'
    precedent for lifecycle-specific warning types.
    """

    code: str
    message: str
    column: ColumnReference | None = None

    def __post_init__(self) -> None:
        if not self.message:
            raise ValueError("DetectorWarning.message must not be empty")
        if "." not in self.code:
            raise ValueError("DetectorWarning.code must be namespaced (contain '.')")


@dataclass(frozen=True, slots=True)
class ExecutionMetrics:
    """Timing metadata for one detector run. Engine-owned (`engine.py`
    overwrites whatever a detector itself returns) — see `docs/
    detector-framework.md` §10's "record timing" execution-engine
    responsibility.
    """

    duration_ms: int

    def __post_init__(self) -> None:
        if self.duration_ms < 0:
            raise ValueError("ExecutionMetrics.duration_ms must not be negative")


@dataclass(frozen=True, slots=True)
class SafeFailure:
    """A safe, non-raw-data description of an isolated detector failure
    (`docs/detector-framework.md` §6/§10). Never includes raw dataset
    content.
    """

    error_type: str
    safe_message: str

    def __post_init__(self) -> None:
        if not self.error_type:
            raise ValueError("SafeFailure.error_type must not be empty")
        if not self.safe_message:
            raise ValueError("SafeFailure.safe_message must not be empty")


@dataclass(frozen=True, slots=True)
class DetectorRunResult:
    """The result of running one detector (`docs/detector-framework.md`
    §6). `status=FAILED` requires `safe_failure` set and empty
    `findings`/`evidence` (an isolated failure produces no partial
    findings); `status=SUCCESS` requires `safe_failure=None`.

    Evidence cross-referencing (docs/domain-model.md §7's "evidence
    produced in the same result or an approved upstream profile") is
    checked only against this result's own `evidence` collection —
    `DatasetProfile` carries no `Evidence` objects today, so "upstream
    profile" evidence references are not structurally possible yet. A
    disclosed, reversible scoping decision.
    """

    detector_id: str
    detector_version: str
    status: DetectorRunStatus
    findings: tuple[FindingCandidate, ...]
    evidence: tuple[Evidence, ...]
    warnings: tuple[DetectorWarning, ...]
    execution_metrics: ExecutionMetrics
    safe_failure: SafeFailure | None = None

    def __post_init__(self) -> None:
        if not self.detector_id:
            raise ValueError("DetectorRunResult.detector_id must not be empty")
        if not self.detector_version:
            raise ValueError("DetectorRunResult.detector_version must not be empty")
        if self.status is DetectorRunStatus.FAILED:
            if self.safe_failure is None:
                raise ValueError("DetectorRunResult.safe_failure is required when status is FAILED")
            if self.findings or self.evidence:
                raise ValueError(
                    "DetectorRunResult.findings and evidence must be empty when status is FAILED"
                )
        elif self.status is DetectorRunStatus.SUCCESS and self.safe_failure is not None:
            raise ValueError("DetectorRunResult.safe_failure must be None when status is SUCCESS")

        known_evidence_ids = {evidence.evidence_id for evidence in self.evidence}
        for finding in self.findings:
            for evidence_id in finding.evidence_ids:
                if evidence_id not in known_evidence_ids:
                    raise ValueError(
                        "DetectorRunResult.findings entries must reference an evidence_id "
                        f"present in this result's own evidence collection: {evidence_id!r}"
                    )


class Detector(Protocol):
    """The detector contract (`docs/detector-framework.md` §2)."""

    metadata: DetectorMetadata
    config_schema: type[BaseModel]

    def supports(self, request: DetectorSupportRequest) -> bool: ...

    def run(self, request: DetectorRunRequest) -> DetectorRunResult: ...
