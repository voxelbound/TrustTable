"""Structural detectors (`DET-02` partial, plus `DET-03` slice 4), matching
`docs/detector-framework.md` §16's "Structural" category: exact
duplicate rows, empty columns and duplicate normalized column names.

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

import unicodedata
from collections import defaultdict
from typing import Final

from pydantic import BaseModel

from ..domain.evidence import Evidence, EvidenceType
from ..domain.parsing import SamplingScope
from ..domain.value_objects import ColumnReference, Severity
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


_MAX_NAMES_SHOWN: Final[int] = 5
_MAX_NAME_DISPLAY: Final[int] = 60


def _column_name_key(name: str) -> tuple[bool, str]:
    """The comparison key for a column name: compatibility-composed, casefolded
    and reduced to its letters and digits (any script).

    Deliberately *not* the CSV parser's ASCII-only internal key, which maps
    every non-Latin character to `_` and would make unrelated non-Latin names
    collide. A name with no letter or digit at all (for example `?`) keeps
    its exact text as the key, so only identical names group. Linear in the
    name length; no regular expression runs over the (untrusted) name.
    """
    folded = unicodedata.normalize("NFKC", name).casefold()
    reduced = "".join(character for character in folded if character.isalnum())
    if reduced:
        return (True, reduced)
    return (False, name)


class DuplicateNormalizedColumnNameDetector:
    """`structural.duplicate_normalized_column_name` — flags two or more
    columns whose names are the same once case, spacing and punctuation are
    ignored (for example `Order ID` and `order_id`), one finding per group.

    Reads column names only (never a cell value) from the profile. A blank
    header reaches the profile as the parser-assigned `column_<n>` name, so
    it can only collide with a real header of that exact shape; blank
    headers themselves belong to the later unnamed-column detector, which
    needs the ingest-facts record.
    """

    metadata = DetectorMetadata(
        detector_id="structural.duplicate_normalized_column_name",
        version="1",
        name="Duplicate normalized column name",
        category=DetectorCategory.STRUCTURAL,
        description=(
            "Flags columns whose names are the same once case, spacing and punctuation are ignored."
        ),
        applicable_inferred_types=(),
        required_profile_fields=("column_profiles[].column.original_name",),
        requires_raw_rows=False,
        requires_confirmed_context=False,
        default_configuration={},
        performance_class=PerformanceClass.CONSTANT_OR_METADATA_ONLY,
        documented_limitations=(
            "Only names are compared; two columns with the same name can still hold "
            "different data, and different names can hold the same data.",
            "A blank header is seen under its parser-assigned column_<n> name.",
        ),
    )
    config_schema: type[BaseModel] = _EmptyConfig

    def supports(self, request: DetectorSupportRequest) -> bool:
        del request  # Dataset-level, structurally always applicable.
        return True

    def run(self, request: DetectorRunRequest) -> DetectorRunResult:
        groups: dict[tuple[bool, str], list[ColumnReference]] = {}
        for profile in request.dataset_profile.column_profiles:
            groups.setdefault(_column_name_key(profile.column.original_name), []).append(
                profile.column
            )

        findings: list[FindingCandidate] = []
        evidence: list[Evidence] = []
        for columns in groups.values():
            if len(columns) < 2:
                continue
            shown = ", ".join(
                f"'{column.original_name[:_MAX_NAME_DISPLAY]}'"
                for column in columns[:_MAX_NAMES_SHOWN]
            )
            if len(columns) > _MAX_NAMES_SHOWN:
                shown += f" and {len(columns) - _MAX_NAMES_SHOWN} more"
            identical = len({column.original_name for column in columns}) == 1
            evidence_id = (
                f"structural.duplicate_normalized_column_name.evidence.{columns[0].internal_key}"
            )
            evidence.append(
                Evidence(
                    evidence_id=evidence_id,
                    evidence_type=EvidenceType.METRIC,
                    calculation_version="1",
                    structured_payload={
                        "column_count": len(columns),
                        "ordinals": [column.ordinal for column in columns],
                        "identical_as_written": identical,
                    },
                    affected_columns=tuple(columns),
                    affected_row_references=(),
                    scope=SamplingScope.FULL,
                    display_safe_summary=(
                        f"{len(columns)} columns share one name once case, spacing and "
                        f"punctuation are ignored: {shown}."
                    ),
                )
            )
            findings.append(
                FindingCandidate(
                    detector_id=self.metadata.detector_id,
                    detector_version=self.metadata.version,
                    category=self.metadata.category,
                    severity=Severity.MEDIUM,
                    confidence=1.0 if identical else 0.9,
                    calculated_observation=(
                        f"{len(columns)} columns have the same name once case, spacing and "
                        f"punctuation are ignored: {shown}."
                    ),
                    affected_columns=tuple(columns),
                    affected_row_references=(),
                    evidence_ids=(evidence_id,),
                    default_remediation_template_key=None,
                    default_validation_rule_template_key=None,
                )
            )

        return DetectorRunResult(
            detector_id=self.metadata.detector_id,
            detector_version=self.metadata.version,
            status=DetectorRunStatus.SUCCESS,
            findings=tuple(findings),
            evidence=tuple(evidence),
            warnings=(),
            execution_metrics=ExecutionMetrics(duration_ms=0),
        )


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
