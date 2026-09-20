"""Deterministic built-in guidance for every finding (`AI-08`,
`docs/decision-log.md` D-040): possible business impact, an advisory
remediation and a proposed validation rule, authored once per detector and
rendered with no AI at all.

This is what makes the four Finding Detail sections useful when AI is
disabled (`docs/product-requirements.md` §5.7), when a provider fails, and
when its output is rejected — the section is never empty or a placeholder.

Honesty rules baked into the table, because nothing here is validated by a
model boundary and everything is shown to users:

- every business-impact statement is labelled `ASSUMPTION` with its
  condition stated. A deterministic template cannot know a dataset's
  business use, so it never asserts a consequence as a fact and never
  claims `EVIDENCE` or `CONFIRMED_CONTEXT` backing;
- remediation is advice to a person; the wording says changes belong in the
  source system (TrustTable never edits an uploaded file);
- the rule is a *proposal* (`ProposedValidationRule`, status constant
  `"proposed"`) of a type from `docs/product-requirements.md` §13; nothing
  runs or enforces it (the rule engine is `RULE-01`, a later item).

Pure and framework-independent: no `ai_boundary`/`ai_provider` import, no
I/O. Stdlib only besides the domain and detector-contract types.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from ..detectors.contract import FindingCandidate
from ..domain.explanation import (
    BusinessImpactStatement,
    ImpactBasis,
    ProposedValidationRule,
    ValidationRuleType,
)

_MAX_NAMED_COLUMNS: Final[int] = 3
_MAX_COLUMN_NAME_DISPLAY: Final[int] = 60


@dataclass(frozen=True, slots=True)
class FindingGuidance:
    """The three advisory sections for one finding."""

    business_impact: tuple[BusinessImpactStatement, ...]
    remediation: tuple[str, ...]
    validation_rule: ProposedValidationRule


@dataclass(frozen=True, slots=True)
class _Template:
    impact: tuple[tuple[str, str], ...]  # (statement, assumption)
    remediation: tuple[str, ...]
    rule_type: ValidationRuleType
    rule_description: str


_TEMPLATES: Final[dict[str, _Template]] = {
    "structural.exact_duplicate_rows": _Template(
        impact=(
            (
                "Repeated rows can be counted more than once in totals, averages and "
                "record counts.",
                "the rows are aggregated or counted without removing duplicates first",
            ),
        ),
        remediation=(
            "Check whether the repeated rows are true duplicates or legitimate repeated records.",
            "If they are true duplicates, remove or merge them in the source system; "
            "TrustTable never edits your file.",
        ),
        rule_type=ValidationRuleType.UNIQUE,
        rule_description="Each row should be unique across {columns}.",
    ),
    "structural.empty_column": _Template(
        impact=(
            (
                "A column with no values carries no information and can signal a broken "
                "export or column mapping.",
                "the column is expected to hold values that reports rely on",
            ),
        ),
        remediation=(
            "Confirm whether {columns} should contain data and, if so, fix the export or "
            "mapping that produces it.",
            "If the column is not needed, leave it out of the export.",
        ),
        rule_type=ValidationRuleType.NOT_NULL,
        rule_description="Values in {columns} should not be blank.",
    ),
    "completeness.excessive_missing_values": _Template(
        impact=(
            (
                "Blank values can bias totals and averages or hide records from filters.",
                "the column feeds calculations or filters that assume it is filled in",
            ),
        ),
        remediation=(
            "Find out why values in {columns} are missing (an optional field, a failed "
            "export or a data-entry gap) before deciding how to handle them.",
            "Fill in or correct the missing values in the source system where the true "
            "value is known.",
        ),
        rule_type=ValidationRuleType.MAX_MISSING_PERCENTAGE,
        rule_description=(
            "The share of blank values in {columns} should stay below an agreed threshold."
        ),
    ),
    "completeness.missing_likely_identifier": _Template(
        impact=(
            (
                "A record without its identifier may not be matched, de-duplicated or traced "
                "back to its source.",
                "the identifier is used to join or reconcile records",
            ),
        ),
        remediation=(
            "Recover the missing identifiers in {columns} from the source system.",
            "Decide whether records that cannot be identified should be excluded from "
            "analysis until they are corrected.",
        ),
        rule_type=ValidationRuleType.NOT_NULL,
        rule_description="Every row should have a value in {columns}.",
    ),
    "consistency.inconsistent_capitalization": _Template(
        impact=(
            (
                "The same category written with different capitalization can be split into "
                "separate groups in summaries and filters.",
                "the column is used for grouping, filtering or joining",
            ),
        ),
        remediation=(
            "Standardize the capitalization of values in {columns} in the source system.",
            "Agree on one canonical spelling for each category.",
        ),
        rule_type=ValidationRuleType.ACCEPTED_VALUES,
        rule_description=(
            "Values in {columns} should come from one agreed list with a single canonical "
            "capitalization."
        ),
    ),
    "consistency.leading_trailing_whitespace": _Template(
        impact=(
            (
                "Stray spaces make identical-looking values compare as different, which can "
                "break matching and grouping.",
                "values in the column are matched or grouped by exact text",
            ),
        ),
        remediation=(
            "Trim leading and trailing spaces from values in {columns} at the source.",
            "Add trimming to the process that exports or enters this data.",
        ),
        rule_type=ValidationRuleType.REGEX,
        rule_description="Values in {columns} should not start or end with whitespace.",
    ),
    "validity.future_dates": _Template(
        impact=(
            (
                "Dates later than the analysis date may be typing errors or events that have "
                "not happened yet, and can distort time-based reports.",
                "the column is meant to record events that have already happened",
            ),
        ),
        remediation=(
            "Check the flagged rows and correct any mistyped dates in the source.",
            "If the dates are genuine scheduled events, consider keeping them in a separate field.",
        ),
        rule_type=ValidationRuleType.DATE_RANGE,
        rule_description=(
            "Dates in {columns} should not be later than the date the data is analyzed."
        ),
    ),
    "validity.negative_likely_non_negative_values": _Template(
        impact=(
            (
                "Negative values in a measure that is normally zero or positive can reduce "
                "totals, or reflect refunds or entry errors.",
                "the column is expected to hold only zero or positive amounts",
            ),
        ),
        remediation=(
            "Review the flagged rows to tell legitimate adjustments from entry errors.",
            "Correct erroneous values in the source system.",
        ),
        rule_type=ValidationRuleType.NUMERIC_RANGE,
        rule_description="Values in {columns} should be zero or greater.",
    ),
    "validity.invalid_percentages": _Template(
        impact=(
            (
                "Percentages outside the valid range are impossible values and can distort "
                "calculations that use them.",
                "the percentage is used to compute amounts such as discounts or taxes",
            ),
        ),
        remediation=(
            "Check whether values in {columns} were entered inconsistently as fractions and "
            "whole numbers.",
            "Correct out-of-range values in the source system.",
        ),
        rule_type=ValidationRuleType.NUMERIC_RANGE,
        rule_description="Percentage values in {columns} should be between 0 and 100.",
    ),
    "cross_field.line_total_mismatch": _Template(
        impact=(
            (
                "When a stored total does not match the values it should be computed from, "
                "downstream amounts may be wrong.",
                "the stored total is used for reporting or reconciliation",
            ),
        ),
        remediation=(
            "Compare the flagged rows' total with the fields it is computed from to see "
            "which value is wrong.",
            "Correct the wrong value in the source, or recompute the total there.",
        ),
        rule_type=ValidationRuleType.APPROXIMATE_EQUALITY,
        rule_description=(
            "The stored total should equal the value computed from the columns it depends "
            "on ({columns}), within a small rounding tolerance."
        ),
    ),
    "statistical.suspiciously_constant_column": _Template(
        impact=(
            (
                "A column with a single repeated value adds no information and may signal a "
                "default or a broken field.",
                "the column is expected to vary between records",
            ),
        ),
        remediation=(
            "Confirm whether a single value is expected for {columns}.",
            "If it is not, check the process that fills the column in.",
        ),
        rule_type=ValidationRuleType.ACCEPTED_VALUES,
        rule_description=(
            "Values in {columns} should be reviewed against the set of values that are "
            "actually expected."
        ),
    ),
    "statistical.extreme_outliers": _Template(
        impact=(
            (
                "Extreme values can dominate averages and totals, or be entry errors.",
                "the column feeds averages, totals or thresholds",
            ),
        ),
        remediation=(
            "Review the flagged rows to see whether the extreme values in {columns} are genuine.",
            "Correct entry errors at the source; keep genuine extreme values but consider "
            "reporting them separately.",
        ),
        rule_type=ValidationRuleType.NUMERIC_RANGE,
        rule_description=(
            "Values in {columns} should stay within a plausible range agreed with the data owner."
        ),
    ),
    "security.possible_llm_prompt_injection": _Template(
        impact=(
            (
                "Text that reads like an instruction to an AI assistant could influence an AI "
                "tool that later reads this data.",
                "an AI tool or assistant reads values from this column",
            ),
        ),
        remediation=(
            "Review the flagged cells and remove instruction-like text that does not belong "
            "in the data.",
            "Treat the contents of {columns} as untrusted whenever they are passed to any AI tool.",
        ),
        rule_type=ValidationRuleType.REGEX,
        rule_description=(
            "Values in {columns} should not contain instruction-like phrases aimed at AI "
            "assistants."
        ),
    ),
}

#: Used for any detector id without a dedicated template, so a finding from
#: a detector added later still gets honest, non-empty guidance.
_GENERIC_TEMPLATE: Final[_Template] = _Template(
    impact=(
        (
            "This condition could affect reports or decisions that rely on the affected data.",
            "the affected data is used in reports or decisions",
        ),
    ),
    remediation=(
        "Review the flagged rows and confirm whether the values in {columns} are correct.",
        "Correct genuine errors in the source system.",
    ),
    rule_type=ValidationRuleType.CONDITIONAL_RULE,
    rule_description=(
        "Once you have confirmed what a valid value looks like, define a rule for {columns} "
        "that flags this condition."
    ),
)

#: Detector ids that have a dedicated template (used by tests to prove full
#: catalogue coverage).
GUIDED_DETECTOR_IDS: Final[frozenset[str]] = frozenset(_TEMPLATES)


def _columns_phrase(finding: FindingCandidate) -> str:
    names = [
        f"'{column.original_name[:_MAX_COLUMN_NAME_DISPLAY]}'"
        for column in finding.affected_columns[:_MAX_NAMED_COLUMNS]
    ]
    if not names:
        return "the affected columns"
    phrase = ", ".join(names)
    if len(finding.affected_columns) > _MAX_NAMED_COLUMNS:
        phrase += " and other columns"
    return phrase


def build_deterministic_guidance(finding: FindingCandidate) -> FindingGuidance:
    """Build the three advisory sections for `finding` from the static
    table. Always non-empty; never asserts a consequence as a fact."""
    template = _TEMPLATES.get(finding.detector_id, _GENERIC_TEMPLATE)
    columns = _columns_phrase(finding)
    impact = tuple(
        BusinessImpactStatement(
            statement=statement,
            basis=ImpactBasis.ASSUMPTION,
            evidence_ids=finding.evidence_ids,
            assumption=assumption,
        )
        for statement, assumption in template.impact
    )
    remediation = tuple(step.format(columns=columns) for step in template.remediation)
    rule = ProposedValidationRule(
        rule_type=template.rule_type,
        columns=finding.affected_columns,
        description=template.rule_description.format(columns=columns),
    )
    return FindingGuidance(business_impact=impact, remediation=remediation, validation_rule=rule)


__all__ = ["GUIDED_DETECTOR_IDS", "FindingGuidance", "build_deterministic_guidance"]
