"""Validated-rules export (`EXP-01` slice 1): one framework-independent
document builder plus a JSON and a YAML renderer over the same document.

Only *validated* rules are exported: enabled, and with a latest execution
result that carries no error. Rules that are disabled, never executed, or
whose last execution errored are excluded and only *counted* in the header,
so a consumer can see that something was withheld.

No dataset row content is exported. A rule's own declared parameters
(for example `accepted_values`, `pattern`, bounds) are the rule definition
and are exported; `example_failures` and every per-row detail are not.
Aggregate pass/fail/skipped counts are included as validation evidence.

The output has no timestamp and a fixed key order, so it is byte-identical
across repeated calls for the same analysis.
"""

from __future__ import annotations

import json
from typing import Any

import yaml

from trusttable_backend.domain.rules import ValidationRule

EXPORT_TYPE = "validation_rules"
EXPORT_SCHEMA_VERSION = "1"


def is_validated(rule: ValidationRule) -> bool:
    """True iff the rule is enabled and its latest execution succeeded."""
    return rule.enabled and rule.last_result is not None and rule.last_result.error is None


def _parameters(rule: ValidationRule) -> dict[str, Any]:
    candidates: dict[str, Any] = {
        "accepted_values": list(rule.accepted_values) if rule.accepted_values is not None else None,
        "minimum": rule.minimum,
        "maximum": rule.maximum,
        "minimum_date": rule.minimum_date.isoformat() if rule.minimum_date is not None else None,
        "maximum_date": rule.maximum_date.isoformat() if rule.maximum_date is not None else None,
        "pattern": rule.pattern,
        "threshold_percentage": rule.threshold_percentage,
        "tolerance": rule.tolerance,
        "comparison_operator": rule.comparison_operator.value
        if rule.comparison_operator is not None
        else None,
        "comparison_value": rule.comparison_value,
        "condition_operator": rule.condition_operator.value
        if rule.condition_operator is not None
        else None,
        "condition_value": rule.condition_value,
    }
    return {key: value for key, value in candidates.items() if value is not None}


def _rule_entry(rule: ValidationRule) -> dict[str, Any]:
    result = rule.last_result
    assert result is not None  # guaranteed by is_validated
    return {
        "rule_id": rule.rule_id,
        "name": rule.name,
        "description": rule.description,
        "severity": rule.severity.value,
        "rule_type": rule.rule_type.value,
        "columns": [
            {"name": column.original_name, "key": column.internal_key} for column in rule.columns
        ],
        "null_handling": rule.null_handling.value,
        "parameters": _parameters(rule),
        "provenance": rule.provenance.value,
        "source_finding_ids": list(rule.source_finding_ids),
        "validation": {
            "pass_count": result.pass_count,
            "fail_count": result.fail_count,
            "skipped_count": result.skipped_count,
        },
    }


def build_rules_export(analysis_id: str, rules: tuple[ValidationRule, ...]) -> dict[str, Any]:
    """Build the export document from an analysis's stored rules."""
    exported = [_rule_entry(rule) for rule in rules if is_validated(rule)]
    return {
        "export_type": EXPORT_TYPE,
        "export_schema_version": EXPORT_SCHEMA_VERSION,
        "analysis_id": analysis_id,
        "rule_count": len(exported),
        "excluded_rule_count": len(rules) - len(exported),
        "rules": exported,
    }


def render_json(document: dict[str, Any]) -> str:
    return json.dumps(document, indent=2, ensure_ascii=False, sort_keys=False) + "\n"


def render_yaml(document: dict[str, Any]) -> str:
    return yaml.safe_dump(
        document, sort_keys=False, allow_unicode=True, default_flow_style=False, width=1_000_000
    )
