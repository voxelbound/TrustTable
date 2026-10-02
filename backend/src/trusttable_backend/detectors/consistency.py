"""Consistency detectors (`DET-02` partial), matching
`docs/detector-framework.md` §16's "Consistency" category: inconsistent
capitalization and leading/trailing whitespace.

Both detectors are restricted to text-family columns (`TEXT`,
`CATEGORICAL`, `IDENTIFIER`) — the same set `PROF-03` already scopes its
own text-family metrics to (`PROF-02` r3's forward-compatibility
requirement). `LeadingTrailingWhitespaceDetector` reuses `PROF-03`'s
already-computed `whitespace_issue_count` metric to decide *whether* a
column qualifies, then re-scans raw rows only to identify *which* rows
(the metric itself is a count, not a row list). `InconsistentCapitalizationDetector`
computes its own precise, whitespace-excluded grouping directly from raw
rows: no existing metric distinguishes a pure casing difference from a
pure whitespace difference or a combination of both.

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
    """No configurable parameters for either detector in this package."""


_TEXT_FAMILY_TYPES: tuple[InferredColumnType, ...] = (
    InferredColumnType.TEXT,
    InferredColumnType.CATEGORICAL,
    InferredColumnType.IDENTIFIER,
)


class InconsistentCapitalizationDetector:
    """`consistency.inconsistent_capitalization` — flags a group of
    values within a text-family column that are identical after
    stripping whitespace and lowercasing, but use more than one distinct
    raw casing.

    Grouping is keyed on `value.strip().lower()` (not `value.lower()`):
    whitespace differences are intentionally excluded from the casing
    comparison, since that condition is `leading_trailing_whitespace`'s
    exclusive territory. One finding is produced per conflicting group,
    with `affected_row_references` covering every row in that group (the
    full group, not just the minority casing) — the same evidence-scope
    convention as `structural.exact_duplicate_rows` (`WP-014`).
    """

    metadata = DetectorMetadata(
        detector_id="consistency.inconsistent_capitalization",
        version="1",
        name="Inconsistent capitalization",
        category=DetectorCategory.CONSISTENCY,
        description=("Flags values within a column that are identical except for casing."),
        applicable_inferred_types=_TEXT_FAMILY_TYPES,
        required_profile_fields=("column_profiles[].inferred_type",),
        requires_raw_rows=True,
        requires_confirmed_context=False,
        default_configuration={},
        performance_class=PerformanceClass.LINEAR_BY_ROW,
        documented_limitations=(
            "Only flags exact matches after stripping whitespace and lowercasing; "
            "near-duplicate values that differ by more than casing are out of scope.",
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
            if profile.inferred_type not in _TEXT_FAMILY_TYPES:
                continue

            groups: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
            for index, row in enumerate(request.rows):
                value = row.get(profile.column.internal_key)
                if not isinstance(value, str):
                    continue
                stripped = value.strip()
                if not stripped:
                    continue
                groups[stripped.lower()][stripped].append(index)

            for normalized_key, casings in groups.items():
                if len(casings) < 2:
                    continue

                affected_indices = sorted(
                    index for indices in casings.values() for index in indices
                )
                affected_row_references = tuple(
                    request.row_references[index] for index in affected_indices
                )

                evidence_id = (
                    f"consistency.inconsistent_capitalization.evidence."
                    f"{profile.column.internal_key}.{normalized_key}"
                )
                column_evidence = Evidence(
                    evidence_id=evidence_id,
                    evidence_type=EvidenceType.ROW_SET,
                    calculation_version="1",
                    structured_payload={
                        "distinct_casings": sorted(casings),
                        "affected_row_count": len(affected_indices),
                    },
                    affected_columns=(profile.column,),
                    affected_row_references=affected_row_references,
                    scope=SamplingScope.FULL,
                    display_safe_summary=(
                        f"Column '{profile.column.original_name}' has "
                        f"{len(casings)} different casings of the same value "
                        f"across {len(affected_indices)} row(s)."
                    ),
                )
                finding = FindingCandidate(
                    detector_id=self.metadata.detector_id,
                    detector_version=self.metadata.version,
                    category=self.metadata.category,
                    severity=Severity.LOW,
                    confidence=1.0,
                    calculated_observation=(
                        f"Column '{profile.column.original_name}' uses "
                        f"{len(casings)} different casings ({', '.join(sorted(casings))}) "
                        f"for the same value across {len(affected_indices)} row(s)."
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


_BOOLEAN_FAMILIES: dict[str, str] = {
    "true": "true/false",
    "false": "true/false",
    "yes": "yes/no",
    "no": "yes/no",
    "y": "y/n",
    "n": "y/n",
    "t": "t/f",
    "f": "t/f",
    "on": "on/off",
    "off": "on/off",
    "1": "1/0",
    "0": "1/0",
}
"""Closed boolean vocabulary: each lowercased token maps to the spelling
family it belongs to. A column is a boolean column only when *every*
non-blank value is one of these tokens."""

_BOOLEAN_APPLICABLE_TYPES: tuple[InferredColumnType, ...] = (
    InferredColumnType.TEXT,
    InferredColumnType.CATEGORICAL,
    InferredColumnType.BOOLEAN,
    InferredColumnType.MIXED,
)


class InconsistentBooleansDetector:
    """`consistency.inconsistent_booleans` — flags a column whose values are
    all boolean tokens but written in more than one spelling family, for
    example `Y`, `yes` and `TRUE` side by side (`DET-03` slice 1).

    Mixed spellings break filters and counts: `Y` and `yes` group apart, and
    a join or a boolean cast can silently drop one family.

    False-positive guards, all deliberate:

    - every non-blank value must be in the closed vocabulary, so a status
      column holding `Y`, `N` and `Maybe` is never flagged;
    - at least two *families* must appear. Casing differences inside one
      family (`yes`/`YES`) are `consistency.inconsistent_capitalization`'s
      territory, and a column of only `1`/`0` or only `Y`/`N` is consistent;
    - identifier, numeric and date columns are out of scope.
    """

    metadata = DetectorMetadata(
        detector_id="consistency.inconsistent_booleans",
        version="1",
        name="Inconsistent boolean spellings",
        category=DetectorCategory.CONSISTENCY,
        description=(
            "Flags a column whose values are all boolean tokens written in more than "
            "one spelling family."
        ),
        applicable_inferred_types=_BOOLEAN_APPLICABLE_TYPES,
        required_profile_fields=("column_profiles[].inferred_type",),
        requires_raw_rows=True,
        requires_confirmed_context=False,
        default_configuration={},
        performance_class=PerformanceClass.LINEAR_BY_ROW,
        documented_limitations=(
            "Only the closed vocabulary true/false, yes/no, y/n, t/f, on/off and 1/0 is "
            "recognized, in any casing; other spellings are not treated as booleans.",
            "A column mixing two single-letter families, such as Y and T, is flagged "
            "although the letters could be unrelated categories.",
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
            if profile.inferred_type not in _BOOLEAN_APPLICABLE_TYPES:
                continue

            spelling_counts: dict[str, int] = defaultdict(int)
            indices: list[int] = []
            all_boolean = True
            for index, row in enumerate(request.rows):
                value = row.get(profile.column.internal_key)
                if not isinstance(value, str):
                    continue
                stripped = value.strip()
                if not stripped:
                    continue
                if stripped.lower() not in _BOOLEAN_FAMILIES:
                    all_boolean = False
                    break
                spelling_counts[stripped] += 1
                indices.append(index)

            if not all_boolean or not spelling_counts:
                continue
            families = sorted({_BOOLEAN_FAMILIES[spelling.lower()] for spelling in spelling_counts})
            if len(families) < 2:
                continue

            affected_row_references = tuple(request.row_references[index] for index in indices)
            spellings = sorted(spelling_counts)
            evidence_id = (
                f"consistency.inconsistent_booleans.evidence.{profile.column.internal_key}"
            )
            column_evidence = Evidence(
                evidence_id=evidence_id,
                evidence_type=EvidenceType.ROW_SET,
                calculation_version="1",
                structured_payload={
                    "spelling_families": families,
                    "distinct_spellings": spellings,
                    "affected_row_count": len(indices),
                },
                affected_columns=(profile.column,),
                affected_row_references=affected_row_references,
                scope=SamplingScope.FULL,
                display_safe_summary=(
                    f"Column '{profile.column.original_name}' writes boolean values "
                    f"{len(families)} different ways across {len(indices)} row(s)."
                ),
            )
            finding = FindingCandidate(
                detector_id=self.metadata.detector_id,
                detector_version=self.metadata.version,
                category=self.metadata.category,
                severity=Severity.LOW,
                confidence=0.9,
                calculated_observation=(
                    f"Column '{profile.column.original_name}' writes yes/no style values "
                    f"in {len(families)} spelling families ({', '.join(spellings)}) "
                    f"across {len(indices)} row(s)."
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


_CURRENCY_SYMBOLS = "$€£¥"
_ASCII_DIGITS = frozenset("0123456789")

_NUMBERS_AS_TEXT_MIN_SHARE = 0.9
"""A column is read as numbers stored as text only when at least this share
of its non-blank values read as numbers. A disclosed, reversible design
choice (`docs/detector-framework.md` §11 requires an explicit rule but fixes
no exact number): high enough that a text column with a few numeric-looking
entries is left alone, low enough that a numeric column with a few blank-ish
or stray entries is still found."""

_NUMBERS_AS_TEXT_APPLICABLE_TYPES: tuple[InferredColumnType, ...] = (
    InferredColumnType.TEXT,
    InferredColumnType.CATEGORICAL,
    InferredColumnType.IDENTIFIER,
    InferredColumnType.MIXED,
)


def _is_ascii_digits(text: str) -> bool:
    return bool(text) and all(character in _ASCII_DIGITS for character in text)


def _read_number(value: str) -> tuple[bool, tuple[str, ...]]:
    """Whether `value` is a number, and which decorations it carries.

    Accepts an optional sign, one optional currency symbol, digits with
    optional thousands commas (groups of exactly three), an optional decimal
    part and an optional percent sign. Rejects anything else — brackets,
    hyphens inside the number, spaces, letters — so phone numbers and codes
    are not numbers. An integer part with a leading zero (`007`) is treated
    as a code, not a number. Written with character checks only, no regular
    expression, so value length cannot cause backtracking.
    """
    text = value.strip()
    decorations: list[str] = []
    if text[:1] in ("+", "-"):
        text = text[1:]
    if text[:1] and text[0] in _CURRENCY_SYMBOLS:
        decorations.append("currency symbol")
        text = text[1:]
        if text[:1] in ("+", "-"):
            text = text[1:]
    if text.endswith("%"):
        decorations.append("percent sign")
        text = text[:-1]
    integer, dot, fraction = text.partition(".")
    if "," in integer:
        groups = integer.split(",")
        if not (1 <= len(groups[0]) <= 3 and all(len(group) == 3 for group in groups[1:])):
            return False, ()
        decorations.append("thousands separator")
        integer = "".join(groups)
    if dot and not fraction:
        return False, ()
    if (integer and not _is_ascii_digits(integer)) or (fraction and not _is_ascii_digits(fraction)):
        return False, ()
    if not integer and not fraction:
        return False, ()
    if len(integer) > 1 and integer.startswith("0"):
        return False, ()
    return True, tuple(decorations)


class NumericValuesStoredAsTextDetector:
    """`consistency.numeric_values_stored_as_text` — flags a column that is
    not already numeric but whose values are almost all numbers written with
    a currency symbol, percent sign or thousands separator, such as
    `$1,234.50` or `12%` (`DET-03` slice 3).

    Such values cannot be summed, averaged or sorted as numbers, and most
    tools skip or mis-sort them silently. `PROF-02` calls a column numeric
    only when every value is a plain number, so these columns are typed as
    text; this detector finds them.

    False-positive guards, all deliberate: at least one value must carry a
    decoration (a column of plain numbers is already numeric); at least 90%
    of non-blank values must read as numbers; and zero-padded values,
    phone numbers, codes with hyphens or brackets, and anything with letters
    are never numbers here.
    """

    metadata = DetectorMetadata(
        detector_id="consistency.numeric_values_stored_as_text",
        version="1",
        name="Numeric values stored as text",
        category=DetectorCategory.CONSISTENCY,
        description=(
            "Flags a column whose values are numbers written with currency symbols, "
            "percent signs or thousands separators, so it is typed as text."
        ),
        applicable_inferred_types=_NUMBERS_AS_TEXT_APPLICABLE_TYPES,
        required_profile_fields=("column_profiles[].inferred_type",),
        requires_raw_rows=True,
        requires_confirmed_context=False,
        default_configuration={},
        performance_class=PerformanceClass.LINEAR_BY_ROW,
        documented_limitations=(
            "Only a sign, one currency symbol ($, €, £, ¥), comma thousands separators and "
            "a percent sign are recognized; European decimal commas, spaces inside numbers, "
            "accounting brackets and currency codes such as USD are not.",
            "Zero-padded values such as 007 are treated as codes, so a column of "
            "zero-padded amounts is not flagged.",
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
            if profile.inferred_type not in _NUMBERS_AS_TEXT_APPLICABLE_TYPES:
                continue

            checked = 0
            numeric_like = 0
            decorated_indices: list[int] = []
            decoration_kinds: set[str] = set()
            for index, row in enumerate(request.rows):
                value = row.get(profile.column.internal_key)
                if not isinstance(value, str) or not value.strip():
                    continue
                checked += 1
                is_number, decorations = _read_number(value)
                if is_number:
                    numeric_like += 1
                    if decorations:
                        decorated_indices.append(index)
                        decoration_kinds.update(decorations)

            if not decorated_indices or numeric_like / checked < _NUMBERS_AS_TEXT_MIN_SHARE:
                continue

            affected_row_references = tuple(
                request.row_references[index] for index in decorated_indices
            )
            kinds = sorted(decoration_kinds)
            evidence_id = (
                f"consistency.numeric_values_stored_as_text.evidence.{profile.column.internal_key}"
            )
            column_evidence = Evidence(
                evidence_id=evidence_id,
                evidence_type=EvidenceType.ROW_SET,
                calculation_version="1",
                structured_payload={
                    "checked_value_count": checked,
                    "numeric_like_count": numeric_like,
                    "decorated_value_count": len(decorated_indices),
                    "decorations": kinds,
                },
                affected_columns=(profile.column,),
                affected_row_references=affected_row_references,
                scope=SamplingScope.FULL,
                display_safe_summary=(
                    f"Column '{profile.column.original_name}' holds numbers as text in "
                    f"{len(decorated_indices)} row(s) ({', '.join(kinds)})."
                ),
            )
            finding = FindingCandidate(
                detector_id=self.metadata.detector_id,
                detector_version=self.metadata.version,
                category=self.metadata.category,
                severity=Severity.MEDIUM,
                confidence=0.9,
                calculated_observation=(
                    f"Column '{profile.column.original_name}' holds numbers as text in "
                    f"{len(decorated_indices)} of {checked} non-blank row(s) "
                    f"({', '.join(kinds)}), so it is not read as a numeric column."
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


_NEAR_DUPLICATE_MAX_VARIANTS_SHOWN = 10
_NEAR_DUPLICATE_MAX_VARIANT_LENGTH = 60
_NEAR_DUPLICATE_MIN_KEY_LENGTH = 2


def _near_duplicate_key(value: str) -> str:
    """The value lowercased with every character that is not a letter or a
    digit removed, so `New York`, `New-York` and `NewYork` share a key."""
    return "".join(character for character in value.lower() if character.isalnum())


class NearDuplicateCategoriesDetector:
    """`consistency.near_duplicate_categories` — flags category values in a
    categorical column that differ only by punctuation or internal spacing,
    such as `New York`, `New-York` and `NewYork` (`DET-03` slice 3).

    One finding is produced per group of variants, with every row in the
    group as an affected row, the same convention as
    `consistency.inconsistent_capitalization`.

    It deliberately leaves two things to the existing detectors so nothing is
    reported twice: values that differ only in casing
    (`consistency.inconsistent_capitalization`) and values that differ only in
    leading or trailing whitespace (`consistency.leading_trailing_whitespace`).
    A group is reported only when it has at least two variants that differ
    after trimming and lowercasing.

    Guards: only categorical columns; a key of fewer than two characters, or
    made only of digits (where `1.5` and `15` are different numbers), is
    ignored.
    """

    metadata = DetectorMetadata(
        detector_id="consistency.near_duplicate_categories",
        version="1",
        name="Near-duplicate categories",
        category=DetectorCategory.CONSISTENCY,
        description=("Flags category values that differ only by punctuation or internal spacing."),
        applicable_inferred_types=(InferredColumnType.CATEGORICAL,),
        required_profile_fields=("column_profiles[].inferred_type",),
        requires_raw_rows=True,
        requires_confirmed_context=False,
        default_configuration={},
        performance_class=PerformanceClass.LINEAR_BY_ROW,
        documented_limitations=(
            "Only differences in punctuation and internal spacing are found; spelling "
            "variants, abbreviations and plurals are not.",
            "Two categories that really are different but share letters and digits, such "
            "as A-1 and A1, are reported as near-duplicates.",
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
            if profile.inferred_type is not InferredColumnType.CATEGORICAL:
                continue

            groups: dict[str, dict[str, list[int]]] = defaultdict(lambda: defaultdict(list))
            for index, row in enumerate(request.rows):
                value = row.get(profile.column.internal_key)
                if not isinstance(value, str):
                    continue
                stripped = value.strip()
                if not stripped:
                    continue
                key = _near_duplicate_key(stripped)
                if len(key) < _NEAR_DUPLICATE_MIN_KEY_LENGTH or _is_ascii_digits(key):
                    continue
                groups[key][stripped.lower()].append(index)

            for key, variants in sorted(groups.items()):
                if len(variants) < 2:
                    continue

                affected_indices = sorted(
                    index for indices in variants.values() for index in indices
                )
                affected_row_references = tuple(
                    request.row_references[index] for index in affected_indices
                )
                shown = sorted(variants)[:_NEAR_DUPLICATE_MAX_VARIANTS_SHOWN]
                shown = [variant[:_NEAR_DUPLICATE_MAX_VARIANT_LENGTH] for variant in shown]
                evidence_id = (
                    f"consistency.near_duplicate_categories.evidence."
                    f"{profile.column.internal_key}.{key}"
                )
                column_evidence = Evidence(
                    evidence_id=evidence_id,
                    evidence_type=EvidenceType.ROW_SET,
                    calculation_version="1",
                    structured_payload={
                        "variant_count": len(variants),
                        "variants_shown": shown,
                        "affected_row_count": len(affected_indices),
                    },
                    affected_columns=(profile.column,),
                    affected_row_references=affected_row_references,
                    scope=SamplingScope.FULL,
                    display_safe_summary=(
                        f"Column '{profile.column.original_name}' has {len(variants)} "
                        f"spellings of one category across {len(affected_indices)} row(s)."
                    ),
                )
                finding = FindingCandidate(
                    detector_id=self.metadata.detector_id,
                    detector_version=self.metadata.version,
                    category=self.metadata.category,
                    severity=Severity.LOW,
                    confidence=0.8,
                    calculated_observation=(
                        f"Column '{profile.column.original_name}' writes what looks like one "
                        f"category {len(variants)} ways ({', '.join(shown)}) across "
                        f"{len(affected_indices)} row(s)."
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


class LeadingTrailingWhitespaceDetector:
    """`consistency.leading_trailing_whitespace` — flags text-family
    columns with one or more values carrying leading or trailing
    whitespace, reusing `PROF-03`'s already-computed
    `whitespace_issue_count` metric to decide whether a column
    qualifies.
    """

    metadata = DetectorMetadata(
        detector_id="consistency.leading_trailing_whitespace",
        version="1",
        name="Leading/trailing whitespace",
        category=DetectorCategory.CONSISTENCY,
        description="Flags column values with leading or trailing whitespace.",
        applicable_inferred_types=_TEXT_FAMILY_TYPES,
        required_profile_fields=("column_profiles[].metrics.whitespace_issue_count",),
        requires_raw_rows=True,
        requires_confirmed_context=False,
        default_configuration={},
        performance_class=PerformanceClass.LINEAR_BY_ROW,
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
            if profile.inferred_type not in _TEXT_FAMILY_TYPES:
                continue
            whitespace_issue_count = profile.metrics.get("whitespace_issue_count")
            if not isinstance(whitespace_issue_count, int) or whitespace_issue_count <= 0:
                continue

            affected_indices: list[int] = []
            for index, row in enumerate(request.rows):
                value = row.get(profile.column.internal_key)
                if isinstance(value, str) and value != value.strip():
                    affected_indices.append(index)
            affected_row_references = tuple(
                request.row_references[index] for index in affected_indices
            )

            evidence_id = (
                f"consistency.leading_trailing_whitespace.evidence.{profile.column.internal_key}"
            )
            column_evidence = Evidence(
                evidence_id=evidence_id,
                evidence_type=EvidenceType.ROW_SET,
                calculation_version="1",
                structured_payload={"whitespace_issue_count": whitespace_issue_count},
                affected_columns=(profile.column,),
                affected_row_references=affected_row_references,
                scope=SamplingScope.FULL,
                display_safe_summary=(
                    f"Column '{profile.column.original_name}' has leading or "
                    f"trailing whitespace in {len(affected_indices)} row(s)."
                ),
            )
            finding = FindingCandidate(
                detector_id=self.metadata.detector_id,
                detector_version=self.metadata.version,
                category=self.metadata.category,
                severity=Severity.LOW,
                confidence=1.0,
                calculated_observation=(
                    f"Column '{profile.column.original_name}' has leading or "
                    f"trailing whitespace in {len(affected_indices)} row(s)."
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
