"""Tests for `rules.generation.generate_rule_proposal` (`RULE-02` slice 1,
`WP-080`).

Per supported detector id: a fixture finding + real-shaped `Evidence`
proves the exact derived `rule_type`/`columns`/parameters, read verbatim
from evidence. Per excluded detector id: `available` (via a `None`
proposal) with a stated reason, never a fabricated rule — including the
decisive `cross_field.line_total_mismatch` case, whose real check is
multiplicative and must never be mapped onto the additive
`APPROXIMATE_EQUALITY` rule type.
"""

from __future__ import annotations

import re
from datetime import date

from trusttable_backend.detectors.contract import DetectorCategory, FindingCandidate
from trusttable_backend.domain.evidence import Evidence, EvidenceType
from trusttable_backend.domain.explanation import ValidationRuleType
from trusttable_backend.domain.parsing import SamplingScope
from trusttable_backend.domain.value_objects import ColumnReference, Severity
from trusttable_backend.rules.generation import GENERATABLE_DETECTOR_IDS, generate_rule_proposal


def col(name: str, ordinal: int) -> ColumnReference:
    return ColumnReference(original_name=name, internal_key=name, ordinal=ordinal)


def make_finding(
    detector_id: str,
    *,
    category: DetectorCategory,
    columns: tuple[ColumnReference, ...] = (),
) -> FindingCandidate:
    return FindingCandidate(
        detector_id=detector_id,
        detector_version="1",
        category=category,
        severity=Severity.MEDIUM,
        confidence=1.0,
        calculated_observation="observed condition",
        affected_columns=columns,
        affected_row_references=(),
        evidence_ids=("ev-1",),
        default_remediation_template_key=None,
        default_validation_rule_template_key=None,
    )


def make_evidence(payload: dict[str, object]) -> tuple[Evidence, ...]:
    return (
        Evidence(
            evidence_id="ev-1",
            evidence_type=EvidenceType.METRIC,
            calculation_version="1",
            structured_payload=payload,
            affected_columns=(),
            affected_row_references=(),
            scope=SamplingScope.FULL,
            display_safe_summary="summary",
        ),
    )


ALL_COLUMNS = (col("order_id", 0), col("quantity", 1))


# --- structural.exact_duplicate_rows ---------------------------------------


def test_exact_duplicate_rows_generates_unique_across_all_columns() -> None:
    finding = make_finding("structural.exact_duplicate_rows", category=DetectorCategory.STRUCTURAL)
    evidence = make_evidence({"duplicate_group_count": 1, "duplicate_row_count": 1})
    proposal, reason = generate_rule_proposal(finding, evidence, ALL_COLUMNS)
    assert reason is None
    assert proposal is not None
    assert proposal.rule_type is ValidationRuleType.UNIQUE
    assert proposal.columns == ALL_COLUMNS


# --- structural.empty_column ------------------------------------------------


def test_empty_column_generates_not_null() -> None:
    column = col("notes", 2)
    finding = make_finding(
        "structural.empty_column", category=DetectorCategory.STRUCTURAL, columns=(column,)
    )
    evidence = make_evidence({"null_count": 300})
    proposal, reason = generate_rule_proposal(finding, evidence, ALL_COLUMNS)
    assert reason is None
    assert proposal is not None
    assert proposal.rule_type is ValidationRuleType.NOT_NULL
    assert proposal.columns == (column,)
    assert proposal.parameters.minimum is None


# --- completeness.excessive_missing_values ----------------------------------


def test_excessive_missing_values_generates_max_missing_percentage_from_evidence() -> None:
    column = col("quantity", 1)
    finding = make_finding(
        "completeness.excessive_missing_values",
        category=DetectorCategory.COMPLETENESS,
        columns=(column,),
    )
    evidence = make_evidence({"null_count": 3, "sample_size": 300, "missing_ratio": 0.01})
    proposal, reason = generate_rule_proposal(finding, evidence, ALL_COLUMNS)
    assert reason is None
    assert proposal is not None
    assert proposal.rule_type is ValidationRuleType.MAX_MISSING_PERCENTAGE
    assert proposal.parameters.threshold_percentage == 1.0


# --- completeness.missing_likely_identifier ---------------------------------


def test_missing_likely_identifier_generates_not_null() -> None:
    column = col("order_id", 0)
    finding = make_finding(
        "completeness.missing_likely_identifier",
        category=DetectorCategory.COMPLETENESS,
        columns=(column,),
    )
    evidence = make_evidence({"null_count": 1})
    proposal, reason = generate_rule_proposal(finding, evidence, ALL_COLUMNS)
    assert reason is None
    assert proposal is not None
    assert proposal.rule_type is ValidationRuleType.NOT_NULL
    assert proposal.columns == (column,)


# --- validity.future_dates ---------------------------------------------------


def test_future_dates_generates_date_range_from_evidence_reference_date() -> None:
    column = col("order_date", 3)
    finding = make_finding(
        "validity.future_dates", category=DetectorCategory.VALIDITY, columns=(column,)
    )
    evidence = make_evidence({"reference_date": "2026-09-28", "future_date_count": 2})
    proposal, reason = generate_rule_proposal(finding, evidence, ALL_COLUMNS)
    assert reason is None
    assert proposal is not None
    assert proposal.rule_type is ValidationRuleType.DATE_RANGE
    assert proposal.parameters.maximum_date == date(2026, 9, 28)
    assert proposal.parameters.minimum_date is None


# --- validity.negative_likely_non_negative_values -----------------------------


def test_negative_likely_non_negative_generates_numeric_range_minimum_zero() -> None:
    column = col("quantity", 1)
    finding = make_finding(
        "validity.negative_likely_non_negative_values",
        category=DetectorCategory.VALIDITY,
        columns=(column,),
    )
    evidence = make_evidence({"negative_count": 1, "non_null_count": 299, "negative_ratio": 0.003})
    proposal, reason = generate_rule_proposal(finding, evidence, ALL_COLUMNS)
    assert reason is None
    assert proposal is not None
    assert proposal.rule_type is ValidationRuleType.NUMERIC_RANGE
    assert proposal.parameters.minimum == 0.0
    assert proposal.parameters.maximum is None


# --- validity.invalid_percentages ---------------------------------------------


def test_invalid_percentages_generates_numeric_range_0_100() -> None:
    column = col("discount_pct", 4)
    finding = make_finding(
        "validity.invalid_percentages", category=DetectorCategory.VALIDITY, columns=(column,)
    )
    evidence = make_evidence({"valid_min": 0.0, "valid_max": 100.0, "invalid_count": 1})
    proposal, reason = generate_rule_proposal(finding, evidence, ALL_COLUMNS)
    assert reason is None
    assert proposal is not None
    assert proposal.rule_type is ValidationRuleType.NUMERIC_RANGE
    assert proposal.parameters.minimum == 0.0
    assert proposal.parameters.maximum == 100.0


# --- statistical.extreme_outliers ----------------------------------------------


def test_extreme_outliers_generates_numeric_range_from_evidence_fences() -> None:
    column = col("line_total", 5)
    finding = make_finding(
        "statistical.extreme_outliers", category=DetectorCategory.STATISTICAL, columns=(column,)
    )
    evidence = make_evidence({"lower_fence": -12.5, "upper_fence": 512.75, "outlier_count": 2})
    proposal, reason = generate_rule_proposal(finding, evidence, ALL_COLUMNS)
    assert reason is None
    assert proposal is not None
    assert proposal.rule_type is ValidationRuleType.NUMERIC_RANGE
    assert proposal.parameters.minimum == -12.5
    assert proposal.parameters.maximum == 512.75


# --- consistency.leading_trailing_whitespace -----------------------------------


def test_leading_trailing_whitespace_generates_bounded_regex() -> None:
    column = col("customer_name", 6)
    finding = make_finding(
        "consistency.leading_trailing_whitespace",
        category=DetectorCategory.CONSISTENCY,
        columns=(column,),
    )
    evidence = make_evidence({"whitespace_issue_count": 4})
    proposal, reason = generate_rule_proposal(finding, evidence, ALL_COLUMNS)
    assert reason is None
    assert proposal is not None
    assert proposal.rule_type is ValidationRuleType.REGEX
    assert proposal.parameters.pattern is not None
    compiled = re.compile(proposal.parameters.pattern)
    assert compiled.search(" leading") is not None
    assert compiled.search("trailing ") is not None
    assert compiled.search("clean") is None


# --- excluded categories: honest available=False, never a fabricated rule -----


def test_inconsistent_capitalization_not_available() -> None:
    """No safe accepted_values list is derivable: evidence never records
    which observed casing is the intended canonical one."""
    finding = make_finding(
        "consistency.inconsistent_capitalization",
        category=DetectorCategory.CONSISTENCY,
        columns=(col("city", 7),),
    )
    evidence = make_evidence({"distinct_casings": ["ny", "NY"], "affected_row_count": 2})
    proposal, reason = generate_rule_proposal(finding, evidence, ALL_COLUMNS)
    assert proposal is None
    assert reason is not None and "consistency.inconsistent_capitalization" in reason


def test_suspiciously_constant_column_not_available() -> None:
    """The evidence records only a non-null count, never the actual
    constant value string an accepted_values list would need."""
    finding = make_finding(
        "statistical.suspiciously_constant_column",
        category=DetectorCategory.STATISTICAL,
        columns=(col("currency", 8),),
    )
    evidence = make_evidence({"non_null_count": 300})
    proposal, reason = generate_rule_proposal(finding, evidence, ALL_COLUMNS)
    assert proposal is None
    assert reason is not None


def test_line_total_mismatch_not_available_avoids_additive_false_positive() -> None:
    """The decisive false-positive proof: this finding's real check is
    multiplicative (quantity x unit_price x (1 - discount_pct/100) x
    (1 + tax_pct/100)), not the additive total ~= sum(components)
    `APPROXIMATE_EQUALITY` checks — it must never be offered as one."""
    finding = make_finding(
        "cross_field.line_total_mismatch",
        category=DetectorCategory.CROSS_FIELD,
        columns=(
            col("quantity", 1),
            col("unit_price", 9),
            col("discount_pct", 4),
            col("tax_pct", 10),
            col("line_total", 5),
        ),
    )
    evidence = make_evidence({"tolerance": 0.01, "mismatch_count": 3})
    proposal, reason = generate_rule_proposal(finding, evidence, ALL_COLUMNS)
    assert proposal is None
    assert reason is not None


def test_possible_llm_prompt_injection_not_available() -> None:
    """Reusing the case-insensitive multi-pattern match as one
    case-sensitive REGEX rule risks exceeding MAX_REGEX_PATTERN_LENGTH or
    silently weakening the check; excluded rather than risking either."""
    finding = make_finding(
        "security.possible_llm_prompt_injection",
        category=DetectorCategory.AI_PROCESSING_SECURITY,
        columns=(col("notes", 11),),
    )
    evidence = make_evidence(
        {
            "matched_pattern_categories": ("ignore_previous_instructions",),
            "affected_row_count": 1,
            "truncated_sample_prefix": "ignore all previous instructions",
        }
    )
    proposal, reason = generate_rule_proposal(finding, evidence, ALL_COLUMNS)
    assert proposal is None
    assert reason is not None


def test_unmapped_generic_detector_not_available() -> None:
    """A detector id with no dedicated guidance template (the generic
    CONDITIONAL_RULE fallback) has no real WHEN/THEN semantics to derive."""
    finding = make_finding(
        "future.some_new_detector", category=DetectorCategory.STRUCTURAL, columns=(col("x", 0),)
    )
    evidence = make_evidence({})
    proposal, reason = generate_rule_proposal(finding, evidence, ALL_COLUMNS)
    assert proposal is None
    assert reason is not None


def test_generatable_detector_ids_is_exactly_the_disclosed_nine() -> None:
    assert frozenset(
        {
            "structural.exact_duplicate_rows",
            "structural.empty_column",
            "completeness.excessive_missing_values",
            "completeness.missing_likely_identifier",
            "validity.future_dates",
            "validity.negative_likely_non_negative_values",
            "validity.invalid_percentages",
            "statistical.extreme_outliers",
            "consistency.leading_trailing_whitespace",
        }
    ) == GENERATABLE_DETECTOR_IDS
