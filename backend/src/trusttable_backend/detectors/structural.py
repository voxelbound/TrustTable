"""Structural detectors (`DET-02` partial, `DET-03` slice 4 and `DET-03`
closure package 1), matching `docs/detector-framework.md` §16's
"Structural" category: exact duplicate rows, empty columns, duplicate
normalized column names, an empty dataset, unnamed columns and excessive
parse failures.

The last two read only the in-memory `IngestFacts` projection of four
parser warnings (`domain/ingest_facts.py`), behind
`DetectorMetadata.requires_ingest_facts`; they never see a parser message
or a cell value, and they are skipped when no facts are supplied.

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

from pydantic import BaseModel, ConfigDict, Field

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
#: Unicode general-category first letters kept in a name key: Letter, Number, Mark.
_KEPT_CATEGORIES: Final[str] = "LNM"


def _column_name_key(name: str) -> tuple[bool, str]:
    """The comparison key for a column name: compatibility-composed, casefolded
    and reduced to its letters, digits and combining marks (any script).

    Deliberately *not* the CSV parser's ASCII-only internal key, which maps
    every non-Latin character to `_` and would make unrelated non-Latin names
    collide. Combining marks are kept because in many scripts (for example
    Devanagari vowel signs, Thai tone marks, Arabic diacritics) they cannot be
    composed into a base letter and they distinguish one name from another;
    only punctuation, symbols, separators and control characters are dropped.
    A name with no letter, digit or mark at all (for example `?`) keeps its
    exact text as the key, so only identical names group. Linear in the name
    length; no regular expression runs over the (untrusted) name.
    """
    folded = unicodedata.normalize("NFKC", name).casefold()
    reduced = "".join(
        character for character in folded if unicodedata.category(character)[0] in _KEPT_CATEGORIES
    )
    if reduced:
        return (True, reduced)
    return (False, name)


class DuplicateNormalizedColumnNameDetector:
    """`structural.duplicate_normalized_column_name` — flags two or more
    columns whose names are the same once case, spacing and punctuation are
    ignored (for example `Order ID` and `order_id`), one finding per group.
    Names are compared by letters, digits and combining marks in any script
    (see `_column_name_key`).

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


def _no_findings(metadata: DetectorMetadata) -> DetectorRunResult:
    return DetectorRunResult(
        detector_id=metadata.detector_id,
        detector_version=metadata.version,
        status=DetectorRunStatus.SUCCESS,
        findings=(),
        evidence=(),
        warnings=(),
        execution_metrics=ExecutionMetrics(duration_ms=0),
    )


def _profile_row_count(request: DetectorRunRequest | DetectorSupportRequest) -> int:
    """The number of data rows the profile was computed over.

    Prefers the profile's own `row_count` metric and falls back to the
    sampling population. `bool` is excluded on purpose: it is an `int`
    subclass and must never be read as a count.
    """
    profile = request.dataset_profile
    value = profile.dataset_metrics.get("row_count")
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return profile.sampling.population_size


class EmptyDatasetDetector:
    """`structural.empty_dataset` — flags a dataset that has a header but no
    data rows (`DET-03` closure package 1).

    The zero-row investigation found that the parsers accept a header-only
    CSV or worksheet (row count zero, no warning), profiling computes an
    all-unknown profile without error, and no stage before detection stops
    the run, so detector execution is the correct owner of this case. Without
    this detector the only signal was one misleading "column is empty in all
    sampled rows" finding per column. One dataset-level finding states the
    actual condition. It reads only the profile's row count, never a cell.
    """

    metadata = DetectorMetadata(
        detector_id="structural.empty_dataset",
        version="1",
        name="Empty dataset",
        category=DetectorCategory.STRUCTURAL,
        description="Flags a dataset that has a header but no data rows.",
        applicable_inferred_types=(),
        required_profile_fields=("dataset_metrics.row_count",),
        requires_raw_rows=False,
        requires_confirmed_context=False,
        default_configuration={},
        performance_class=PerformanceClass.CONSTANT_OR_METADATA_ONLY,
        documented_limitations=(
            "A file with no content at all, or a worksheet with no header row, is "
            "refused by the parser before detection and never reaches this detector.",
            "A dataset whose only data rows are blank still has rows; "
            "completeness.fully_empty_rows covers that case.",
        ),
    )
    config_schema: type[BaseModel] = _EmptyConfig

    def supports(self, request: DetectorSupportRequest) -> bool:
        del request  # Dataset-level, structurally always applicable.
        return True

    def run(self, request: DetectorRunRequest) -> DetectorRunResult:
        if _profile_row_count(request) != 0:
            return _no_findings(self.metadata)

        column_count = len(request.dataset_profile.column_profiles)
        evidence_id = "structural.empty_dataset.evidence.1"
        evidence = Evidence(
            evidence_id=evidence_id,
            evidence_type=EvidenceType.METRIC,
            calculation_version="1",
            structured_payload={"row_count": 0, "column_count": column_count},
            affected_columns=(),
            affected_row_references=(),
            scope=SamplingScope.FULL,
            display_safe_summary=(
                f"The dataset has {column_count} column(s) in its header and no data rows."
            ),
        )
        finding = FindingCandidate(
            detector_id=self.metadata.detector_id,
            detector_version=self.metadata.version,
            category=self.metadata.category,
            severity=Severity.HIGH,
            confidence=1.0,
            calculated_observation=(
                "The dataset has a header but no data rows, so there is nothing to analyze."
            ),
            affected_columns=(),
            affected_row_references=(),
            evidence_ids=(evidence_id,),
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


class UnnamedColumnDetector:
    """`structural.unnamed_column` — flags header cells that were blank
    (`DET-03` closure package 1).

    Reads only the `IngestFacts` projection of `parsing.empty_column_name`:
    a count and at most `MAX_REFERENCES` example columns. Each blank header is
    seen by every other detector under the parser-assigned `column_<n>`
    placeholder, which is also what this finding names; the original header
    cell was empty, so no user text is repeated. A header made only of spaces
    is a name to the parser and is not flagged. One finding covers every
    unnamed column.
    """

    metadata = DetectorMetadata(
        detector_id="structural.unnamed_column",
        version="1",
        name="Unnamed column",
        category=DetectorCategory.STRUCTURAL,
        description="Flags columns whose header cell is blank.",
        applicable_inferred_types=(),
        required_profile_fields=(),
        requires_raw_rows=False,
        requires_confirmed_context=False,
        default_configuration={},
        performance_class=PerformanceClass.CONSTANT_OR_METADATA_ONLY,
        documented_limitations=(
            "A header cell holding only whitespace counts as a name and is not flagged.",
            "Only up to 20 example columns are listed; the count is exact.",
        ),
        requires_ingest_facts=True,
    )
    config_schema: type[BaseModel] = _EmptyConfig

    def supports(self, request: DetectorSupportRequest) -> bool:
        return request.ingest_facts is not None

    def run(self, request: DetectorRunRequest) -> DetectorRunResult:
        facts = request.ingest_facts
        if facts is None or facts.unnamed_column_count == 0:
            return _no_findings(self.metadata)

        columns = facts.unnamed_columns
        shown = ", ".join(
            f"'{column.original_name[:_MAX_NAME_DISPLAY]}'" for column in columns[:_MAX_NAMES_SHOWN]
        )
        if facts.unnamed_column_count > min(len(columns), _MAX_NAMES_SHOWN):
            shown += f" and {facts.unnamed_column_count - min(len(columns), _MAX_NAMES_SHOWN)} more"
        evidence_id = "structural.unnamed_column.evidence.1"
        evidence = Evidence(
            evidence_id=evidence_id,
            evidence_type=EvidenceType.METRIC,
            calculation_version="1",
            structured_payload={
                "unnamed_column_count": facts.unnamed_column_count,
                "column_count": facts.column_count,
                "ordinals": [column.ordinal for column in columns],
            },
            affected_columns=columns,
            affected_row_references=(),
            scope=SamplingScope.FULL,
            display_safe_summary=(
                f"{facts.unnamed_column_count} of {facts.column_count} column(s) have a blank "
                f"header cell and were given placeholder names: {shown}."
            ),
        )
        finding = FindingCandidate(
            detector_id=self.metadata.detector_id,
            detector_version=self.metadata.version,
            category=self.metadata.category,
            severity=Severity.MEDIUM,
            confidence=1.0,
            calculated_observation=(
                f"{facts.unnamed_column_count} of {facts.column_count} column(s) have no header "
                f"name and were given placeholder names: {shown}."
            ),
            affected_columns=columns,
            affected_row_references=(),
            evidence_ids=(evidence_id,),
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


class _ExcessiveParseFailuresConfig(BaseModel):
    """Thresholds for `structural.excessive_parse_failures`.

    A finding needs the share to reach the ratio *and* the count to reach
    `minimum_count`, so one stray blank line in a short file is not enough.
    """

    model_config = ConfigDict(extra="forbid")

    row_ratio_threshold: float = Field(default=0.05, gt=0.0, le=1.0, allow_inf_nan=False)
    cell_ratio_threshold: float = Field(default=0.05, gt=0.0, le=1.0, allow_inf_nan=False)
    minimum_count: int = Field(default=5, ge=1)


#: At or above this share the finding is HIGH rather than MEDIUM.
_HIGH_SEVERITY_RATIO: Final[float] = 0.5


class ExcessiveParseFailuresDetector:
    """`structural.excessive_parse_failures` — flags a file in which an
    excessive share of rows or cells could not be read as intended
    (`DET-03` closure package 1).

    Two measures, both from the `IngestFacts` projection and both exact:

    - rows that did not have the header's number of fields
      (`parsing.ragged_row`), as a share of data rows;
    - cells that were read as empty because a formula had no stored result
      (`parsing.xlsx_formula_without_cached_value`) or that held a
      spreadsheet error value (`parsing.xlsx_error_value`), as a share of all
      data cells (`rows x columns`).

    A finding needs a share at or above its configured ratio **and** at least
    `minimum_count` affected items. Truncation caused by a TrustTable
    processing limit (long values or names) is not one of the four projected
    codes and can never count: it is not a defect in the user's data. A CSV
    blank line is read by the parser as a ragged row, so blank lines count
    here as well as under `completeness.fully_empty_rows`; the count floor
    keeps a few trailing blank lines from firing it. One finding covers both
    measures; its row references are the bounded ragged-row examples.
    """

    metadata = DetectorMetadata(
        detector_id="structural.excessive_parse_failures",
        version="1",
        name="Excessive parse failures",
        category=DetectorCategory.STRUCTURAL,
        description=(
            "Flags a file where an excessive share of rows had the wrong number of fields or "
            "of cells could not be read as values."
        ),
        applicable_inferred_types=(),
        required_profile_fields=(),
        requires_raw_rows=False,
        requires_confirmed_context=False,
        default_configuration={
            "row_ratio_threshold": 0.05,
            "cell_ratio_threshold": 0.05,
            "minimum_count": 5,
        },
        performance_class=PerformanceClass.CONSTANT_OR_METADATA_ONLY,
        documented_limitations=(
            "Truncation caused by a TrustTable processing limit is never counted.",
            "A blank CSV line counts as a ragged row; a few such lines stay below the "
            "minimum count.",
            "Only up to 20 example rows are referenced; the counts are exact.",
        ),
        requires_ingest_facts=True,
    )
    config_schema: type[BaseModel] = _ExcessiveParseFailuresConfig

    def supports(self, request: DetectorSupportRequest) -> bool:
        return request.ingest_facts is not None

    def run(self, request: DetectorRunRequest) -> DetectorRunResult:
        facts = request.ingest_facts
        if facts is None or facts.row_count == 0:
            return _no_findings(self.metadata)

        row_threshold = float(request.configuration["row_ratio_threshold"])  # type: ignore[arg-type]
        cell_threshold = float(request.configuration["cell_ratio_threshold"])  # type: ignore[arg-type]
        minimum = int(request.configuration["minimum_count"])  # type: ignore[call-overload]

        ragged = facts.ragged_row_count
        unreadable_cells = (
            facts.formula_without_cached_value_cell_count + facts.error_value_cell_count
        )
        total_cells = facts.row_count * max(facts.column_count, 1)
        row_ratio = min(ragged / facts.row_count, 1.0)
        cell_ratio = min(unreadable_cells / total_cells, 1.0)
        row_hit = ragged >= minimum and row_ratio >= row_threshold
        cell_hit = unreadable_cells >= minimum and cell_ratio >= cell_threshold
        if not (row_hit or cell_hit):
            return _no_findings(self.metadata)

        parts: list[str] = []
        if row_hit:
            parts.append(
                f"{ragged} of {facts.row_count} data row(s) did not have the header's "
                "number of fields"
            )
        if cell_hit:
            parts.append(
                f"{unreadable_cells} of {total_cells} cell(s) could not be read as values "
                f"({facts.formula_without_cached_value_cell_count} formula(s) without a stored "
                f"result, {facts.error_value_cell_count} spreadsheet error value(s))"
            )
        observation = "; ".join(parts) + "."
        worst = max(row_ratio if row_hit else 0.0, cell_ratio if cell_hit else 0.0)
        row_references = facts.ragged_rows if row_hit else ()

        evidence_id = "structural.excessive_parse_failures.evidence.1"
        evidence = Evidence(
            evidence_id=evidence_id,
            evidence_type=EvidenceType.METRIC,
            calculation_version="1",
            structured_payload={
                "row_count": facts.row_count,
                "column_count": facts.column_count,
                "ragged_row_count": ragged,
                "ragged_row_ratio": round(row_ratio, 4),
                "unreadable_cell_count": unreadable_cells,
                "formula_without_cached_value_cell_count": (
                    facts.formula_without_cached_value_cell_count
                ),
                "error_value_cell_count": facts.error_value_cell_count,
                "unreadable_cell_ratio": round(cell_ratio, 4),
                "row_ratio_threshold": row_threshold,
                "cell_ratio_threshold": cell_threshold,
                "minimum_count": minimum,
            },
            affected_columns=(),
            affected_row_references=row_references,
            scope=SamplingScope.FULL,
            display_safe_summary=observation,
        )
        finding = FindingCandidate(
            detector_id=self.metadata.detector_id,
            detector_version=self.metadata.version,
            category=self.metadata.category,
            severity=Severity.HIGH if worst >= _HIGH_SEVERITY_RATIO else Severity.MEDIUM,
            confidence=1.0,
            calculated_observation=observation,
            affected_columns=(),
            affected_row_references=row_references,
            evidence_ids=(evidence_id,),
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
