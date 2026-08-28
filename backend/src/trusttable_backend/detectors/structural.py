"""Structural detectors (`DET-02` partial), matching
`docs/detector-framework.md` §16's "Structural" category: exact
duplicate rows and empty columns.

Both detectors reuse `PROF-03`'s already-computed profile facts as much
as possible: `structural.empty_column` relies entirely on `PROF-02`'s
`InferredColumnType.UNKNOWN` classification (which already exactly means
"zero non-blank values" — see `type_inference.py`'s `_classify()`), and
`structural.exact_duplicate_rows` uses the already-computed
`dataset_metrics["duplicate_row_count"]` count for its observation text,
while still requiring raw rows to identify *which* rows are duplicates
for evidence.

Framework-independent per `docs/architecture.md` §3's "Detectors" layer
rule ("detector modules do not import FastAPI"); `pydantic.BaseModel` is
used only for each detector's (currently empty) `config_schema`.
"""

from __future__ import annotations

from collections import defaultdict

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
    """No configurable parameters for this detector in this package."""


class ExactDuplicateRowsDetector:
    """`structural.exact_duplicate_rows` — flags rows that are byte-
    identical to another row in the dataset.

    One finding aggregates every duplicate group found (not one finding
    per group), with `affected_row_references` covering every row that
    belongs to any duplicate group (both the first-seen row and its
    duplicates) — a broader evidence scope than `PROF-03`'s
    `duplicate_row_count` metric, which counts only the "extra"
    occurrences. The finding's `calculated_observation` reports that
    metric's exact count for consistency.
    """

    metadata = DetectorMetadata(
        detector_id="structural.exact_duplicate_rows",
        version="1",
        name="Exact duplicate rows",
        category=DetectorCategory.STRUCTURAL,
        description="Flags rows that are byte-identical to another row in the dataset.",
        applicable_inferred_types=(),
        required_profile_fields=("dataset_metrics.duplicate_row_count",),
        requires_raw_rows=True,
        requires_confirmed_context=False,
        default_configuration={},
        performance_class=PerformanceClass.LINEAR_BY_ROW,
        documented_limitations=(
            "Only exact, byte-for-byte row duplicates are detected; near-duplicates "
            "(e.g. differing only by whitespace or capitalization) are out of scope.",
        ),
    )
    config_schema: type[BaseModel] = _EmptyConfig

    def supports(self, request: DetectorSupportRequest) -> bool:
        del request  # Dataset-level, structurally always applicable.
        return True

    def run(self, request: DetectorRunRequest) -> DetectorRunResult:
        groups: dict[tuple[tuple[str, object], ...], list[int]] = defaultdict(list)
        for index, row in enumerate(request.rows):
            key = tuple(sorted(row.items()))
            groups[key].append(index)

        duplicate_indices: list[int] = []
        group_count = 0
        for indices in groups.values():
            if len(indices) > 1:
                group_count += 1
                duplicate_indices.extend(indices)

        if not duplicate_indices:
            return DetectorRunResult(
                detector_id=self.metadata.detector_id,
                detector_version=self.metadata.version,
                status=DetectorRunStatus.SUCCESS,
                findings=(),
                evidence=(),
                warnings=(),
                execution_metrics=ExecutionMetrics(duration_ms=0),
            )

        duplicate_indices.sort()
        affected_row_references = tuple(request.row_references[i] for i in duplicate_indices)
        extra_row_count = len(duplicate_indices) - group_count

        evidence = Evidence(
            evidence_id="structural.exact_duplicate_rows.evidence.1",
            evidence_type=EvidenceType.ROW_SET,
            calculation_version="1",
            structured_payload={
                "duplicate_group_count": group_count,
                "duplicate_row_count": extra_row_count,
            },
            affected_columns=(),
            affected_row_references=affected_row_references,
            scope=SamplingScope.FULL,
            display_safe_summary=(
                f"Found {extra_row_count} exact duplicate row(s) across {group_count} group(s)."
            ),
        )
        finding = FindingCandidate(
            detector_id=self.metadata.detector_id,
            detector_version=self.metadata.version,
            category=self.metadata.category,
            severity=Severity.MEDIUM,
            confidence=1.0,
            calculated_observation=(
                f"{extra_row_count} row(s) are exact duplicates of another row "
                f"({group_count} duplicate group(s))."
            ),
            affected_columns=(),
            affected_row_references=affected_row_references,
            evidence_ids=(evidence.evidence_id,),
            default_remediation_template_key=None,
            default_validation_rule_template_key=None,
        )
        return DetectorRunResult(
            detector_id=self.metadata.detector_id,
            detector_version=self.metadata.version,
            status=DetectorRunStatus.SUCCESS,
            findings=(finding,),
            evidence=(evidence,),
            warnings=(),
            execution_metrics=ExecutionMetrics(duration_ms=0),
        )


class EmptyColumnDetector:
    """`structural.empty_column` — flags columns that contain no
    non-blank values in any sampled row.

    Does not declare `requires_raw_rows`: `PROF-02`'s `UNKNOWN`
    classification already exactly means "zero non-blank values" (a
    direct code-level fact, not an approximation), so the already-
    computed profile alone is sufficient evidence.
    """

    metadata = DetectorMetadata(
        detector_id="structural.empty_column",
        version="1",
        name="Empty column",
        category=DetectorCategory.STRUCTURAL,
        description="Flags columns that contain no non-blank values in any sampled row.",
        applicable_inferred_types=(InferredColumnType.UNKNOWN,),
        required_profile_fields=("column_profiles[].inferred_type",),
        requires_raw_rows=False,
        requires_confirmed_context=False,
        default_configuration={},
        performance_class=PerformanceClass.CONSTANT_OR_METADATA_ONLY,
        documented_limitations=(),
    )
    config_schema: type[BaseModel] = _EmptyConfig

    def supports(self, request: DetectorSupportRequest) -> bool:
        del request  # Dataset-level, structurally always applicable.
        return True

    def run(self, request: DetectorRunRequest) -> DetectorRunResult:
        findings: list[FindingCandidate] = []
        evidence: list[Evidence] = []

        for profile in request.dataset_profile.column_profiles:
            if profile.inferred_type is not InferredColumnType.UNKNOWN:
                continue

            evidence_id = f"structural.empty_column.evidence.{profile.column.internal_key}"
            column_evidence = Evidence(
                evidence_id=evidence_id,
                evidence_type=EvidenceType.METRIC,
                calculation_version="1",
                structured_payload={"null_count": profile.null_count},
                affected_columns=(profile.column,),
                affected_row_references=(),
                scope=SamplingScope.FULL,
                display_safe_summary=(
                    f"Column '{profile.column.original_name}' has no non-blank values."
                ),
            )
            finding = FindingCandidate(
                detector_id=self.metadata.detector_id,
                detector_version=self.metadata.version,
                category=self.metadata.category,
                severity=Severity.MEDIUM,
                confidence=1.0,
                calculated_observation=(
                    f"Column '{profile.column.original_name}' is empty in all sampled rows."
                ),
                affected_columns=(profile.column,),
                affected_row_references=(),
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
