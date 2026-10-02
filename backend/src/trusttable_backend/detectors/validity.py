"""Validity detectors (`DET-02` partial), matching
`docs/detector-framework.md` §16's "Validity" category: future dates,
negative likely non-negative values, and invalid percentages.

`FutureDatesDetector` recomputes future-date membership fresh from the
detector's own `analysis_timestamp` rather than reusing `PROF-03`'s
`future_date_count` metric: that metric's `as_of` parameter is fixed at
profiling time and could be stale relative to a later detector run.
`NegativeLikelyNonNegativeValuesDetector` reuses `PROF-03`'s
already-computed `negative_count` metric to decide *whether* a column
qualifies (no equivalent staleness concern — it is a plain count, not
time-relative), and uses `confidence=0.7` rather than the `1.0` used by
every deterministic detector in prior `DET-02` sub-packages: a negative
value in an otherwise-non-negative column is very likely an error, but
could be a legitimate return/adjustment without confirmed business
context, per `docs/detector-framework.md` §12's own worked example
("context-dependent negative quantity without confirmed return
semantics: lower confidence"). `InvalidPercentagesDetector` identifies
candidate columns via a column-name heuristic (no confirmed column-role
context, `CTX-01`, exists yet) and scans raw rows directly (like
`FutureDatesDetector`, not reusing a `PROF-03` metric) for values outside
the valid `[0, 100]` percentage range.

Framework-independent per `docs/architecture.md` §3's "Detectors" layer
rule ("detector modules do not import FastAPI"); `pydantic.BaseModel` is
used only for each detector's (currently empty) `config_schema`.
"""

from __future__ import annotations

from datetime import date

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


_NEGATIVE_MINORITY_RATIO = 0.10
"""A `NUMERIC` column's negative values are treated as likely errors when
they make up less than this fraction of its non-blank values. A
disclosed, reversible design choice (`docs/detector-framework.md` §11
requires an explicit rule but fixes no exact number) — chosen so a
column where negatives are a normal, substantial part of the
distribution (e.g. a genuine balance/delta column) does not fire, while
a column where negatives are rare (as in every real-file case in the
`DEMO-01` demo dataset, all under 2%) does."""


class FutureDatesDetector:
    """`validity.future_dates` — flags `DATE`-typed columns containing
    one or more values later than the detector's own
    `analysis_timestamp`.

    Does not distinguish column semantics (an order date being in the
    future is suspicious; a due/renewal date might not be) — a disclosed
    limitation, since no confirmed-context type (`CTX-01`) exists yet to
    supply that distinction.
    """

    metadata = DetectorMetadata(
        detector_id="validity.future_dates",
        version="1",
        name="Future dates",
        category=DetectorCategory.VALIDITY,
        description="Flags date columns containing one or more values in the future.",
        applicable_inferred_types=(InferredColumnType.DATE,),
        required_profile_fields=("column_profiles[].inferred_type",),
        requires_raw_rows=True,
        requires_confirmed_context=False,
        default_configuration={},
        performance_class=PerformanceClass.LINEAR_BY_ROW,
        documented_limitations=(
            "Does not distinguish column semantics; a legitimately future-oriented "
            "date column (e.g. a due date) would still be flagged.",
        ),
    )
    config_schema: type[BaseModel] = _EmptyConfig

    def supports(self, request: DetectorSupportRequest) -> bool:
        del request  # Dataset-level, structurally always applicable.
        return True

    def run(self, request: DetectorRunRequest) -> DetectorRunResult:
        reference_date = request.analysis_timestamp.date()
        findings: list[FindingCandidate] = []
        evidence: list[Evidence] = []

        for profile in request.dataset_profile.column_profiles:
            if profile.inferred_type is not InferredColumnType.DATE:
                continue

            affected_indices: list[int] = []
            for index, row in enumerate(request.rows):
                value = row.get(profile.column.internal_key)
                if not isinstance(value, str) or not value:
                    continue
                try:
                    parsed = date.fromisoformat(value.strip())
                except ValueError:
                    continue
                if parsed > reference_date:
                    affected_indices.append(index)

            if not affected_indices:
                continue

            affected_row_references = tuple(
                request.row_references[index] for index in affected_indices
            )
            evidence_id = f"validity.future_dates.evidence.{profile.column.internal_key}"
            column_evidence = Evidence(
                evidence_id=evidence_id,
                evidence_type=EvidenceType.ROW_SET,
                calculation_version="1",
                structured_payload={
                    "reference_date": reference_date.isoformat(),
                    "future_date_count": len(affected_indices),
                },
                affected_columns=(profile.column,),
                affected_row_references=affected_row_references,
                scope=SamplingScope.FULL,
                display_safe_summary=(
                    f"Column '{profile.column.original_name}' has "
                    f"{len(affected_indices)} value(s) later than {reference_date.isoformat()}."
                ),
            )
            finding = FindingCandidate(
                detector_id=self.metadata.detector_id,
                detector_version=self.metadata.version,
                category=self.metadata.category,
                severity=Severity.MEDIUM,
                confidence=1.0,
                calculated_observation=(
                    f"Column '{profile.column.original_name}' has "
                    f"{len(affected_indices)} value(s) later than {reference_date.isoformat()}."
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


_EARLIEST_PLAUSIBLE_DATE = date(1900, 1, 1)
"""Dates strictly before this are flagged `implausibly_old_dates`. A
disclosed, reversible design choice (`docs/detector-framework.md` §11
requires an explicit rule but fixes no exact number): it catches the usual
placeholder and typo dates (`0001-01-01`, `1000-01-01`) while leaving
ordinary business history alone. A genuinely historical dataset can hold
real earlier dates, which the detector's documented limitations state."""


class ImplausiblyOldDatesDetector:
    """`validity.implausibly_old_dates` — flags `DATE`-typed columns holding
    ISO dates strictly before `_EARLIEST_PLAUSIBLE_DATE` (`DET-03` slice 2).

    Dates this old are most often placeholders or typing errors, and they
    distort ages, durations and time-based grouping. Only the cutoff date
    and the oldest date found are recorded, never a row's other content.
    """

    metadata = DetectorMetadata(
        detector_id="validity.implausibly_old_dates",
        version="1",
        name="Implausibly old dates",
        category=DetectorCategory.VALIDITY,
        description="Flags date columns containing dates before 1900-01-01.",
        applicable_inferred_types=(InferredColumnType.DATE,),
        required_profile_fields=("column_profiles[].inferred_type",),
        requires_raw_rows=True,
        requires_confirmed_context=False,
        default_configuration={},
        performance_class=PerformanceClass.LINEAR_BY_ROW,
        documented_limitations=(
            "The cutoff is a fixed 1900-01-01; a genuinely historical dataset (archives, "
            "genealogy) can hold real dates before it and would be flagged.",
            "Only ISO dates (YYYY-MM-DD) are read; other formats are not checked.",
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
            if profile.inferred_type is not InferredColumnType.DATE:
                continue

            affected_indices: list[int] = []
            oldest: date | None = None
            for index, row in enumerate(request.rows):
                value = row.get(profile.column.internal_key)
                if not isinstance(value, str) or not value.strip():
                    continue
                try:
                    parsed = date.fromisoformat(value.strip())
                except ValueError:
                    continue
                if parsed < _EARLIEST_PLAUSIBLE_DATE:
                    affected_indices.append(index)
                    oldest = parsed if oldest is None else min(oldest, parsed)

            if not affected_indices or oldest is None:
                continue

            affected_row_references = tuple(
                request.row_references[index] for index in affected_indices
            )
            evidence_id = f"validity.implausibly_old_dates.evidence.{profile.column.internal_key}"
            cutoff = _EARLIEST_PLAUSIBLE_DATE.isoformat()
            column_evidence = Evidence(
                evidence_id=evidence_id,
                evidence_type=EvidenceType.ROW_SET,
                calculation_version="1",
                structured_payload={
                    "earliest_plausible_date": cutoff,
                    "old_date_count": len(affected_indices),
                    "oldest_date_found": oldest.isoformat(),
                },
                affected_columns=(profile.column,),
                affected_row_references=affected_row_references,
                scope=SamplingScope.FULL,
                display_safe_summary=(
                    f"Column '{profile.column.original_name}' has {len(affected_indices)} "
                    f"date(s) before {cutoff}."
                ),
            )
            finding = FindingCandidate(
                detector_id=self.metadata.detector_id,
                detector_version=self.metadata.version,
                category=self.metadata.category,
                severity=Severity.LOW,
                confidence=0.8,
                calculated_observation=(
                    f"Column '{profile.column.original_name}' has {len(affected_indices)} "
                    f"date(s) before {cutoff} (oldest {oldest.isoformat()})."
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


_EMAIL_NAME_MARKER = "email"
"""A text-family column is treated as a candidate email column when its
lowercased name, with `-`, `_` and spaces removed, contains this marker. A
disclosed, reversible column-name heuristic — no confirmed column-role
context (`CTX-01`) exists yet — in the same spirit as
`_PERCENTAGE_NAME_MARKERS` below."""

_EMAIL_MIN_VALID_SHARE = 0.5
"""A candidate column is checked only when at least this share of its
non-blank values already have an email shape. A column named `email_sent`
holding `Y`/`N`, or `email_template` holding names, is then left alone,
while an email column with some bad entries is still found."""

_EMAIL_APPLICABLE_TYPES: tuple[InferredColumnType, ...] = (
    InferredColumnType.TEXT,
    InferredColumnType.CATEGORICAL,
    InferredColumnType.IDENTIFIER,
    InferredColumnType.MIXED,
)


def _has_email_shape(value: str) -> bool:
    """Whether `value` has the shape `local@domain.tld`: no whitespace, one
    `@`, a non-empty local part and a domain of at least two non-empty
    dot-separated labels. A shape check only — it never claims the address
    exists or can receive mail. Written without a regular expression so
    value length cannot cause backtracking."""
    if any(character.isspace() for character in value):
        return False
    if value.count("@") != 1:
        return False
    local, domain = value.split("@")
    if not local or not domain:
        return False
    labels = domain.split(".")
    return len(labels) >= 2 and all(labels)


class InvalidEmailShapeDetector:
    """`validity.invalid_email_shape` — flags a column named like an email
    column whose non-blank values mostly have an email shape but include
    some that cannot (`DET-03` slice 2).

    Email values are personal data, so this detector records **counts and
    row numbers only**: no value, fragment or domain ever appears in the
    finding, the evidence or any text built from them.
    """

    metadata = DetectorMetadata(
        detector_id="validity.invalid_email_shape",
        version="1",
        name="Invalid email shape",
        category=DetectorCategory.VALIDITY,
        description=(
            "Flags values in an email-named column that do not have the shape local@domain.tld."
        ),
        applicable_inferred_types=_EMAIL_APPLICABLE_TYPES,
        required_profile_fields=("column_profiles[].inferred_type",),
        requires_raw_rows=True,
        requires_confirmed_context=False,
        default_configuration={},
        performance_class=PerformanceClass.LINEAR_BY_ROW,
        documented_limitations=(
            "Email columns are found by name ('email' in the column name); a differently "
            "named email column is not checked, and a column named like one that holds "
            "something else is checked only if most of its values look like emails.",
            "Only the shape is checked; an address with a valid shape can still be wrong "
            "or undeliverable.",
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
            if profile.inferred_type not in _EMAIL_APPLICABLE_TYPES:
                continue
            compact_name = (
                profile.column.original_name.lower()
                .replace("-", "")
                .replace("_", "")
                .replace(" ", "")
            )
            if _EMAIL_NAME_MARKER not in compact_name:
                continue

            checked = 0
            invalid_indices: list[int] = []
            for index, row in enumerate(request.rows):
                value = row.get(profile.column.internal_key)
                if not isinstance(value, str):
                    continue
                stripped = value.strip()
                if not stripped:
                    continue
                checked += 1
                if not _has_email_shape(stripped):
                    invalid_indices.append(index)

            if not invalid_indices:
                continue
            if (checked - len(invalid_indices)) / checked < _EMAIL_MIN_VALID_SHARE:
                continue

            affected_row_references = tuple(
                request.row_references[index] for index in invalid_indices
            )
            evidence_id = f"validity.invalid_email_shape.evidence.{profile.column.internal_key}"
            column_evidence = Evidence(
                evidence_id=evidence_id,
                evidence_type=EvidenceType.ROW_SET,
                calculation_version="1",
                structured_payload={
                    "checked_value_count": checked,
                    "invalid_value_count": len(invalid_indices),
                    "expected_shape": "local@domain.tld",
                },
                affected_columns=(profile.column,),
                affected_row_references=affected_row_references,
                scope=SamplingScope.FULL,
                display_safe_summary=(
                    f"Column '{profile.column.original_name}' has {len(invalid_indices)} of "
                    f"{checked} value(s) that do not have an email shape."
                ),
            )
            finding = FindingCandidate(
                detector_id=self.metadata.detector_id,
                detector_version=self.metadata.version,
                category=self.metadata.category,
                severity=Severity.LOW,
                confidence=0.8,
                calculated_observation=(
                    f"Column '{profile.column.original_name}' has {len(invalid_indices)} of "
                    f"{checked} non-blank value(s) that do not have the shape of an email address."
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


_PERCENTAGE_NAME_MARKERS: tuple[str, ...] = ("pct", "percent", "%")
"""A `NUMERIC` column is treated as a candidate percentage column when
its lowercased `original_name` contains any of these markers. A
disclosed, reversible column-name heuristic — no confirmed column-role
context (`CTX-01`) exists yet to identify percentage columns directly.
Matches exactly `discount_pct`/`tax_pct` in the `DEMO-01` demo dataset;
a percentage column named differently would be missed, and a
coincidentally-matching non-percentage column would be incorrectly
checked (both disclosed limitations)."""

_PERCENTAGE_VALID_MIN = 0.0
_PERCENTAGE_VALID_MAX = 100.0
"""The valid percentage range is `[0, 100]` inclusive; a value outside
this range is invalid."""


class NegativeLikelyNonNegativeValuesDetector:
    """`validity.negative_likely_non_negative_values` — flags
    `NUMERIC`-typed columns where negative values are present but make
    up a small minority (below `_NEGATIVE_MINORITY_RATIO`) of non-blank
    values, treating them as likely errors rather than a normal bipolar
    distribution.
    """

    metadata = DetectorMetadata(
        detector_id="validity.negative_likely_non_negative_values",
        version="1",
        name="Negative likely non-negative values",
        category=DetectorCategory.VALIDITY,
        description=(
            "Flags numeric columns where negative values are a small minority, "
            "suggesting they are likely errors."
        ),
        applicable_inferred_types=(InferredColumnType.NUMERIC,),
        required_profile_fields=(
            "column_profiles[].metrics.negative_count",
            "column_profiles[].null_count",
            "sampling.sample_size",
        ),
        requires_raw_rows=True,
        requires_confirmed_context=False,
        default_configuration={},
        performance_class=PerformanceClass.LINEAR_BY_ROW,
        documented_limitations=(
            "A negative value may be a legitimate return or adjustment without "
            "confirmed business context; confidence is lowered to reflect this.",
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
            if profile.inferred_type is not InferredColumnType.NUMERIC:
                continue

            negative_count = profile.metrics.get("negative_count")
            if not isinstance(negative_count, int) or negative_count <= 0:
                continue

            non_null_count = sample_size - profile.null_count
            if non_null_count <= 0:
                continue
            ratio = negative_count / non_null_count
            if ratio >= _NEGATIVE_MINORITY_RATIO:
                continue

            affected_indices: list[int] = []
            for index, row in enumerate(request.rows):
                value = row.get(profile.column.internal_key)
                if not isinstance(value, str) or not value:
                    continue
                try:
                    parsed_value = float(value.strip())
                except ValueError:
                    continue
                if parsed_value < 0.0:
                    affected_indices.append(index)

            if not affected_indices:
                continue

            affected_row_references = tuple(
                request.row_references[index] for index in affected_indices
            )
            evidence_id = (
                "validity.negative_likely_non_negative_values.evidence."
                f"{profile.column.internal_key}"
            )
            column_evidence = Evidence(
                evidence_id=evidence_id,
                evidence_type=EvidenceType.ROW_SET,
                calculation_version="1",
                structured_payload={
                    "negative_count": negative_count,
                    "non_null_count": non_null_count,
                    "negative_ratio": ratio,
                },
                affected_columns=(profile.column,),
                affected_row_references=affected_row_references,
                scope=SamplingScope.FULL,
                display_safe_summary=(
                    f"Column '{profile.column.original_name}' has {negative_count} "
                    f"negative value(s) out of {non_null_count}."
                ),
            )
            finding = FindingCandidate(
                detector_id=self.metadata.detector_id,
                detector_version=self.metadata.version,
                category=self.metadata.category,
                severity=Severity.MEDIUM,
                confidence=0.7,
                calculated_observation=(
                    f"Column '{profile.column.original_name}' has {negative_count} "
                    f"negative value(s) out of {non_null_count} "
                    f"({ratio:.1%}), likely an error rather than a normal "
                    "negative-valued column."
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


class InvalidPercentagesDetector:
    """`validity.invalid_percentages` — flags `NUMERIC`-typed columns
    whose name matches a percentage-name heuristic and that contain one
    or more values outside the valid `[0, 100]` range.

    Scans raw rows directly (like `FutureDatesDetector`) rather than
    reusing a `PROF-03` metric: `min`/`max` are not part of this
    detector's declared contract, avoiding a dependency on an optional
    metrics key.
    """

    metadata = DetectorMetadata(
        detector_id="validity.invalid_percentages",
        version="1",
        name="Invalid percentages",
        category=DetectorCategory.VALIDITY,
        description=(
            "Flags numeric percentage-like columns containing values outside the valid 0-100 range."
        ),
        applicable_inferred_types=(InferredColumnType.NUMERIC,),
        required_profile_fields=(
            "column_profiles[].inferred_type",
            "column_profiles[].column.original_name",
        ),
        requires_raw_rows=True,
        requires_confirmed_context=False,
        default_configuration={},
        performance_class=PerformanceClass.LINEAR_BY_ROW,
        documented_limitations=(
            "Relies on a column-name heuristic ('pct'/'percent' substring or a "
            "'%' character) to identify percentage columns; a percentage column "
            "named differently is not checked, and a non-percentage numeric "
            "column whose name happens to match the heuristic would be "
            "incorrectly checked. Confirmed column semantics (CTX-01) would "
            "remove this heuristic.",
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
            lowered_name = profile.column.original_name.lower()
            if not any(marker in lowered_name for marker in _PERCENTAGE_NAME_MARKERS):
                continue

            affected_indices: list[int] = []
            for index, row in enumerate(request.rows):
                value = row.get(profile.column.internal_key)
                if not isinstance(value, str) or not value:
                    continue
                try:
                    parsed_value = float(value.strip())
                except ValueError:
                    continue
                if parsed_value < _PERCENTAGE_VALID_MIN or parsed_value > _PERCENTAGE_VALID_MAX:
                    affected_indices.append(index)

            if not affected_indices:
                continue

            affected_row_references = tuple(
                request.row_references[index] for index in affected_indices
            )
            evidence_id = f"validity.invalid_percentages.evidence.{profile.column.internal_key}"
            column_evidence = Evidence(
                evidence_id=evidence_id,
                evidence_type=EvidenceType.ROW_SET,
                calculation_version="1",
                structured_payload={
                    "valid_min": _PERCENTAGE_VALID_MIN,
                    "valid_max": _PERCENTAGE_VALID_MAX,
                    "invalid_count": len(affected_indices),
                },
                affected_columns=(profile.column,),
                affected_row_references=affected_row_references,
                scope=SamplingScope.FULL,
                display_safe_summary=(
                    f"Column '{profile.column.original_name}' has "
                    f"{len(affected_indices)} value(s) outside the valid "
                    f"{_PERCENTAGE_VALID_MIN:g}-{_PERCENTAGE_VALID_MAX:g} range."
                ),
            )
            finding = FindingCandidate(
                detector_id=self.metadata.detector_id,
                detector_version=self.metadata.version,
                category=self.metadata.category,
                severity=Severity.MEDIUM,
                confidence=1.0,
                calculated_observation=(
                    f"Column '{profile.column.original_name}' has "
                    f"{len(affected_indices)} value(s) outside the valid "
                    f"{_PERCENTAGE_VALID_MIN:g}-{_PERCENTAGE_VALID_MAX:g} range."
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
