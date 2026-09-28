"""Tests for `rules.engine.execute_rule` (`RULE-01`).

Every rule type gets a positive case (all rows pass), a negative case
(exact fail_count and example row numbers proven), a null-handling case,
and a boundary case where one exists. Slice 2 (`WP-079`) adds
`expression_comparison`/`conditional_rule`, including the
vacuous-WHEN-false proof for `conditional_rule`.
"""

from __future__ import annotations

from datetime import UTC, date, datetime

from trusttable_backend.domain.explanation import ValidationRuleType
from trusttable_backend.domain.rules import (
    ComparisonOperator,
    NullHandling,
    RuleExecutionResult,
    ValidationRule,
)
from trusttable_backend.domain.value_objects import ColumnReference, Severity
from trusttable_backend.rules.engine import execute_rule

NOW = datetime.now(UTC)


def col(name: str = "quantity", ordinal: int = 0) -> ColumnReference:
    return ColumnReference(original_name=name, internal_key=name, ordinal=ordinal)


def make_rule(**overrides: object) -> ValidationRule:
    fields: dict[str, object] = {
        "rule_id": "rule-1",
        "schema_version": "validation_rule_v1",
        "name": "test rule",
        "description": "test rule",
        "severity": Severity.MEDIUM,
        "rule_type": ValidationRuleType.NOT_NULL,
        "columns": (col(),),
    }
    fields.update(overrides)
    return ValidationRule(**fields)  # type: ignore[arg-type]


def run(rule: ValidationRule, rows: tuple[tuple[str | None, ...], ...]) -> RuleExecutionResult:
    return execute_rule(rule, rows, analysis_id="an-1", now=NOW)


# --- not_null ---------------------------------------------------------


def test_not_null_all_pass() -> None:
    result = run(make_rule(), (("1",), ("2",), ("3",)))
    assert result.pass_count == 3 and result.fail_count == 0


def test_not_null_reports_exact_failures() -> None:
    result = run(make_rule(), (("1",), (None,), ("",), ("4",)))
    assert result.pass_count == 2
    assert result.fail_count == 2
    assert {example.row.row_number for example in result.example_failures} == {1, 2}


# --- accepted_values ----------------------------------------------------


def test_accepted_values_positive_and_negative() -> None:
    rule = make_rule(rule_type=ValidationRuleType.ACCEPTED_VALUES, accepted_values=("A", "B"))
    result = run(rule, (("A",), ("B",), ("C",)))
    assert result.pass_count == 2 and result.fail_count == 1


def test_accepted_values_null_handling_skip_by_default() -> None:
    rule = make_rule(rule_type=ValidationRuleType.ACCEPTED_VALUES, accepted_values=("A",))
    result = run(rule, (("A",), (None,)))
    assert result.pass_count == 1 and result.skipped_count == 1 and result.fail_count == 0


def test_accepted_values_null_handling_fail_when_configured() -> None:
    rule = make_rule(
        rule_type=ValidationRuleType.ACCEPTED_VALUES,
        accepted_values=("A",),
        null_handling=NullHandling.FAIL,
    )
    result = run(rule, (("A",), (None,)))
    assert result.pass_count == 1 and result.fail_count == 1 and result.skipped_count == 0


# --- numeric_range --------------------------------------------------------


def test_numeric_range_positive_and_negative() -> None:
    rule = make_rule(rule_type=ValidationRuleType.NUMERIC_RANGE, minimum=0.0, maximum=100.0)
    result = run(rule, (("50",), ("-1",), ("150",)))
    assert result.pass_count == 1 and result.fail_count == 2


def test_numeric_range_inclusive_boundary() -> None:
    rule = make_rule(rule_type=ValidationRuleType.NUMERIC_RANGE, minimum=0.0, maximum=100.0)
    result = run(rule, (("0",), ("100",)))
    assert result.pass_count == 2 and result.fail_count == 0


def test_numeric_range_non_numeric_value_fails_not_skips() -> None:
    rule = make_rule(rule_type=ValidationRuleType.NUMERIC_RANGE, minimum=0.0)
    result = run(rule, (("abc",),))
    assert result.fail_count == 1 and result.skipped_count == 0
    assert "not numeric" in result.example_failures[0].reason


def test_numeric_range_null_is_skipped_by_default() -> None:
    rule = make_rule(rule_type=ValidationRuleType.NUMERIC_RANGE, minimum=0.0)
    result = run(rule, ((None,),))
    assert result.skipped_count == 1


# --- date_range -----------------------------------------------------------


def test_date_range_positive_and_negative() -> None:
    rule = make_rule(
        rule_type=ValidationRuleType.DATE_RANGE,
        maximum_date=date(2026, 1, 1),
    )
    result = run(rule, (("2025-06-01",), ("2026-06-01",)))
    assert result.pass_count == 1 and result.fail_count == 1


def test_date_range_boundary_is_inclusive() -> None:
    rule = make_rule(rule_type=ValidationRuleType.DATE_RANGE, maximum_date=date(2026, 1, 1))
    result = run(rule, (("2026-01-01",),))
    assert result.pass_count == 1


def test_date_range_malformed_value_fails() -> None:
    rule = make_rule(rule_type=ValidationRuleType.DATE_RANGE, maximum_date=date(2026, 1, 1))
    result = run(rule, (("not-a-date",),))
    assert result.fail_count == 1


# --- regex ------------------------------------------------------------


def test_regex_pattern_names_the_disallowed_condition() -> None:
    rule = make_rule(rule_type=ValidationRuleType.REGEX, pattern=r"^\s|\s$")
    result = run(rule, (("clean",), (" leading",), ("trailing ",)))
    assert result.pass_count == 1 and result.fail_count == 2


def test_regex_null_handling_default_skip() -> None:
    rule = make_rule(rule_type=ValidationRuleType.REGEX, pattern=r"x")
    result = run(rule, ((None,),))
    assert result.skipped_count == 1


# --- max_missing_percentage -------------------------------------------


def test_max_missing_percentage_reports_raw_incident_count() -> None:
    rule = make_rule(rule_type=ValidationRuleType.MAX_MISSING_PERCENTAGE, threshold_percentage=10.0)
    result = run(rule, (("1",), (None,), ("",), ("4",)))
    assert result.pass_count == 2 and result.fail_count == 2
    assert result.fail_count / (result.pass_count + result.fail_count) == 0.5


# --- unique / max_duplicate_percentage (shared grouping mechanic) ------


def test_unique_positive_case_no_duplicates() -> None:
    rule = make_rule(rule_type=ValidationRuleType.UNIQUE, columns=(col(),))
    result = run(rule, (("1",), ("2",), ("3",)))
    assert result.pass_count == 3 and result.fail_count == 0


def test_unique_flags_every_row_in_a_duplicate_group() -> None:
    rule = make_rule(rule_type=ValidationRuleType.UNIQUE, columns=(col(),))
    result = run(rule, (("1",), ("1",), ("2",)))
    assert result.pass_count == 1 and result.fail_count == 2
    assert {example.row.row_number for example in result.example_failures} == {0, 1}


def test_unique_composite_key_across_two_columns() -> None:
    rule = make_rule(rule_type=ValidationRuleType.UNIQUE, columns=(col("a", 0), col("b", 1)))
    result = run(rule, (("1", "x"), ("1", "y"), ("1", "x")))
    assert result.fail_count == 2 and result.pass_count == 1


def test_unique_null_key_component_is_skipped_by_default() -> None:
    rule = make_rule(rule_type=ValidationRuleType.UNIQUE, columns=(col(),))
    result = run(rule, ((None,), ("1",)))
    assert result.skipped_count == 1 and result.pass_count == 1


def test_max_duplicate_percentage_uses_the_same_grouping_mechanic() -> None:
    rule = make_rule(
        rule_type=ValidationRuleType.MAX_DUPLICATE_PERCENTAGE,
        columns=(col(),),
        threshold_percentage=50.0,
    )
    result = run(rule, (("1",), ("1",), ("2",)))
    assert result.fail_count == 2 and result.pass_count == 1


# --- approximate_equality ----------------------------------------------


def test_approximate_equality_positive_and_negative() -> None:
    rule = make_rule(
        rule_type=ValidationRuleType.APPROXIMATE_EQUALITY,
        columns=(col("total", 0), col("a", 1), col("b", 2)),
        tolerance=0.01,
    )
    result = run(rule, (("10", "4", "6"), ("10", "4", "5")))
    assert result.pass_count == 1 and result.fail_count == 1


def test_approximate_equality_within_tolerance_passes() -> None:
    rule = make_rule(
        rule_type=ValidationRuleType.APPROXIMATE_EQUALITY,
        columns=(col("total", 0), col("a", 1), col("b", 2)),
        tolerance=0.5,
    )
    result = run(rule, (("10.0", "4.0", "5.8"),))
    assert result.pass_count == 1


def test_approximate_equality_null_handling_default_skip() -> None:
    rule = make_rule(
        rule_type=ValidationRuleType.APPROXIMATE_EQUALITY,
        columns=(col("total", 0), col("a", 1)),
        tolerance=0.01,
    )
    result = run(rule, ((None, "4"),))
    assert result.skipped_count == 1


# --- expression_comparison ----------------------------------------------


def test_expression_comparison_against_a_literal_positive_and_negative() -> None:
    rule = make_rule(
        rule_type=ValidationRuleType.EXPRESSION_COMPARISON,
        comparison_operator=ComparisonOperator.GREATER_THAN,
        comparison_value=0.0,
    )
    result = run(rule, (("5",), ("-1",), ("0",)))
    assert result.pass_count == 1 and result.fail_count == 2


def test_expression_comparison_against_a_column_positive_and_negative() -> None:
    rule = make_rule(
        rule_type=ValidationRuleType.EXPRESSION_COMPARISON,
        columns=(col("price", 0), col("cost", 1)),
        comparison_operator=ComparisonOperator.GREATER_THAN,
    )
    result = run(rule, (("10", "4"), ("3", "4")))
    assert result.pass_count == 1 and result.fail_count == 1


def test_expression_comparison_non_numeric_value_fails_not_skips() -> None:
    rule = make_rule(
        rule_type=ValidationRuleType.EXPRESSION_COMPARISON,
        comparison_operator=ComparisonOperator.GREATER_THAN,
        comparison_value=0.0,
    )
    result = run(rule, (("abc",),))
    assert result.fail_count == 1 and result.skipped_count == 0
    assert "not numeric" in result.example_failures[0].reason


def test_expression_comparison_null_is_skipped_by_default() -> None:
    rule = make_rule(
        rule_type=ValidationRuleType.EXPRESSION_COMPARISON,
        columns=(col("price", 0), col("cost", 1)),
        comparison_operator=ComparisonOperator.GREATER_THAN,
    )
    result = run(rule, ((None, "4"),))
    assert result.skipped_count == 1


def test_expression_comparison_equals_boundary() -> None:
    rule = make_rule(
        rule_type=ValidationRuleType.EXPRESSION_COMPARISON,
        comparison_operator=ComparisonOperator.EQUALS,
        comparison_value=5.0,
    )
    result = run(rule, (("5",), ("5.0",), ("6",)))
    assert result.pass_count == 2 and result.fail_count == 1


# --- conditional_rule -----------------------------------------------------


def _conditional_rule(**overrides: object) -> ValidationRule:
    fields: dict[str, object] = {
        "rule_type": ValidationRuleType.CONDITIONAL_RULE,
        "columns": (col("status", 0), col("ship_date_offset", 1)),
        "condition_operator": ComparisonOperator.EQUALS,
        "condition_value": 1.0,
        "comparison_operator": ComparisonOperator.GREATER_THAN,
        "comparison_value": 0.0,
    }
    fields.update(overrides)
    return make_rule(**fields)


def test_conditional_rule_when_false_passes_vacuously_and_never_evaluates_then() -> None:
    rule = _conditional_rule()
    # status != 1 (WHEN false): the THEN column holds an obviously-failing
    # value ("-5"), but must never be evaluated or counted.
    result = run(rule, (("0", "-5"),))
    assert result.pass_count == 1 and result.fail_count == 0 and result.skipped_count == 0


def test_conditional_rule_when_true_then_true_passes() -> None:
    rule = _conditional_rule()
    result = run(rule, (("1", "3"),))
    assert result.pass_count == 1 and result.fail_count == 0


def test_conditional_rule_when_true_then_false_fails() -> None:
    rule = _conditional_rule()
    result = run(rule, (("1", "-3"),))
    assert result.pass_count == 0 and result.fail_count == 1
    assert "THEN clause is false" in result.example_failures[0].reason


def test_conditional_rule_null_when_column_is_skipped_by_default() -> None:
    rule = _conditional_rule()
    result = run(rule, ((None, "3"),))
    assert result.skipped_count == 1


def test_conditional_rule_null_then_column_is_skipped_only_when_when_is_true() -> None:
    rule = _conditional_rule()
    # WHEN true (status == 1), THEN column missing: follows null_handling.
    result = run(rule, (("1", None),))
    assert result.skipped_count == 1
    # WHEN false (status != 1): THEN column missing is irrelevant, still a pass.
    result = run(rule, (("0", None),))
    assert result.pass_count == 1 and result.skipped_count == 0


def test_conditional_rule_when_column_non_numeric_fails() -> None:
    rule = _conditional_rule()
    result = run(rule, (("abc", "3"),))
    assert result.fail_count == 1
    assert "WHEN value is not numeric" in result.example_failures[0].reason


# --- structural guarantees ----------------------------------------------


def test_module_imports_no_ai_boundary_or_provider() -> None:
    import re
    from pathlib import Path

    source = (
        Path(__file__).resolve().parents[2] / "src" / "trusttable_backend" / "rules" / "engine.py"
    ).read_text(encoding="utf-8")
    import_lines = "\n".join(
        line.strip() for line in source.splitlines() if re.match(r"\s*(from|import)\s+\S", line)
    )
    for forbidden in ("ai_boundary", "ai_provider", "fastapi", "sqlalchemy", "pydantic"):
        assert forbidden not in import_lines
    assert not re.search(r"\b(eval|exec)\s*\(", source)


def test_every_supported_rule_type_has_a_runner() -> None:
    from trusttable_backend.domain.rules import SUPPORTED_RULE_TYPES

    for rule_type in SUPPORTED_RULE_TYPES:
        columns: tuple[ColumnReference, ...]
        extra: dict[str, object] = {}
        if rule_type is ValidationRuleType.UNIQUE:
            columns = (col(),)
        elif rule_type is ValidationRuleType.MAX_DUPLICATE_PERCENTAGE:
            columns = (col(),)
            extra["threshold_percentage"] = 10.0
        elif rule_type is ValidationRuleType.APPROXIMATE_EQUALITY:
            columns = (col("total", 0), col("a", 1))
            extra["tolerance"] = 0.1
        elif rule_type is ValidationRuleType.ACCEPTED_VALUES:
            columns = (col(),)
            extra["accepted_values"] = ("A",)
        elif rule_type is ValidationRuleType.NUMERIC_RANGE:
            columns = (col(),)
            extra["minimum"] = 0.0
        elif rule_type is ValidationRuleType.DATE_RANGE:
            columns = (col(),)
            extra["maximum_date"] = date(2026, 1, 1)
        elif rule_type is ValidationRuleType.REGEX:
            columns = (col(),)
            extra["pattern"] = "x"
        elif rule_type is ValidationRuleType.MAX_MISSING_PERCENTAGE:
            columns = (col(),)
            extra["threshold_percentage"] = 10.0
        elif rule_type is ValidationRuleType.EXPRESSION_COMPARISON:
            columns = (col(),)
            extra["comparison_operator"] = ComparisonOperator.GREATER_THAN
            extra["comparison_value"] = 0.0
        elif rule_type is ValidationRuleType.CONDITIONAL_RULE:
            columns = (col("a", 0), col("b", 1))
            extra["condition_operator"] = ComparisonOperator.EQUALS
            extra["condition_value"] = 1.0
            extra["comparison_operator"] = ComparisonOperator.GREATER_THAN
            extra["comparison_value"] = 0.0
        else:
            columns = (col(),)
        rule = make_rule(rule_type=rule_type, columns=columns, **extra)
        result = run(rule, (("1",) * len(columns),))
        assert result.error is None, (rule_type, result.error)
