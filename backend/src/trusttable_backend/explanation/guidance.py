"""Deterministic built-in guidance for every finding (`AI-08`,
`docs/decision-log.md` D-040; remediation restructured by `REM-01`,
`docs/domain-model.md` §16): possible business impact, a structured
remediation recommendation and a proposed validation rule, authored once
per detector and rendered with no AI at all.

This is what makes the four Finding Detail sections useful when AI is
disabled (`docs/product-requirements.md` §5.7), when a provider fails, and
when its output is rejected — the section is never empty or a placeholder.

Honesty rules baked into the table, because nothing here is validated by a
model boundary and everything is shown to users:

- every business-impact statement is labelled `ASSUMPTION` with its
  condition stated. A deterministic template cannot know a dataset's
  business use, so it never asserts a consequence as a fact and never
  claims `EVIDENCE` or `CONFIRMED_CONTEXT` backing;
- remediation is one structured `RemediationOption` (`REM-01`): advice to a
  person, never a claim that TrustTable itself changed anything. Its two
  guidance texts stay split exactly as before REM-01's restructuring —
  correcting rows already affected (`historical_correction_guidance`) and
  fixing the source system so it does not recur
  (`source_system_prevention_guidance`) — now joined by a role, an urgency,
  an always-populated risk warning, and a verification step;
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
    RemediationOption,
    ValidationRuleType,
)

_MAX_NAMED_COLUMNS: Final[int] = 3
_MAX_COLUMN_NAME_DISPLAY: Final[int] = 60


@dataclass(frozen=True, slots=True)
class FindingGuidance:
    """The three advisory sections for one finding."""

    business_impact: tuple[BusinessImpactStatement, ...]
    remediation: tuple[RemediationOption, ...]
    validation_rule: ProposedValidationRule


@dataclass(frozen=True, slots=True)
class _RemediationTemplate:
    """One detector's authored remediation content, before `{columns}` is
    substituted. Field names mirror `RemediationOption` exactly except
    `remediation_id`/`evidence_ids` (assigned by the caller — see
    `build_deterministic_guidance`)."""

    action_summary: str
    responsible_role: str
    urgency: str
    historical_correction_guidance: str
    source_system_prevention_guidance: str
    risk_warning: str
    verification_step: str


@dataclass(frozen=True, slots=True)
class _Template:
    impact: tuple[tuple[str, str], ...]  # (statement, assumption)
    remediation: _RemediationTemplate
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
        remediation=_RemediationTemplate(
            action_summary=(
                "Confirm whether the repeated rows are true duplicates, then remove or "
                "merge them in the source system."
            ),
            responsible_role="The person who owns or enters data in the source system",
            urgency="Before the next report that counts or totals these rows",
            historical_correction_guidance=(
                "Check whether the repeated rows are true duplicates or legitimate "
                "repeated records."
            ),
            source_system_prevention_guidance=(
                "If they are true duplicates, remove or merge them in the source system; "
                "TrustTable never edits your file."
            ),
            risk_warning=(
                "Removing a row that only looks like a duplicate could delete a "
                "legitimate repeated transaction; confirm each one individually before "
                "deleting."
            ),
            verification_step=(
                "Re-run this check after the source system is updated and confirm the "
                "duplicate count drops to zero."
            ),
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
        remediation=_RemediationTemplate(
            action_summary=(
                "Confirm whether {columns} should hold data and fix the export or mapping "
                "that produces it."
            ),
            responsible_role="The person who maintains the export or integration",
            urgency="Before this data is used in the next report",
            historical_correction_guidance=(
                "Confirm whether {columns} should contain data and, if so, fix the export "
                "or mapping that produces it."
            ),
            source_system_prevention_guidance=(
                "If the column is not needed, leave it out of the export."
            ),
            risk_warning=(
                "Leaving a genuinely required column empty can silently hide missing "
                "information from downstream reports; do not assume the column is unused "
                "without checking."
            ),
            verification_step=(
                "Re-run this check after fixing the export and confirm the column now "
                "contains the expected values."
            ),
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
        remediation=_RemediationTemplate(
            action_summary=(
                "Find out why {columns} is missing values, then fill in or correct them "
                "at the source."
            ),
            responsible_role="The person who owns the source system or data-entry process",
            urgency="Before {columns} is used in any calculation or filter",
            historical_correction_guidance=(
                "Find out why values in {columns} are missing (an optional field, a "
                "failed export or a data-entry gap) before deciding how to handle them."
            ),
            source_system_prevention_guidance=(
                "Fill in or correct the missing values in the source system where the "
                "true value is known."
            ),
            risk_warning=(
                "Filling in missing values with a guessed default can be worse than "
                "leaving them blank; only fill in values you can verify from the source."
            ),
            verification_step=(
                "Re-run this check after correction and confirm the missing share has dropped."
            ),
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
        remediation=_RemediationTemplate(
            action_summary="Recover the missing identifiers in {columns} from the source system.",
            responsible_role="The person who owns the source system",
            urgency="Before these records are joined or reconciled with other data",
            historical_correction_guidance=(
                "Recover the missing identifiers in {columns} from the source system."
            ),
            source_system_prevention_guidance=(
                "Decide whether records that cannot be identified should be excluded "
                "from analysis until they are corrected."
            ),
            risk_warning=(
                "Assigning a new identifier without confirming the original risks "
                "merging two different records together; only restore identifiers you "
                "can verify."
            ),
            verification_step=(
                "Confirm the recovered identifiers match the source system's own "
                "records before using them."
            ),
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
        remediation=_RemediationTemplate(
            action_summary=(
                "Agree on one canonical spelling for each category and standardize "
                "{columns} in the source system."
            ),
            responsible_role="The person who maintains the source system or data-entry standards",
            urgency="Before the next grouped or filtered report",
            historical_correction_guidance=(
                "Standardize the capitalization of values in {columns} in the source system."
            ),
            source_system_prevention_guidance="Agree on one canonical spelling for each category.",
            risk_warning=(
                "Standardizing capitalization by find-and-replace can silently rewrite "
                "an unrelated value that happens to match; review the affected values "
                "before changing them at the source."
            ),
            verification_step=(
                "Re-run this check and confirm the values now group as a single category."
            ),
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
        remediation=_RemediationTemplate(
            action_summary=(
                "Trim leading and trailing spaces from {columns} at the source and add "
                "trimming to the export or entry process."
            ),
            responsible_role="The person who maintains the export or entry form",
            urgency="Before this column is used for matching or grouping",
            historical_correction_guidance=(
                "Trim leading and trailing spaces from values in {columns} at the source."
            ),
            source_system_prevention_guidance=(
                "Add trimming to the process that exports or enters this data."
            ),
            risk_warning=(
                "Automated trimming tools can also strip meaningful spacing inside a "
                "value if applied too broadly; trim only leading and trailing "
                "whitespace, not internal spacing."
            ),
            verification_step=(
                "Re-run this check and confirm no values remain with leading or trailing "
                "whitespace."
            ),
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
        remediation=_RemediationTemplate(
            action_summary="Check the flagged rows and correct any mistyped dates in the source.",
            responsible_role="The person who entered or owns the record",
            urgency="Before this data is used in a time-based report",
            historical_correction_guidance=(
                "Check the flagged rows and correct any mistyped dates in the source."
            ),
            source_system_prevention_guidance=(
                "If the dates are genuine scheduled events, consider keeping them in a "
                "separate field."
            ),
            risk_warning=(
                "Changing a date without checking the original document can turn a "
                "genuine future-dated event into an incorrect one; verify against the "
                "source document first."
            ),
            verification_step="Re-run this check and confirm no unexpected future dates remain.",
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
        remediation=_RemediationTemplate(
            action_summary=(
                "Review the flagged rows to tell legitimate adjustments from entry "
                "errors, then correct errors in the source."
            ),
            responsible_role="The person who owns the source system",
            urgency="Before this column is totalled or averaged",
            historical_correction_guidance=(
                "Review the flagged rows to tell legitimate adjustments from entry errors."
            ),
            source_system_prevention_guidance="Correct erroneous values in the source system.",
            risk_warning=(
                "Treating every negative value as an error could remove a legitimate "
                "refund or adjustment; confirm each flagged row individually."
            ),
            verification_step=(
                "Re-run this check and confirm only expected negative values, if any, remain."
            ),
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
        remediation=_RemediationTemplate(
            action_summary=(
                "Check whether {columns} was entered inconsistently as fractions and "
                "whole numbers, then correct out-of-range values at the source."
            ),
            responsible_role="The person who owns the source system",
            urgency="Before this percentage is used in a calculation",
            historical_correction_guidance=(
                "Check whether values in {columns} were entered inconsistently as "
                "fractions and whole numbers."
            ),
            source_system_prevention_guidance="Correct out-of-range values in the source system.",
            risk_warning=(
                "Rescaling every value by 100 without checking can turn an "
                "already-correct percentage into a wrong one; confirm each flagged "
                "value's original scale first."
            ),
            verification_step="Re-run this check and confirm all values fall within 0-100.",
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
        remediation=_RemediationTemplate(
            action_summary=(
                "Compare the flagged rows' total with the fields it should be computed "
                "from and correct the wrong value at the source."
            ),
            responsible_role="The person who owns the source system or reconciliation process",
            urgency="Before this total is used in reporting or reconciliation",
            historical_correction_guidance=(
                "Compare the flagged rows' total with the fields it is computed from to "
                "see which value is wrong."
            ),
            source_system_prevention_guidance=(
                "Correct the wrong value in the source, or recompute the total there."
            ),
            risk_warning=(
                "Recomputing and overwriting the stored total without checking which "
                "side is wrong could replace a correct total with an incorrect one; "
                "identify the actual error first."
            ),
            verification_step=(
                "Re-run this check and confirm the total and its components now agree "
                "within tolerance."
            ),
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
        remediation=_RemediationTemplate(
            action_summary=(
                "Confirm whether a single value is expected for {columns}; if not, check "
                "the process that fills it in."
            ),
            responsible_role="The person who maintains the source system or integration",
            urgency="Before this column is relied on to vary",
            historical_correction_guidance=(
                "Confirm whether a single value is expected for {columns}."
            ),
            source_system_prevention_guidance=(
                "If it is not, check the process that fills the column in."
            ),
            risk_warning=(
                "Assuming the constant value is always wrong could mask a legitimately "
                "fixed field, such as a fixed currency code; confirm the expected "
                "behavior before changing anything."
            ),
            verification_step=(
                "Re-run this check after the process is fixed and confirm the column "
                "now varies as expected."
            ),
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
        remediation=_RemediationTemplate(
            action_summary=(
                "Review the flagged rows to see whether the extreme values in {columns} "
                "are genuine, then correct entry errors at the source."
            ),
            responsible_role="The person who owns the source system",
            urgency="Before this column feeds an average, total or threshold",
            historical_correction_guidance=(
                "Review the flagged rows to see whether the extreme values in {columns} "
                "are genuine."
            ),
            source_system_prevention_guidance=(
                "Correct entry errors at the source; keep genuine extreme values but "
                "consider reporting them separately."
            ),
            risk_warning=(
                "Removing or capping a genuine extreme value could hide a real event, "
                "such as a large but valid order; confirm each flagged value "
                "individually."
            ),
            verification_step=(
                "Re-run this check and confirm remaining extreme values are genuine and expected."
            ),
        ),
        rule_type=ValidationRuleType.NUMERIC_RANGE,
        rule_description=(
            "Values in {columns} should stay within a plausible range agreed with the data owner."
        ),
    ),
    "completeness.fully_empty_rows": _Template(
        impact=(
            (
                "Rows with no values add nothing to the analysis, but they are still counted "
                "as records and can inflate row totals and missing-value percentages.",
                "row counts or missing-value percentages from this file are reported or compared",
            ),
        ),
        remediation=_RemediationTemplate(
            action_summary=(
                "Find out where the blank rows come from, such as stray blank lines or a "
                "padded export, and remove them at the source."
            ),
            responsible_role="The person who maintains the export or enters the data",
            urgency="Before row counts from this file are reported",
            historical_correction_guidance=(
                "Check the flagged rows to confirm they are blank, then remove them in the "
                "source system or the export."
            ),
            source_system_prevention_guidance=(
                "Stop the export or entry process from writing blank rows, for example by "
                "trimming trailing empty lines."
            ),
            risk_warning=(
                "A row that looks blank here could hold data in a column this file does not "
                "include; confirm in the source before deleting any record."
            ),
            verification_step=(
                "Re-run this check after the source is fixed and confirm no blank rows remain."
            ),
        ),
        rule_type=ValidationRuleType.NOT_NULL,
        rule_description="Every row should have a value in at least one column.",
    ),
    "consistency.inconsistent_booleans": _Template(
        impact=(
            (
                "The same yes/no answer written in different ways, such as Y, yes and TRUE, "
                "can be counted as separate values or dropped by a filter that expects only "
                "one spelling.",
                "the column is filtered, counted or converted to true/false",
            ),
        ),
        remediation=_RemediationTemplate(
            action_summary=(
                "Agree on one spelling for the yes/no values in {columns} and standardize "
                "it in the source system."
            ),
            responsible_role="The person who maintains the source system or data-entry standards",
            urgency="Before the next report that filters or counts on this column",
            historical_correction_guidance=(
                "Standardize the yes/no values in {columns} to the one agreed spelling in the "
                "source system."
            ),
            source_system_prevention_guidance=(
                "Restrict the field to a single yes/no spelling, for example a checkbox or a "
                "fixed list."
            ),
            risk_warning=(
                "Single letters such as Y or T may not mean yes or true in your data; confirm "
                "what each spelling means before converting them."
            ),
            verification_step=(
                "Re-run this check and confirm the column now uses a single spelling."
            ),
        ),
        rule_type=ValidationRuleType.ACCEPTED_VALUES,
        rule_description="Values in {columns} should use one agreed yes/no spelling.",
    ),
    "validity.implausibly_old_dates": _Template(
        impact=(
            (
                "Dates far in the past are often placeholders or typing errors, and they can "
                "distort ages, durations and time-based groupings.",
                "the column is used for ages, durations, time ranges or sorting by date",
            ),
        ),
        remediation=_RemediationTemplate(
            action_summary=(
                "Check the flagged rows in {columns} and replace placeholder or mistyped "
                "dates with the real ones in the source."
            ),
            responsible_role="The person who entered or owns the record",
            urgency="Before this column is used for time-based reporting",
            historical_correction_guidance=(
                "Check the flagged rows in {columns} against the original records and correct "
                "any placeholder or mistyped dates."
            ),
            source_system_prevention_guidance=(
                "If a date is unknown, leave it blank instead of using a placeholder such as "
                "an early default date."
            ),
            risk_warning=(
                "Some datasets hold genuine historical dates; replacing a real old date with "
                "a guess would damage correct data, so confirm each one against its source."
            ),
            verification_step=(
                "Re-run this check and confirm no unexpected dates before 1900 remain."
            ),
        ),
        rule_type=ValidationRuleType.DATE_RANGE,
        rule_description="Dates in {columns} should not be earlier than 1900-01-01.",
    ),
    "validity.invalid_email_shape": _Template(
        impact=(
            (
                "Entries that are not email addresses can make messages bounce or be skipped, "
                "and they hide customers who cannot be contacted.",
                "the column is used to contact people or to match records by email",
            ),
        ),
        remediation=_RemediationTemplate(
            action_summary=(
                "Review the flagged entries in {columns} and correct or remove the ones that "
                "are not email addresses."
            ),
            responsible_role="The person who owns the contact records",
            urgency="Before this column is used to send messages or match records",
            historical_correction_guidance=(
                "Review the flagged entries in {columns} against the source records and fix "
                "typing errors, such as a missing @ or domain."
            ),
            source_system_prevention_guidance=(
                "Validate the email format where addresses are entered, and keep other "
                "contact details in their own fields."
            ),
            risk_warning=(
                "Email addresses are personal data; handle the flagged rows only as your "
                "data-protection rules allow, and do not guess a correction."
            ),
            verification_step=(
                "Re-run this check and confirm every remaining entry has the shape of an "
                "email address."
            ),
        ),
        rule_type=ValidationRuleType.REGEX,
        rule_description=(
            "Values in {columns} should have the shape of an email address, such as "
            "name@example.com."
        ),
    ),
    "consistency.numeric_values_stored_as_text": _Template(
        impact=(
            (
                "Numbers written with currency symbols, percent signs or thousands separators "
                "are read as text, so totals, averages and sorting can silently skip or "
                "misorder them.",
                "the column is summed, averaged, sorted or compared as numbers",
            ),
        ),
        remediation=_RemediationTemplate(
            action_summary=(
                "Store the values in {columns} as plain numbers, and keep the currency or "
                "percent meaning in the column name or a separate column."
            ),
            responsible_role="The person who maintains the export or the source system",
            urgency="Before this column is totalled, averaged or sorted",
            historical_correction_guidance=(
                "Convert the values in {columns} to plain numbers, after confirming what "
                "each symbol means, for example which currency."
            ),
            source_system_prevention_guidance=(
                "Export numbers without symbols or separators, and record the unit once, "
                "for example in the column name."
            ),
            risk_warning=(
                "Removing a symbol can lose its meaning, such as mixed currencies or a "
                "percentage versus a fraction; confirm the unit before converting."
            ),
            verification_step=(
                "Re-run this check and confirm the column is now read as a numeric column."
            ),
        ),
        rule_type=ValidationRuleType.REGEX,
        rule_description=(
            "Values in {columns} should be plain numbers, without currency symbols, percent "
            "signs or thousands separators."
        ),
    ),
    "consistency.near_duplicate_categories": _Template(
        impact=(
            (
                "The same category written with different punctuation or spacing can be "
                "split into separate groups in summaries and filters.",
                "the column is used for grouping, filtering or joining",
            ),
        ),
        remediation=_RemediationTemplate(
            action_summary=(
                "Agree on one spelling for each category and standardize {columns} in the "
                "source system."
            ),
            responsible_role="The person who maintains the source system or data-entry standards",
            urgency="Before the next grouped or filtered report",
            historical_correction_guidance=(
                "Standardize the punctuation and spacing of the category values in {columns} "
                "in the source system."
            ),
            source_system_prevention_guidance=(
                "Use a fixed list of allowed categories instead of free text."
            ),
            risk_warning=(
                "Two spellings that look alike can be genuinely different categories, such "
                "as product codes A-1 and A1; confirm each pair before merging them."
            ),
            verification_step=(
                "Re-run this check and confirm each category now has a single spelling."
            ),
        ),
        rule_type=ValidationRuleType.ACCEPTED_VALUES,
        rule_description="Values in {columns} should come from one agreed list of categories.",
    ),
    "structural.duplicate_normalized_column_name": _Template(
        impact=(
            (
                "Columns whose names read as the same name are easy to mix up, and a tool "
                "that matches columns by name can pick the wrong one or merge them.",
                "people or tools refer to these columns by name",
            ),
        ),
        remediation=_RemediationTemplate(
            action_summary=(
                "Check whether {columns} are the same field exported twice or two different "
                "fields, then give each column one distinct name in the source system."
            ),
            responsible_role="The person who maintains the export or the source system",
            urgency="Before these columns are used in a report, join or import",
            historical_correction_guidance=(
                "Compare the values of {columns}, then rename or remove the extra column so "
                "that every column has its own distinct name."
            ),
            source_system_prevention_guidance=(
                "Give every column a distinct name in the export, so that names cannot be "
                "confused by case, spacing or punctuation."
            ),
            risk_warning=(
                "Two columns with similar names can hold different data, such as a billing "
                "and a shipping value; confirm what each holds before removing or merging "
                "one."
            ),
            verification_step=(
                "Re-run this check and confirm each of these columns now has a distinct name."
            ),
        ),
        rule_type=ValidationRuleType.CONDITIONAL_RULE,
        rule_description=(
            "Once you have decided which names are correct, define a rule that every "
            "column name is distinct, including {columns}."
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
        remediation=_RemediationTemplate(
            action_summary=(
                "Review the flagged cells and remove instruction-like text that does not "
                "belong in the data."
            ),
            responsible_role="The person who owns the source system or data-entry process",
            urgency="Before this column is passed to any AI tool",
            historical_correction_guidance=(
                "Review the flagged cells and remove instruction-like text that does not "
                "belong in the data."
            ),
            source_system_prevention_guidance=(
                "Treat the contents of {columns} as untrusted whenever they are passed to "
                "any AI tool."
            ),
            risk_warning=(
                "Removing text that only looks instruction-like without checking could "
                "delete a legitimate customer comment or note; review each flagged cell "
                "before editing."
            ),
            verification_step=(
                "Re-run this check and confirm the flagged instruction-like content no "
                "longer appears; keep treating {columns} as untrusted for any AI tool."
            ),
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
    remediation=_RemediationTemplate(
        action_summary=(
            "Review the flagged rows and confirm whether the values in {columns} are "
            "correct, then correct genuine errors at the source."
        ),
        responsible_role="The person who owns the source system",
        urgency="Before this data is used in a report or decision",
        historical_correction_guidance=(
            "Review the flagged rows and confirm whether the values in {columns} are correct."
        ),
        source_system_prevention_guidance="Correct genuine errors in the source system.",
        risk_warning=(
            "Correcting a value without confirming it against the source record risks "
            "introducing a new error; verify before changing anything."
        ),
        verification_step=(
            "Re-run this check after correction and confirm the condition no longer appears."
        ),
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
    remediation_template = template.remediation
    remediation = (
        RemediationOption(
            remediation_id="rem.1",
            action_summary=remediation_template.action_summary.format(columns=columns),
            responsible_role=remediation_template.responsible_role,
            urgency=remediation_template.urgency,
            historical_correction_guidance=(
                remediation_template.historical_correction_guidance.format(columns=columns)
            ),
            source_system_prevention_guidance=(
                remediation_template.source_system_prevention_guidance.format(columns=columns)
            ),
            risk_warning=remediation_template.risk_warning,
            verification_step=remediation_template.verification_step.format(columns=columns),
            evidence_ids=finding.evidence_ids,
        ),
    )
    rule = ProposedValidationRule(
        rule_type=template.rule_type,
        columns=finding.affected_columns,
        description=template.rule_description.format(columns=columns),
    )
    return FindingGuidance(business_impact=impact, remediation=remediation, validation_rule=rule)


__all__ = ["GUIDED_DETECTOR_IDS", "FindingGuidance", "build_deterministic_guidance"]
