"""The `ValidationRule` execution engine (`RULE-01` slice 1).

`execute_rule` is pure and framework-independent: given a `ValidationRule`
and the real parsed rows it applies to, it scans every row exactly once
(never a sample) and returns a `RuleExecutionResult`. No `eval`/`exec`,
no `ai_boundary`/`ai_provider` import, no I/O.

Two rule types (`MAX_MISSING_PERCENTAGE`, `MAX_DUPLICATE_PERCENTAGE`)
report the *raw incident count* per row (a cell is missing; a row's key
duplicates another's) rather than a single dataset-wide pass/fail
boolean — `docs/domain-model.md` §19's `RuleExecutionResult` field list
has no separate "did the rule pass overall" field, so the percentage a
caller compares against `ValidationRule.threshold_percentage` is
`fail_count / (pass_count + fail_count)`, derived by the caller/UI, the
same way `UNIQUE` reports duplicate rows without a separate
"uniqueness satisfied" flag (a `UNIQUE` rule is exactly a
`MAX_DUPLICATE_PERCENTAGE` rule with an implied 0% threshold).

`REGEX` follows this codebase's own existing convention for the type
(`explanation/guidance.py`'s rule descriptions, e.g. "should not start
or end with whitespace", "should not contain instruction-like
phrases"): the pattern names the *disallowed* condition, so a match is
a failure and no match is a pass.

A non-null cell that cannot be parsed as the type the rule requires
(e.g. `"abc"` for `numeric_range`) is a failure, not a skip — only an
actually missing (`None`/empty-string) cell follows `null_handling`.
"""

from __future__ import annotations

import re
import time
from collections import defaultdict
from datetime import date, datetime

from ..domain.explanation import ValidationRuleType
from ..domain.rules import (
    MAX_EXAMPLE_FAILURES,
    NullHandling,
    RuleExecutionResult,
    RuleFailureExample,
    ValidationRule,
)
from ..domain.value_objects import RowReference


class _Tally:
    """Accumulates one execution's counts and bounded examples."""

    def __init__(self) -> None:
        self.pass_count = 0
        self.fail_count = 0
        self.skipped_count = 0
        self.examples: list[RuleFailureExample] = []

    def record_pass(self) -> None:
        self.pass_count += 1

    def record_skip(self) -> None:
        self.skipped_count += 1

    def record_fail(self, row_number: int, reason: str) -> None:
        self.fail_count += 1
        if len(self.examples) < MAX_EXAMPLE_FAILURES:
            self.examples.append(
                RuleFailureExample(row=RowReference(row_number=row_number), reason=reason)
            )


def _is_missing(value: str | None) -> bool:
    return value is None or value == ""


def _handle_missing(tally: _Tally, row_number: int, null_handling: NullHandling) -> None:
    if null_handling is NullHandling.SKIP:
        tally.record_skip()
    else:
        tally.record_fail(row_number, "value is missing")


def _run_not_null(rule: ValidationRule, rows: tuple[tuple[str | None, ...], ...]) -> _Tally:
    tally = _Tally()
    ordinal = rule.columns[0].ordinal
    for row_number, row in enumerate(rows):
        if _is_missing(row[ordinal]):
            tally.record_fail(row_number, "value is missing")
        else:
            tally.record_pass()
    return tally


def _run_accepted_values(rule: ValidationRule, rows: tuple[tuple[str | None, ...], ...]) -> _Tally:
    tally = _Tally()
    ordinal = rule.columns[0].ordinal
    assert rule.accepted_values is not None
    allowed = frozenset(rule.accepted_values)
    for row_number, row in enumerate(rows):
        value = row[ordinal]
        if _is_missing(value):
            _handle_missing(tally, row_number, rule.null_handling)
        elif value in allowed:
            tally.record_pass()
        else:
            tally.record_fail(row_number, f"value {value!r} is not an accepted value")
    return tally


def _run_numeric_range(rule: ValidationRule, rows: tuple[tuple[str | None, ...], ...]) -> _Tally:
    tally = _Tally()
    ordinal = rule.columns[0].ordinal
    for row_number, row in enumerate(rows):
        value = row[ordinal]
        if _is_missing(value):
            _handle_missing(tally, row_number, rule.null_handling)
            continue
        assert value is not None
        try:
            numeric = float(value)
        except ValueError:
            tally.record_fail(row_number, "value is not numeric")
            continue
        if rule.minimum is not None and numeric < rule.minimum:
            tally.record_fail(row_number, f"value {numeric} is below the minimum {rule.minimum}")
        elif rule.maximum is not None and numeric > rule.maximum:
            tally.record_fail(row_number, f"value {numeric} is above the maximum {rule.maximum}")
        else:
            tally.record_pass()
    return tally


def _run_date_range(rule: ValidationRule, rows: tuple[tuple[str | None, ...], ...]) -> _Tally:
    tally = _Tally()
    ordinal = rule.columns[0].ordinal
    for row_number, row in enumerate(rows):
        value = row[ordinal]
        if _is_missing(value):
            _handle_missing(tally, row_number, rule.null_handling)
            continue
        assert value is not None
        try:
            parsed = date.fromisoformat(value.strip())
        except ValueError:
            tally.record_fail(row_number, "value is not an ISO-8601 date")
            continue
        if rule.minimum_date is not None and parsed < rule.minimum_date:
            tally.record_fail(
                row_number, f"date {parsed.isoformat()} is before {rule.minimum_date.isoformat()}"
            )
        elif rule.maximum_date is not None and parsed > rule.maximum_date:
            tally.record_fail(
                row_number, f"date {parsed.isoformat()} is after {rule.maximum_date.isoformat()}"
            )
        else:
            tally.record_pass()
    return tally


def _run_regex(rule: ValidationRule, rows: tuple[tuple[str | None, ...], ...]) -> _Tally:
    tally = _Tally()
    ordinal = rule.columns[0].ordinal
    assert rule.pattern is not None
    compiled = re.compile(rule.pattern)
    for row_number, row in enumerate(rows):
        value = row[ordinal]
        if _is_missing(value):
            _handle_missing(tally, row_number, rule.null_handling)
            continue
        assert value is not None
        if compiled.search(value) is not None:
            tally.record_fail(row_number, "value matches the disallowed pattern")
        else:
            tally.record_pass()
    return tally


def _run_max_missing_percentage(
    rule: ValidationRule, rows: tuple[tuple[str | None, ...], ...]
) -> _Tally:
    tally = _Tally()
    ordinal = rule.columns[0].ordinal
    for row_number, row in enumerate(rows):
        if _is_missing(row[ordinal]):
            tally.record_fail(row_number, "value is missing")
        else:
            tally.record_pass()
    return tally


def _duplicate_group_tally(
    rule: ValidationRule, rows: tuple[tuple[str | None, ...], ...]
) -> _Tally:
    """Shared mechanic for `UNIQUE` and `MAX_DUPLICATE_PERCENTAGE`: group
    rows by their composite key, fail every row in a group of size > 1."""
    tally = _Tally()
    ordinals = [column.ordinal for column in rule.columns]
    groups: dict[tuple[str | None, ...], list[int]] = defaultdict(list)
    missing_rows: list[int] = []
    for row_number, row in enumerate(rows):
        key = tuple(row[ordinal] for ordinal in ordinals)
        if any(_is_missing(component) for component in key):
            missing_rows.append(row_number)
            continue
        groups[key].append(row_number)

    for row_number in missing_rows:
        _handle_missing(tally, row_number, rule.null_handling)

    for group_rows in groups.values():
        if len(group_rows) > 1:
            for row_number in group_rows:
                tally.record_fail(
                    row_number, f"duplicate key shared with {len(group_rows) - 1} other row(s)"
                )
        else:
            tally.record_pass()
    return tally


def _run_approximate_equality(
    rule: ValidationRule, rows: tuple[tuple[str | None, ...], ...]
) -> _Tally:
    tally = _Tally()
    total_ordinal = rule.columns[0].ordinal
    component_ordinals = [column.ordinal for column in rule.columns[1:]]
    assert rule.tolerance is not None
    for row_number, row in enumerate(rows):
        raw_values = [row[total_ordinal], *(row[ordinal] for ordinal in component_ordinals)]
        if any(_is_missing(value) for value in raw_values):
            _handle_missing(tally, row_number, rule.null_handling)
            continue
        try:
            total = float(raw_values[0])  # type: ignore[arg-type]
            components = [float(value) for value in raw_values[1:]]  # type: ignore[arg-type]
        except ValueError:
            tally.record_fail(row_number, "value is not numeric")
            continue
        difference = abs(total - sum(components))
        if difference <= rule.tolerance:
            tally.record_pass()
        else:
            tally.record_fail(row_number, f"total differs from components by {difference}")
    return tally


_RUNNERS = {
    ValidationRuleType.NOT_NULL: _run_not_null,
    ValidationRuleType.ACCEPTED_VALUES: _run_accepted_values,
    ValidationRuleType.NUMERIC_RANGE: _run_numeric_range,
    ValidationRuleType.DATE_RANGE: _run_date_range,
    ValidationRuleType.REGEX: _run_regex,
    ValidationRuleType.MAX_MISSING_PERCENTAGE: _run_max_missing_percentage,
}


def execute_rule(
    rule: ValidationRule,
    rows: tuple[tuple[str | None, ...], ...],
    *,
    analysis_id: str,
    now: datetime,
) -> RuleExecutionResult:
    """Execute `rule` against `rows` (every row, never a sample) and
    return its `RuleExecutionResult`. Column ordinals are read directly
    from `rule.columns`, which the caller must already have resolved
    against the analysis's real dataset columns."""
    start = time.perf_counter()
    error: str | None = None
    try:
        if rule.rule_type in (
            ValidationRuleType.UNIQUE,
            ValidationRuleType.MAX_DUPLICATE_PERCENTAGE,
        ):
            tally = _duplicate_group_tally(rule, rows)
        elif rule.rule_type is ValidationRuleType.APPROXIMATE_EQUALITY:
            tally = _run_approximate_equality(rule, rows)
        else:
            runner = _RUNNERS[rule.rule_type]
            tally = runner(rule, rows)
    except Exception as exc:  # pragma: no cover - defensive safety net
        tally = _Tally()
        error = f"{type(exc).__name__}: {exc}"

    duration_ms = (time.perf_counter() - start) * 1000
    return RuleExecutionResult(
        rule_id=rule.rule_id,
        analysis_id=analysis_id,
        executed_at=now,
        pass_count=tally.pass_count,
        fail_count=tally.fail_count,
        skipped_count=tally.skipped_count,
        example_failures=tuple(tally.examples),
        duration_ms=duration_ms,
        error=error,
    )


__all__ = ["execute_rule"]
