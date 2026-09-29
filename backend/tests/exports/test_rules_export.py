"""Unit proof for the validated-rules export document and renderers
(`EXP-01` slice 1)."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, date, datetime

import yaml

from trusttable_backend.domain.explanation import ValidationRuleType
from trusttable_backend.domain.rules import (
    ComparisonOperator,
    RuleExecutionResult,
    RuleFailureExample,
    ValidationRule,
)
from trusttable_backend.domain.value_objects import ColumnReference, RowReference, Severity
from trusttable_backend.exports.rules_export import (
    EXPORT_SCHEMA_VERSION,
    build_rules_export,
    is_validated,
    render_json,
    render_yaml,
)

_COLUMN = ColumnReference(original_name="Quantity", internal_key="quantity", ordinal=0)


def _result(*, error: str | None = None, fail: int = 2) -> RuleExecutionResult:
    return RuleExecutionResult(
        rule_id="r",
        analysis_id="a",
        executed_at=datetime(2026, 1, 1, tzinfo=UTC),
        pass_count=8,
        fail_count=fail,
        skipped_count=1,
        example_failures=(
            RuleFailureExample(row=RowReference(row_number=3), reason="SECRET-ROW-VALUE"),
        )
        if fail
        else (),
        duration_ms=1.5,
        error=error,
    )


def _rule(rule_id: str = "r1", **overrides: object) -> ValidationRule:
    base = ValidationRule(
        rule_id=rule_id,
        schema_version="1",
        name="quantity range",
        description="non-negative",
        severity=Severity.MEDIUM,
        rule_type=ValidationRuleType.NUMERIC_RANGE,
        columns=(_COLUMN,),
        minimum=0.0,
        last_result=_result(),
    )
    return replace(base, **overrides)  # type: ignore[arg-type]


def test_a_validated_rule_is_exported_with_parameters_and_counts() -> None:
    document = build_rules_export("a1", (_rule(),))

    assert document["export_schema_version"] == EXPORT_SCHEMA_VERSION
    assert document["analysis_id"] == "a1"
    assert document["rule_count"] == 1
    assert document["excluded_rule_count"] == 0
    entry = document["rules"][0]
    assert entry["parameters"] == {"minimum": 0.0}
    assert entry["columns"] == [{"name": "Quantity", "key": "quantity"}]
    assert entry["validation"] == {"pass_count": 8, "fail_count": 2, "skipped_count": 1}


def test_unvalidated_rules_are_excluded_and_counted() -> None:
    rules = (
        _rule("ok"),
        _rule("unrun", last_result=None),
        _rule("errored", last_result=_result(error="boom")),
        _rule("disabled", enabled=False),
    )

    document = build_rules_export("a1", rules)

    assert [entry["rule_id"] for entry in document["rules"]] == ["ok"]
    assert document["rule_count"] == 1
    assert document["excluded_rule_count"] == 3
    assert [is_validated(rule) for rule in rules] == [True, False, False, False]


def test_no_row_derived_detail_is_exported() -> None:
    document = build_rules_export("a1", (_rule(),))
    text = render_json(document) + render_yaml(document)

    assert "SECRET-ROW-VALUE" not in text
    assert "example" not in text
    assert "row_number" not in text
    assert "executed_at" not in text
    assert set(document["rules"][0]["validation"]) == {"pass_count", "fail_count", "skipped_count"}


def test_json_and_yaml_carry_the_same_document() -> None:
    rule = _rule(
        "cmp",
        rule_type=ValidationRuleType.EXPRESSION_COMPARISON,
        columns=(_COLUMN,),
        minimum=None,
        comparison_operator=ComparisonOperator.LESS_THAN,
        comparison_value=5.0,
    )
    dated = _rule(
        "dated",
        rule_type=ValidationRuleType.DATE_RANGE,
        minimum=None,
        minimum_date=date(2020, 1, 1),
        description="tricky: yes, 'quoted' # not a comment\nsecond line ünï",
    )
    document = build_rules_export("a1", (rule, dated))

    assert yaml.safe_load(render_yaml(document)) == json.loads(render_json(document))
    assert json.loads(render_json(document)) == document


def test_rendering_is_deterministic() -> None:
    document = build_rules_export("a1", (_rule("x"), _rule("y")))

    assert render_json(document) == render_json(build_rules_export("a1", (_rule("x"), _rule("y"))))
    assert render_yaml(document) == render_yaml(build_rules_export("a1", (_rule("x"), _rule("y"))))
    assert render_json(document).endswith("\n")


def test_an_empty_analysis_exports_an_empty_rule_list() -> None:
    document = build_rules_export("a1", ())

    assert document["rules"] == []
    assert yaml.safe_load(render_yaml(document))["rules"] == []
