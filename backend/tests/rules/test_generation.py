"""Tests for `rules.generation.generate_rule_proposal` (`RULE-02` slices 1
and 3, `WP-080`/`WP-082`).

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
from trusttable_backend.rules.generation import (
    AI_ASSISTABLE_DETECTOR_IDS,
    GENERATABLE_DETECTOR_IDS,
    extract_ai_assist_candidates,
    generate_rule_proposal,
)


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


# --- statistical.suspiciously_constant_column (RULE-02 slice 3, WP-082) -------


def test_suspiciously_constant_column_generates_accepted_values_from_evidence() -> None:
    """Unlike `consistency.inconsistent_capitalization`, a constant
    column's own `distinct_count == 1` invariant means the detector's
    evidence already carries exactly one candidate value
    (`constant_value`) - deterministic, never AI-assisted."""
    column = col("currency", 8)
    finding = make_finding(
        "statistical.suspiciously_constant_column",
        category=DetectorCategory.STATISTICAL,
        columns=(column,),
    )
    evidence = make_evidence({"non_null_count": 300, "constant_value": "USD"})
    proposal, reason = generate_rule_proposal(finding, evidence, ALL_COLUMNS)
    assert reason is None
    assert proposal is not None
    assert proposal.rule_type is ValidationRuleType.ACCEPTED_VALUES
    assert proposal.parameters.accepted_values == ("USD",)


def test_suspiciously_constant_column_reads_value_verbatim_never_normalized() -> None:
    """The captured value is read exactly as observed - including
    whitespace or mixed case a naive normalization might otherwise
    silently alter - because `detectors/statistical.py`'s own
    `distinct_count == 1` computation already used the identical,
    unnormalized string comparison."""
    finding = make_finding(
        "statistical.suspiciously_constant_column",
        category=DetectorCategory.STATISTICAL,
        columns=(col("notes", 8),),
    )
    evidence = make_evidence({"non_null_count": 12, "constant_value": " N/A "})
    proposal, reason = generate_rule_proposal(finding, evidence, ALL_COLUMNS)
    assert reason is None
    assert proposal is not None
    assert proposal.parameters.accepted_values == (" N/A ",)


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


def test_fully_empty_rows_not_available() -> None:
    """`DET-03` slice 1: "blank in every column" is a property of a whole
    row, and no `RULE-01` rule type expresses it (`not_null` checks one
    named column), so no rule is offered rather than a weaker one."""
    finding = make_finding("completeness.fully_empty_rows", category=DetectorCategory.COMPLETENESS)
    evidence = make_evidence({"empty_row_count": 2, "column_count": 3, "total_row_count": 10})
    proposal, reason = generate_rule_proposal(finding, evidence, ALL_COLUMNS)
    assert proposal is None
    assert reason is not None and "completeness.fully_empty_rows" in reason


def test_inconsistent_booleans_not_available_and_never_ai_assisted() -> None:
    """`DET-03` slice 1: which spelling is canonical is a judgment about
    the owner's data standard, not a calculation, and a deterministic list
    cannot guess it. It is also not on the AI-assisted list, so the choice
    stays with the person."""
    finding = make_finding(
        "consistency.inconsistent_booleans",
        category=DetectorCategory.CONSISTENCY,
        columns=(col("active", 3),),
    )
    evidence = make_evidence(
        {
            "spelling_families": ["y/n", "yes/no"],
            "distinct_spellings": ["Y", "yes"],
            "affected_row_count": 2,
        }
    )
    proposal, reason = generate_rule_proposal(finding, evidence, ALL_COLUMNS)
    assert proposal is None
    assert reason is not None and "consistency.inconsistent_booleans" in reason
    assert "consistency.inconsistent_booleans" not in AI_ASSISTABLE_DETECTOR_IDS
    assert extract_ai_assist_candidates(finding, evidence) is None


def test_implausibly_old_dates_maps_to_a_date_range_read_from_its_evidence() -> None:
    """`DET-03` slice 2: the cutoff the detector applied is the rule's minimum
    date, read verbatim from the finding's own evidence."""
    finding = make_finding(
        "validity.implausibly_old_dates",
        category=DetectorCategory.VALIDITY,
        columns=(col("order_date", 2),),
    )
    evidence = make_evidence(
        {
            "earliest_plausible_date": "1900-01-01",
            "old_date_count": 2,
            "oldest_date_found": "0001-01-01",
        }
    )
    proposal, reason = generate_rule_proposal(finding, evidence, ALL_COLUMNS)
    assert reason is None and proposal is not None
    assert proposal.rule_type is ValidationRuleType.DATE_RANGE
    assert proposal.parameters.minimum_date == date(1900, 1, 1)
    assert proposal.parameters.maximum_date is None


def test_invalid_email_shape_not_available() -> None:
    """`DET-03` slice 2: a `REGEX` rule names the disallowed condition, so a
    faithful shape check would be a negative pattern over values up to 10,000
    characters — a backtracking risk the detector avoids by not using a
    regular expression. No weaker rule is offered in its place."""
    finding = make_finding(
        "validity.invalid_email_shape",
        category=DetectorCategory.VALIDITY,
        columns=(col("email", 6),),
    )
    evidence = make_evidence(
        {"checked_value_count": 10, "invalid_value_count": 2, "expected_shape": "local@domain.tld"}
    )
    proposal, reason = generate_rule_proposal(finding, evidence, ALL_COLUMNS)
    assert proposal is None
    assert reason is not None and "validity.invalid_email_shape" in reason


def test_numeric_values_stored_as_text_not_available() -> None:
    """`DET-03` slice 3: no rule type says "this column must be numeric", and
    `NUMERIC_RANGE` presupposes values the engine can already read as numbers,
    which these are not. No weaker rule is offered in its place."""
    finding = make_finding(
        "consistency.numeric_values_stored_as_text",
        category=DetectorCategory.CONSISTENCY,
        columns=(col("amount", 4),),
    )
    evidence = make_evidence(
        {
            "checked_value_count": 10,
            "numeric_like_count": 10,
            "decorated_value_count": 8,
            "decorations": ["currency symbol"],
        }
    )
    proposal, reason = generate_rule_proposal(finding, evidence, ALL_COLUMNS)
    assert proposal is None
    assert reason is not None and "consistency.numeric_values_stored_as_text" in reason


def test_near_duplicate_categories_not_available_and_never_ai_assisted() -> None:
    """`DET-03` slice 3: which spelling is canonical is the owner's choice,
    and the detector is not on the AI-assisted list."""
    finding = make_finding(
        "consistency.near_duplicate_categories",
        category=DetectorCategory.CONSISTENCY,
        columns=(col("city", 7),),
    )
    evidence = make_evidence(
        {"variant_count": 2, "variants_shown": ["new york", "new-york"], "affected_row_count": 4}
    )
    proposal, reason = generate_rule_proposal(finding, evidence, ALL_COLUMNS)
    assert proposal is None
    assert reason is not None and "consistency.near_duplicate_categories" in reason
    assert "consistency.near_duplicate_categories" not in AI_ASSISTABLE_DETECTOR_IDS
    assert extract_ai_assist_candidates(finding, evidence) is None


def test_duplicate_normalized_column_name_not_available_and_never_ai_assisted() -> None:
    """`DET-03` slice 4: no rule type expresses that column names are distinct,
    and which name is right is the owner's choice."""
    finding = make_finding(
        "structural.duplicate_normalized_column_name",
        category=DetectorCategory.STRUCTURAL,
        columns=(col("order_id", 1), col("Order ID", 2)),
    )
    evidence = make_evidence({"column_count": 2, "ordinals": [1, 2], "identical_as_written": False})
    proposal, reason = generate_rule_proposal(finding, evidence, ALL_COLUMNS)
    assert proposal is None
    assert reason is not None and "structural.duplicate_normalized_column_name" in reason
    assert "structural.duplicate_normalized_column_name" not in AI_ASSISTABLE_DETECTOR_IDS
    assert "structural.duplicate_normalized_column_name" not in GENERATABLE_DETECTOR_IDS
    assert extract_ai_assist_candidates(finding, evidence) is None


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


def test_generatable_detector_ids_is_exactly_the_disclosed_eleven() -> None:
    assert (
        frozenset(
            {
                "structural.exact_duplicate_rows",
                "structural.empty_column",
                "completeness.excessive_missing_values",
                "completeness.missing_likely_identifier",
                "validity.future_dates",
                "validity.implausibly_old_dates",
                "validity.negative_likely_non_negative_values",
                "validity.invalid_percentages",
                "statistical.extreme_outliers",
                "consistency.leading_trailing_whitespace",
                "statistical.suspiciously_constant_column",
            }
        )
        == GENERATABLE_DETECTOR_IDS
    )


# --- RULE-02 slice 2 (WP-081): AI-assist candidate extraction ---------------


def test_ai_assistable_detector_ids_is_exactly_inconsistent_capitalization() -> None:
    assert frozenset({"consistency.inconsistent_capitalization"}) == AI_ASSISTABLE_DETECTOR_IDS


def test_extract_ai_assist_candidates_returns_evidence_distinct_casings_verbatim() -> None:
    finding = make_finding(
        "consistency.inconsistent_capitalization",
        category=DetectorCategory.CONSISTENCY,
        columns=(col("city", 7),),
    )
    evidence = make_evidence({"distinct_casings": ["ny", "NY"], "affected_row_count": 2})
    assert extract_ai_assist_candidates(finding, evidence) == ("ny", "NY")


def test_extract_ai_assist_candidates_none_for_unsupported_detector() -> None:
    """Every other detector id yields no candidates — including this one,
    which is now fully deterministic (RULE-02 slice 3, WP-082: exactly
    one candidate value, no AI judgment needed), and the 2 categories
    that remain excluded for a `RULE-01` rule-type/regex-length
    structural reason AI cannot repair. The AI-assisted path must never
    silently apply to any of them."""
    finding = make_finding(
        "statistical.suspiciously_constant_column",
        category=DetectorCategory.STATISTICAL,
        columns=(col("currency", 8),),
    )
    evidence = make_evidence({"non_null_count": 300, "constant_value": "USD"})
    assert extract_ai_assist_candidates(finding, evidence) is None


def test_extract_ai_assist_candidates_none_when_payload_missing_distinct_casings() -> None:
    finding = make_finding(
        "consistency.inconsistent_capitalization",
        category=DetectorCategory.CONSISTENCY,
        columns=(col("city", 7),),
    )
    evidence = make_evidence({"affected_row_count": 2})
    assert extract_ai_assist_candidates(finding, evidence) is None


def test_extract_ai_assist_candidates_none_when_fewer_than_two_values() -> None:
    """A single candidate is not a genuine choice — never offered to AI."""
    finding = make_finding(
        "consistency.inconsistent_capitalization",
        category=DetectorCategory.CONSISTENCY,
        columns=(col("city", 7),),
    )
    evidence = make_evidence({"distinct_casings": ["NY"], "affected_row_count": 1})
    assert extract_ai_assist_candidates(finding, evidence) is None


def test_extract_ai_assist_candidates_none_when_referenced_evidence_missing() -> None:
    finding = make_finding(
        "consistency.inconsistent_capitalization",
        category=DetectorCategory.CONSISTENCY,
        columns=(col("city", 7),),
    )
    assert extract_ai_assist_candidates(finding, ()) is None
