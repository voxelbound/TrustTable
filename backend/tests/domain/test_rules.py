"""Tests for `domain.rules.ValidationRule`/`RuleExecutionResult`
(`RULE-01` slice 1, `docs/domain-model.md` §18-19).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from trusttable_backend.domain.explanation import ValidationRuleType
from trusttable_backend.domain.rules import (
    MAX_EXAMPLE_FAILURES,
    NullHandling,
    RuleExecutionResult,
    RuleFailureExample,
    RuleProvenance,
    ValidationRule,
)
from trusttable_backend.domain.value_objects import ColumnReference, RowReference, Severity


def col(name: str = "quantity", ordinal: int = 0) -> ColumnReference:
    return ColumnReference(original_name=name, internal_key=name, ordinal=ordinal)


def make_rule(**overrides: object) -> ValidationRule:
    fields: dict[str, object] = {
        "rule_id": "rule-1",
        "schema_version": "validation_rule_v1",
        "name": "Quantity must not be blank",
        "description": "Every row must have a quantity.",
        "severity": Severity.MEDIUM,
        "rule_type": ValidationRuleType.NOT_NULL,
        "columns": (col(),),
    }
    fields.update(overrides)
    return ValidationRule(**fields)  # type: ignore[arg-type]


def test_a_well_formed_not_null_rule_constructs() -> None:
    rule = make_rule()
    assert rule.rule_type is ValidationRuleType.NOT_NULL
    assert rule.enabled is True
    assert rule.null_handling is NullHandling.SKIP
    assert rule.provenance is RuleProvenance.USER_AUTHORED
    assert rule.source_finding_ids == ()
    assert rule.last_result is None


@pytest.mark.parametrize(
    "rule_type",
    [ValidationRuleType.EXPRESSION_COMPARISON, ValidationRuleType.CONDITIONAL_RULE],
)
def test_expression_based_types_are_rejected_this_slice(rule_type: ValidationRuleType) -> None:
    with pytest.raises(ValueError, match="not supported by RULE-01 slice 1"):
        make_rule(rule_type=rule_type)


@pytest.mark.parametrize(
    "field",
    ["rule_id", "schema_version", "name", "description"],
)
def test_required_text_fields_must_not_be_empty(field: str) -> None:
    with pytest.raises(ValueError, match=field):
        make_rule(**{field: ""})


def test_single_column_type_rejects_zero_or_two_columns() -> None:
    for columns in ((), (col(), col("price", 1))):
        with pytest.raises(ValueError, match="exactly 1 entry"):
            make_rule(columns=columns)


def test_unique_requires_at_least_one_column() -> None:
    with pytest.raises(ValueError, match="at least 1 entry"):
        make_rule(rule_type=ValidationRuleType.UNIQUE, columns=())


def test_unique_accepts_a_composite_key() -> None:
    rule = make_rule(rule_type=ValidationRuleType.UNIQUE, columns=(col("a", 0), col("b", 1)))
    assert len(rule.columns) == 2


def test_approximate_equality_requires_at_least_two_columns() -> None:
    with pytest.raises(ValueError, match="at least 2 entries"):
        make_rule(
            rule_type=ValidationRuleType.APPROXIMATE_EQUALITY,
            columns=(col(),),
            tolerance=0.01,
        )


def test_accepted_values_must_be_non_empty() -> None:
    with pytest.raises(ValueError, match="accepted_values must be non-empty"):
        make_rule(rule_type=ValidationRuleType.ACCEPTED_VALUES, accepted_values=())


def test_accepted_values_rule_constructs_with_values() -> None:
    rule = make_rule(rule_type=ValidationRuleType.ACCEPTED_VALUES, accepted_values=("A", "B"))
    assert rule.accepted_values == ("A", "B")


def test_numeric_range_requires_at_least_one_bound() -> None:
    with pytest.raises(ValueError, match="numeric_range requires"):
        make_rule(rule_type=ValidationRuleType.NUMERIC_RANGE)


def test_numeric_range_rejects_minimum_above_maximum() -> None:
    with pytest.raises(ValueError, match="minimum must not exceed maximum"):
        make_rule(rule_type=ValidationRuleType.NUMERIC_RANGE, minimum=10.0, maximum=5.0)


def test_numeric_range_accepts_a_single_bound() -> None:
    rule = make_rule(rule_type=ValidationRuleType.NUMERIC_RANGE, minimum=0.0)
    assert rule.minimum == 0.0 and rule.maximum is None


def test_date_range_requires_at_least_one_bound() -> None:
    with pytest.raises(ValueError, match="date_range requires"):
        make_rule(rule_type=ValidationRuleType.DATE_RANGE)


def test_regex_requires_a_non_empty_bounded_pattern() -> None:
    with pytest.raises(ValueError, match="pattern must not be empty"):
        make_rule(rule_type=ValidationRuleType.REGEX, pattern="")
    with pytest.raises(ValueError, match="must not exceed"):
        make_rule(rule_type=ValidationRuleType.REGEX, pattern="a" * 500)


def test_regex_rule_constructs_with_a_pattern() -> None:
    rule = make_rule(rule_type=ValidationRuleType.REGEX, pattern=r"^\s|\s$")
    assert rule.pattern == r"^\s|\s$"


@pytest.mark.parametrize(
    "rule_type",
    [ValidationRuleType.MAX_MISSING_PERCENTAGE, ValidationRuleType.MAX_DUPLICATE_PERCENTAGE],
)
def test_percentage_types_require_a_threshold_in_range(rule_type: ValidationRuleType) -> None:
    columns = (col(),) if rule_type is ValidationRuleType.MAX_MISSING_PERCENTAGE else (col(),)
    with pytest.raises(ValueError, match="threshold_percentage"):
        make_rule(rule_type=rule_type, columns=columns)
    for bad in (-1.0, 101.0):
        with pytest.raises(ValueError, match="threshold_percentage"):
            make_rule(rule_type=rule_type, columns=columns, threshold_percentage=bad)


def test_approximate_equality_requires_a_non_negative_tolerance() -> None:
    columns = (col("total", 0), col("a", 1), col("b", 2))
    with pytest.raises(ValueError, match="tolerance"):
        make_rule(rule_type=ValidationRuleType.APPROXIMATE_EQUALITY, columns=columns)
    with pytest.raises(ValueError, match="tolerance"):
        make_rule(
            rule_type=ValidationRuleType.APPROXIMATE_EQUALITY, columns=columns, tolerance=-1.0
        )


def test_a_parameter_field_not_owned_by_the_rule_type_must_be_none() -> None:
    with pytest.raises(ValueError, match="minimum must be None"):
        make_rule(minimum=1.0)  # not_null owns no numeric parameters


def test_scope_must_be_full() -> None:
    from trusttable_backend.domain.parsing import SamplingScope

    with pytest.raises(ValueError, match="scope must be FULL"):
        make_rule(scope=SamplingScope.SAMPLED)


def test_rule_execution_result_constructs_and_validates() -> None:
    result = RuleExecutionResult(
        rule_id="rule-1",
        analysis_id="an-1",
        executed_at=datetime.now(UTC),
        pass_count=8,
        fail_count=2,
        skipped_count=0,
        example_failures=(
            RuleFailureExample(row=RowReference(row_number=3), reason="value is missing"),
        ),
        duration_ms=1.5,
    )
    assert result.error is None
    assert len(result.example_failures) == 1


def test_rule_execution_result_rejects_more_examples_than_failures() -> None:
    with pytest.raises(ValueError, match="must not exceed fail_count"):
        RuleExecutionResult(
            rule_id="rule-1",
            analysis_id="an-1",
            executed_at=datetime.now(UTC),
            pass_count=1,
            fail_count=0,
            skipped_count=0,
            example_failures=(
                RuleFailureExample(row=RowReference(row_number=0), reason="value is missing"),
            ),
            duration_ms=0.1,
        )


def test_rule_execution_result_bounds_example_failures() -> None:
    too_many = tuple(
        RuleFailureExample(row=RowReference(row_number=i), reason="value is missing")
        for i in range(MAX_EXAMPLE_FAILURES + 1)
    )
    with pytest.raises(ValueError, match=f"must not exceed {MAX_EXAMPLE_FAILURES}"):
        RuleExecutionResult(
            rule_id="rule-1",
            analysis_id="an-1",
            executed_at=datetime.now(UTC),
            pass_count=0,
            fail_count=MAX_EXAMPLE_FAILURES + 1,
            skipped_count=0,
            example_failures=too_many,
            duration_ms=0.1,
        )


@pytest.mark.parametrize("field", ["pass_count", "fail_count", "skipped_count"])
def test_rule_execution_result_rejects_negative_counts(field: str) -> None:
    fields: dict[str, object] = {
        "rule_id": "rule-1",
        "analysis_id": "an-1",
        "executed_at": datetime.now(UTC),
        "pass_count": 0,
        "fail_count": 0,
        "skipped_count": 0,
        "example_failures": (),
        "duration_ms": 0.1,
    }
    fields[field] = -1
    with pytest.raises(ValueError, match=field):
        RuleExecutionResult(**fields)  # type: ignore[arg-type]
