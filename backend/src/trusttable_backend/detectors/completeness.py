"""Completeness detectors (`DET-02` partial), matching
`docs/detector-framework.md` §16's "Completeness" category: excessive
missing values and missing likely identifier.

Both detectors reuse `PROF-03`'s already-computed profile facts
(`ColumnProfile.null_count`, the `likely_identifier` text-family metric)
to decide *whether* to fire, but declare `requires_raw_rows=True` because
identifying *which* rows are missing a value needs the raw row values —
unlike `structural.empty_column` (`WP-014`), whose condition
(`inferred_type == UNKNOWN`) already exactly means "every row is blank",
so no row-level evidence is needed there.

Framework-independent per `docs/architecture.md` §3's "Detectors" layer
rule ("detector modules do not import FastAPI"); `pydantic.BaseModel` is
used only for each detector's (currently empty) `config_schema`.
"""

from __future__ import annotations

from pydantic import BaseModel

from ..domain.evidence import Evidence, EvidenceType
from ..domain.parsing import SamplingScope
from ..domain.value_objects import Severity
from ..profiling.schemas import InferredColumnType
from .contract import (
    DetectorCategory,
    DetectorMetadata,
    DetectorRunRequest,
    DetectorRunResult,
    DetectorRunStatus,
    DetectorSupportRequest,
    ExecutionMetrics,
    FindingCandidate,
    PerformanceClass,
)


class _EmptyConfig(BaseModel):
    """No configurable parameters for either detector in this package."""


_EXCESSIVE_MISSING_RATIO = 0.01
"""A column's missing ratio (`null_count / sampling.sample_size`) at or
above this fraction is flagged `excessive_missing_values`. A disclosed,
reversible design choice (`docs/detector-framework.md` §11 requires an
explicit rule but fixes no exact number) — chosen so it fires on the
`DEMO-01` demo dataset's injected 3/300 (exactly 1.0%) gaps in
`quantity`/`line_total` while remaining strictly above `order_id`'s 1/300
(0.33%) single-row gap, which `missing_likely_identifier` (not this
detector) is responsible for."""


def _is_missing(value: object) -> bool:
    """`None` and `""` are both treated as "missing" by both detectors in
    this module — consistent with `PROF-02`/`PROF-03`'s own existing
    "non-blank" convention, and semantically correct here: unlike
    `ExactDuplicateRowsDetector` (`WP-014`), there is no reason to
    distinguish "explicitly null" from "empty string" when the question
    is simply "is a value present"."""
    return value is None or value == ""


class ExcessiveMissingValuesDetector:
    """`completeness.excessive_missing_values` — flags columns whose
    fraction of missing (`None`/`""`) values reaches
    `_EXCESSIVE_MISSING_RATIO`.

    Columns already classified `UNKNOWN` (fully empty, zero non-blank
    values) are excluded: `structural.empty_column` (`WP-014`) already
    covers that condition, and double-reporting the same fact under two
    detector IDs would be confusing rather than useful.
    """

    metadata = DetectorMetadata(
        detector_id="completeness.excessive_missing_values",
        version="1",
        name="Excessive missing values",
        category=DetectorCategory.COMPLETENESS,
        description=(
            "Flags columns whose fraction of missing values reaches a configured threshold."
        ),
        applicable_inferred_types=(),
        required_profile_fields=(
            "column_profiles[].null_count",
            "sampling.sample_size",
        ),
        requires_raw_rows=True,
        requires_confirmed_context=False,
        default_configuration={},
        performance_class=PerformanceClass.LINEAR_BY_ROW,
        documented_limitations=(
            "Columns classified as fully empty (UNKNOWN type) are excluded; "
            "structural.empty_column reports those instead.",
        ),
    )
    config_schema: type[BaseModel] = _EmptyConfig

    def supports(self, request: DetectorSupportRequest) -> bool:
        del request  # Dataset-level, structurally always applicable.
        return True

    def run(self, request: DetectorRunRequest) -> DetectorRunResult:
        sample_size = request.dataset_profile.sampling.sample_size
        findings: list[FindingCandidate] = []
        evidence: list[Evidence] = []

        if sample_size <= 0:
            return DetectorRunResult(
                detector_id=self.metadata.detector_id,
                detector_version=self.metadata.version,
                status=DetectorRunStatus.SUCCESS,
                findings=(),
                evidence=(),
                warnings=(),
                execution_metrics=ExecutionMetrics(duration_ms=0),
            )

        for profile in request.dataset_profile.column_profiles:
            if profile.inferred_type is InferredColumnType.UNKNOWN:
                continue

            ratio = profile.null_count / sample_size
            if ratio < _EXCESSIVE_MISSING_RATIO:
                continue

            affected_indices = [
                index
                for index, row in enumerate(request.rows)
                if _is_missing(row.get(profile.column.internal_key))
            ]
            affected_row_references = tuple(
                request.row_references[index] for index in affected_indices
            )

            evidence_id = (
                f"completeness.excessive_missing_values.evidence.{profile.column.internal_key}"
            )
            column_evidence = Evidence(
                evidence_id=evidence_id,
                evidence_type=EvidenceType.ROW_SET,
                calculation_version="1",
                structured_payload={
                    "null_count": profile.null_count,
                    "sample_size": sample_size,
                    "missing_ratio": ratio,
                },
                affected_columns=(profile.column,),
                affected_row_references=affected_row_references,
                scope=SamplingScope.FULL,
                display_safe_summary=(
                    f"Column '{profile.column.original_name}' is missing a value in "
                    f"{profile.null_count} of {sample_size} row(s)."
                ),
            )
            finding = FindingCandidate(
                detector_id=self.metadata.detector_id,
                detector_version=self.metadata.version,
                category=self.metadata.category,
                severity=Severity.MEDIUM,
                confidence=1.0,
                calculated_observation=(
                    f"Column '{profile.column.original_name}' is missing a value in "
                    f"{profile.null_count} of {sample_size} row(s) "
                    f"({ratio:.1%})."
                ),
                affected_columns=(profile.column,),
                affected_row_references=affected_row_references,
                evidence_ids=(evidence_id,),
                default_remediation_template_key=None,
                default_validation_rule_template_key=None,
            )
            evidence.append(column_evidence)
            findings.append(finding)

        return DetectorRunResult(
            detector_id=self.metadata.detector_id,
            detector_version=self.metadata.version,
            status=DetectorRunStatus.SUCCESS,
            findings=tuple(findings),
            evidence=tuple(evidence),
            warnings=(),
            execution_metrics=ExecutionMetrics(duration_ms=0),
        )


class MissingLikelyIdentifierDetector:
    """`completeness.missing_likely_identifier` — flags columns that
    `PROF-03` has flagged `likely_identifier` (a text-family metric,
    computed independently of `inferred_type` per `PROF-02` r3's
    forward-compatibility requirement) but that still contain one or more
    missing (`None`/`""`) values.
    """

    metadata = DetectorMetadata(
        detector_id="completeness.missing_likely_identifier",
        version="1",
        name="Missing likely identifier",
        category=DetectorCategory.COMPLETENESS,
        description=(
            "Flags columns that behave like identifiers but contain one or more missing values."
        ),
        applicable_inferred_types=(),
        required_profile_fields=(
            "column_profiles[].null_count",
            "column_profiles[].metrics.likely_identifier",
        ),
        requires_raw_rows=True,
        requires_confirmed_context=False,
        default_configuration={},
        performance_class=PerformanceClass.LINEAR_BY_ROW,
        documented_limitations=(
            "Relies on PROF-03's likely_identifier metric (a uniqueness-ratio "
            "heuristic), not a declared or confirmed identifier role.",
        ),
    )
    config_schema: type[BaseModel] = _EmptyConfig

    def supports(self, request: DetectorSupportRequest) -> bool:
        del request  # Dataset-level, structurally always applicable.
        return True

    def run(self, request: DetectorRunRequest) -> DetectorRunResult:
        findings: list[FindingCandidate] = []
        evidence: list[Evidence] = []

        for profile in request.dataset_profile.column_profiles:
            if profile.metrics.get("likely_identifier") is not True:
                continue
            if profile.null_count <= 0:
                continue

            affected_indices = [
                index
                for index, row in enumerate(request.rows)
                if _is_missing(row.get(profile.column.internal_key))
            ]
            affected_row_references = tuple(
                request.row_references[index] for index in affected_indices
            )

            evidence_id = (
                f"completeness.missing_likely_identifier.evidence.{profile.column.internal_key}"
            )
            column_evidence = Evidence(
                evidence_id=evidence_id,
                evidence_type=EvidenceType.ROW_SET,
                calculation_version="1",
                structured_payload={"null_count": profile.null_count},
                affected_columns=(profile.column,),
                affected_row_references=affected_row_references,
                scope=SamplingScope.FULL,
                display_safe_summary=(
                    f"Likely-identifier column '{profile.column.original_name}' is "
                    f"missing a value in {profile.null_count} row(s)."
                ),
            )
            finding = FindingCandidate(
                detector_id=self.metadata.detector_id,
                detector_version=self.metadata.version,
                category=self.metadata.category,
                severity=Severity.HIGH,
                confidence=1.0,
                calculated_observation=(
                    f"Column '{profile.column.original_name}' behaves like an identifier "
                    f"(high uniqueness) but is missing a value in {profile.null_count} row(s)."
                ),
                affected_columns=(profile.column,),
                affected_row_references=affected_row_references,
                evidence_ids=(evidence_id,),
                default_remediation_template_key=None,
                default_validation_rule_template_key=None,
            )
            evidence.append(column_evidence)
            findings.append(finding)

        return DetectorRunResult(
            detector_id=self.metadata.detector_id,
            detector_version=self.metadata.version,
            status=DetectorRunStatus.SUCCESS,
            findings=tuple(findings),
            evidence=tuple(evidence),
            warnings=(),
            execution_metrics=ExecutionMetrics(duration_ms=0),
        )
