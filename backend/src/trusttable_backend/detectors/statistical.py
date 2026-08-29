"""Statistical detectors (`DET-02` final), matching
`docs/detector-framework.md` §16's "Statistical" category: suspiciously
constant columns and extreme outliers. The first detectors in the
`STATISTICAL` category (`docs/detector-framework.md` §4).

`SuspiciouslyConstantColumnDetector` relies entirely on `PROF-02`'s
already-computed `distinct_count`/`null_count` (no raw-row access
needed), following `structural.empty_column`'s established
metadata-only pattern. `ExtremeOutliersDetector` reuses `PROF-03`'s
already-computed `q1`/`q3`/`iqr` numeric metrics to recompute the
identical Tukey 1.5x-IQR fence used to produce `extreme_count`, then
scans raw rows to identify which rows are affected — mirroring
`negative_likely_non_negative_values`'s "reuse a metric to decide
eligibility, then scan rows for evidence" pattern.

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


_MIN_NON_BLANK_FOR_CONSTANT = 2
"""`SuspiciouslyConstantColumnDetector` requires at least this many
non-blank sampled values before firing, matching `PROF-03`'s own
`_LIKELY_IDENTIFIER_MIN_VALUES` precedent reasoning: a single non-blank
value is a sparsity signal (e.g. `notes` in the `DEMO-01` demo dataset,
blank in 299/300 rows), not a genuine "no variance" signal."""

_EXTREME_FENCE_MULTIPLIER = 1.5
"""Matches `profiling.metrics`'s own `_EXTREME_FENCE_MULTIPLIER` exactly
(a standard Tukey fence) — duplicated across the module boundary rather
than importing a private `profiling.metrics` symbol, the same pattern
already used for other cross-module threshold constants in this
codebase."""


class SuspiciouslyConstantColumnDetector:
    """`statistical.suspiciously_constant_column` — flags any non-
    `UNKNOWN`-typed column where every non-blank sampled value is
    identical.

    Does not declare `requires_raw_rows`: `PROF-02`'s already-computed
    `distinct_count`/`null_count` are sufficient evidence, matching
    `structural.empty_column`'s exact precedent. `UNKNOWN`-typed columns
    (zero non-blank values) are excluded — that is
    `structural.empty_column`'s territory, not a "constant" signal.
    """

    metadata = DetectorMetadata(
        detector_id="statistical.suspiciously_constant_column",
        version="1",
        name="Suspiciously constant column",
        category=DetectorCategory.STATISTICAL,
        description="Flags columns where every non-blank sampled value is identical.",
        applicable_inferred_types=(),
        required_profile_fields=(
            "column_profiles[].inferred_type",
            "column_profiles[].distinct_count",
            "column_profiles[].null_count",
        ),
        requires_raw_rows=False,
        requires_confirmed_context=False,
        default_configuration={},
        performance_class=PerformanceClass.CONSTANT_OR_METADATA_ONLY,
        documented_limitations=(
            "Requires at least two non-blank sampled values to fire; a column with "
            "exactly one non-blank value (sparse, not constant) is not flagged.",
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

        for profile in request.dataset_profile.column_profiles:
            if profile.inferred_type is InferredColumnType.UNKNOWN:
                continue

            non_null_count = sample_size - profile.null_count
            if non_null_count < _MIN_NON_BLANK_FOR_CONSTANT:
                continue
            if profile.distinct_count != 1:
                continue

            evidence_id = (
                f"statistical.suspiciously_constant_column.evidence.{profile.column.internal_key}"
            )
            column_evidence = Evidence(
                evidence_id=evidence_id,
                evidence_type=EvidenceType.METRIC,
                calculation_version="1",
                structured_payload={"non_null_count": non_null_count},
                affected_columns=(profile.column,),
                affected_row_references=(),
                scope=SamplingScope.FULL,
                display_safe_summary=(
                    f"Column '{profile.column.original_name}' holds the same value "
                    f"in all {non_null_count} non-blank sampled row(s)."
                ),
            )
            finding = FindingCandidate(
                detector_id=self.metadata.detector_id,
                detector_version=self.metadata.version,
                category=self.metadata.category,
                severity=Severity.MEDIUM,
                confidence=1.0,
                calculated_observation=(
                    f"Column '{profile.column.original_name}' holds the same value "
                    f"in all {non_null_count} non-blank sampled row(s)."
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


class ExtremeOutliersDetector:
    """`statistical.extreme_outliers` — flags `NUMERIC`-typed columns
    with one or more values outside a Tukey `1.5x`-IQR fence
    (`[q1 - 1.5*iqr, q3 + 1.5*iqr]`).

    Reuses `PROF-03`'s already-computed `extreme_count` metric to decide
    whether a column has any candidate values, and `q1`/`q3`/`iqr` to
    recompute the identical fence when scanning raw rows for the
    specific affected indices.
    """

    metadata = DetectorMetadata(
        detector_id="statistical.extreme_outliers",
        version="1",
        name="Extreme outliers",
        category=DetectorCategory.STATISTICAL,
        description=(
            "Flags numeric columns containing values far outside the normal range, "
            "using a Tukey 1.5x-IQR fence."
        ),
        applicable_inferred_types=(InferredColumnType.NUMERIC,),
        required_profile_fields=(
            "column_profiles[].inferred_type",
            "column_profiles[].metrics.extreme_count",
            "column_profiles[].metrics.q1",
            "column_profiles[].metrics.q3",
            "column_profiles[].metrics.iqr",
        ),
        requires_raw_rows=True,
        requires_confirmed_context=False,
        default_configuration={},
        performance_class=PerformanceClass.LINEAR_BY_ROW,
        documented_limitations=(
            "An extreme value may be a legitimate rare business event rather than an "
            "error; confidence is lowered to reflect this.",
            "A fixed 1.5x-IQR Tukey fence assumes a roughly symmetric distribution; a "
            "right-skewed measure (e.g. a multiplicative value like a line total) can "
            "have a natural upper tail that legitimately crosses the fence, producing "
            "more findings than a symmetric distribution would for the same column — "
            "a property of the method, not a defect (verified against the real demo "
            "dataset's 'line_total' column, which fires on this basis).",
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
            if profile.inferred_type is not InferredColumnType.NUMERIC:
                continue

            extreme_count = profile.metrics.get("extreme_count")
            if not isinstance(extreme_count, int) or extreme_count <= 0:
                continue
            q1 = profile.metrics.get("q1")
            q3 = profile.metrics.get("q3")
            iqr = profile.metrics.get("iqr")
            if not all(isinstance(value, (int, float)) for value in (q1, q3, iqr)):
                continue
            assert isinstance(q1, (int, float))
            assert isinstance(q3, (int, float))
            assert isinstance(iqr, (int, float))
            lower_fence = q1 - _EXTREME_FENCE_MULTIPLIER * iqr
            upper_fence = q3 + _EXTREME_FENCE_MULTIPLIER * iqr

            affected_indices: list[int] = []
            for index, row in enumerate(request.rows):
                value = row.get(profile.column.internal_key)
                if not isinstance(value, str) or not value:
                    continue
                try:
                    parsed_value = float(value.strip())
                except ValueError:
                    continue
                if parsed_value < lower_fence or parsed_value > upper_fence:
                    affected_indices.append(index)

            if not affected_indices:
                continue

            affected_row_references = tuple(
                request.row_references[index] for index in affected_indices
            )
            evidence_id = f"statistical.extreme_outliers.evidence.{profile.column.internal_key}"
            column_evidence = Evidence(
                evidence_id=evidence_id,
                evidence_type=EvidenceType.ROW_SET,
                calculation_version="1",
                structured_payload={
                    "lower_fence": lower_fence,
                    "upper_fence": upper_fence,
                    "outlier_count": len(affected_indices),
                },
                affected_columns=(profile.column,),
                affected_row_references=affected_row_references,
                scope=SamplingScope.FULL,
                display_safe_summary=(
                    f"Column '{profile.column.original_name}' has "
                    f"{len(affected_indices)} value(s) outside the normal range."
                ),
            )
            finding = FindingCandidate(
                detector_id=self.metadata.detector_id,
                detector_version=self.metadata.version,
                category=self.metadata.category,
                severity=Severity.MEDIUM,
                confidence=0.7,
                calculated_observation=(
                    f"Column '{profile.column.original_name}' has "
                    f"{len(affected_indices)} value(s) outside the normal "
                    f"[{lower_fence:.2f}, {upper_fence:.2f}] range."
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
