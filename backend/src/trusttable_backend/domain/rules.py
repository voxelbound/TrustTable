"""`ValidationRule`/`RuleExecutionResult` (`RULE-01`, `docs/domain-
model.md` §18-19) — a user-defined, persisted, executable data-quality
check over one analysis's real rows.

`RULE-01`'s backlog text ("Supported rule types defined in product
requirements") names 11 types (`docs/product-requirements.md` §13,
`ValidationRuleType`, `domain.explanation`). Slice 1 (`WP-078`)
implemented 9 of them. Slice 2 (`WP-079`, this revision) adds the last
two, `EXPRESSION_COMPARISON` (a numeric comparison between two columns,
or one column against a numeric literal) and `CONDITIONAL_RULE` (a
numeric WHEN clause on one column gating a numeric THEN clause on a
second), completing 11/11. Both reuse the same typed-parameter shape as
every other rule type (`ComparisonOperator` below plus plain `float`
fields) rather than a free-text expression grammar — `docs/domain-
model.md` §18's single "expression or parameters" field, parameters
route, so `__post_init__` can enforce exactly the right shape instead of
trusting an opaque string. No `eval`/`exec` anywhere in this module.

Distinct from `explanation.ProposedValidationRule` (`AI-08`): that type
is a *display-only proposal* inside one finding's four-section analysis,
never executed, never persisted on its own. `ValidationRule` here is a
first-class, persisted `Analysis` child that a person defines directly
and that actually runs against real rows. `rules/generation.py`
(`RULE-02` slice 1, `WP-080`) is what converts a finding into one of
these for 9 of 13 detector categories, deterministically, using only
facts the matching detector already computed.

`scope` is always `SamplingScope.FULL`: no rule-execution sampling
exists yet, matching `Evidence`'s own current always-`FULL` usage.
`source_finding_ids` is populated for a `DETECTOR_GENERATED` rule
(`RULE-02` slice 1) and empty for a `USER_AUTHORED` one.

Framework-independent: no FastAPI/SQLAlchemy/pydantic/ai_boundary/
ai_provider import. Stdlib only besides the domain value objects.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum

from .explanation import ValidationRuleType
from .parsing import SamplingScope
from .value_objects import ColumnReference, RowReference, Severity

#: All 11 `docs/product-requirements.md` §13 rule types are supported as
#: of `RULE-01` slice 2 (`WP-079`).
SUPPORTED_RULE_TYPES: frozenset[ValidationRuleType] = frozenset(
    {
        ValidationRuleType.NOT_NULL,
        ValidationRuleType.UNIQUE,
        ValidationRuleType.ACCEPTED_VALUES,
        ValidationRuleType.NUMERIC_RANGE,
        ValidationRuleType.DATE_RANGE,
        ValidationRuleType.REGEX,
        ValidationRuleType.MAX_MISSING_PERCENTAGE,
        ValidationRuleType.MAX_DUPLICATE_PERCENTAGE,
        ValidationRuleType.APPROXIMATE_EQUALITY,
        ValidationRuleType.EXPRESSION_COMPARISON,
        ValidationRuleType.CONDITIONAL_RULE,
    }
)

#: Rule types whose `columns` must have exactly one entry.
_SINGLE_COLUMN_TYPES: frozenset[ValidationRuleType] = frozenset(
    {
        ValidationRuleType.NOT_NULL,
        ValidationRuleType.ACCEPTED_VALUES,
        ValidationRuleType.NUMERIC_RANGE,
        ValidationRuleType.DATE_RANGE,
        ValidationRuleType.REGEX,
        ValidationRuleType.MAX_MISSING_PERCENTAGE,
    }
)
#: Rule types whose `columns` must have one or more entries (a composite
#: key) — as opposed to `APPROXIMATE_EQUALITY`'s own "2 or more, first is
#: the total" shape, checked separately.
_MULTI_COLUMN_TYPES: frozenset[ValidationRuleType] = frozenset(
    {ValidationRuleType.UNIQUE, ValidationRuleType.MAX_DUPLICATE_PERCENTAGE}
)

MAX_EXAMPLE_FAILURES: int = 10
MAX_REGEX_PATTERN_LENGTH: int = 200


class NullHandling(StrEnum):
    """How a rule treats a missing (`None`/empty) cell in a column its
    check applies to. Does not apply to `NOT_NULL` itself, whose entire
    purpose is checking for exactly this condition."""

    SKIP = "skip"
    FAIL = "fail"


class ComparisonOperator(StrEnum):
    """A closed set of numeric comparison operators for
    `EXPRESSION_COMPARISON`/`CONDITIONAL_RULE` (`RULE-01` slice 2). No
    string/expression parsing anywhere — a rule names one of these
    members directly, the same way every other rule type names a closed
    enum or a plain typed parameter."""

    EQUALS = "equals"
    NOT_EQUALS = "not_equals"
    LESS_THAN = "less_than"
    LESS_THAN_OR_EQUAL = "less_than_or_equal"
    GREATER_THAN = "greater_than"
    GREATER_THAN_OR_EQUAL = "greater_than_or_equal"


class RuleProvenance(StrEnum):
    """How a `ValidationRule` came to exist.

    `DETECTOR_GENERATED` (`RULE-02` slice 1, `WP-080`) is a rule whose
    `rule_type`/`columns`/parameters were derived deterministically from
    one finding's own already-computed `Evidence` (`rules/generation.py`)
    — never a fresh calculation, never AI — then validated and executed
    before ever being offered, and accepted by a person through the same
    `POST .../rules` path `USER_AUTHORED` rules use, now finding-aware.
    `AI_ASSISTED` (`RULE-02` slice 2, `WP-081`) is additive, not a
    rename: a rule whose single remaining parameter — which of a
    finding's own already-observed evidence values is canonical — was
    chosen by a real AI provider from a closed, per-request enumerated
    set built entirely from that finding's own `Evidence`
    (`rules/ai_generation.py`), never invented and never free text, then
    validated and executed exactly like a `DETECTOR_GENERATED` proposal
    before ever being offered."""

    USER_AUTHORED = "user_authored"
    DETECTOR_GENERATED = "detector_generated"
    AI_ASSISTED = "ai_assisted"


@dataclass(frozen=True, slots=True)
class RuleFailureExample:
    """One bounded example of a row that failed a rule (`docs/domain-
    model.md` §19 "bounded example failures"). `reason` is a short,
    human-readable, non-sensitive description — never the raw failing
    value verbatim beyond what the rule's own parameters already
    disclose (e.g. "value is null", "value outside 0-100")."""

    row: RowReference
    reason: str

    def __post_init__(self) -> None:
        if not self.reason:
            raise ValueError("RuleFailureExample.reason must not be empty")


@dataclass(frozen=True, slots=True)
class RuleExecutionResult:
    """One execution's outcome (`docs/domain-model.md` §19), always the
    *latest* result for its rule — this slice keeps no history."""

    rule_id: str
    analysis_id: str
    executed_at: datetime
    pass_count: int
    fail_count: int
    skipped_count: int
    example_failures: tuple[RuleFailureExample, ...]
    duration_ms: float
    error: str | None = None

    def __post_init__(self) -> None:
        if not self.rule_id:
            raise ValueError("RuleExecutionResult.rule_id must not be empty")
        if not self.analysis_id:
            raise ValueError("RuleExecutionResult.analysis_id must not be empty")
        for name, value in (
            ("pass_count", self.pass_count),
            ("fail_count", self.fail_count),
            ("skipped_count", self.skipped_count),
        ):
            if value < 0:
                raise ValueError(f"RuleExecutionResult.{name} must not be negative")
        if len(self.example_failures) > MAX_EXAMPLE_FAILURES:
            raise ValueError(
                f"RuleExecutionResult.example_failures must not exceed {MAX_EXAMPLE_FAILURES}"
            )
        if len(self.example_failures) > self.fail_count:
            raise ValueError("RuleExecutionResult.example_failures must not exceed fail_count")
        if self.duration_ms < 0:
            raise ValueError("RuleExecutionResult.duration_ms must not be negative")


@dataclass(frozen=True, slots=True)
class ValidationRule:
    """A user-defined, persisted, executable data-quality check
    (`docs/domain-model.md` §18) over one `Analysis`'s real rows.

    `columns`/the type-specific parameter fields below realize §18's
    single "expression or parameters" field, split into a typed
    structure per rule type so `__post_init__` can enforce exactly the
    right shape instead of trusting an opaque expression string:

    | rule_type | columns | extra parameters |
    |---|---|---|
    | not_null | 1 | none |
    | unique | 1+ (composite key) | none |
    | accepted_values | 1 | `accepted_values` (non-empty) |
    | numeric_range | 1 | `minimum`/`maximum` (>=1 set) |
    | date_range | 1 | `minimum_date`/`maximum_date` (>=1 set) |
    | regex | 1 | `pattern` (non-empty, bounded, valid) |
    | max_missing_percentage | 1 | `threshold_percentage` (0-100) |
    | max_duplicate_percentage | 1+ | `threshold_percentage` (0-100) |
    | approximate_equality | 2+ (`columns[0]`=total, rest=parts) | `tolerance` (>=0) |
    | expression_comparison | 1 (literal) or 2 (col) | operator always; value iff 1 col |
    | conditional_rule | 2 (`[0]`=WHEN, `[1]`=THEN) | condition_op/val=WHEN, comparison_op/val=THEN|

    Every parameter field not named for a given `rule_type` must be
    `None` — proven by `__post_init__`, not merely documented.
    """

    rule_id: str
    schema_version: str
    name: str
    description: str
    severity: Severity
    rule_type: ValidationRuleType
    columns: tuple[ColumnReference, ...]
    null_handling: NullHandling = NullHandling.SKIP
    enabled: bool = True
    scope: SamplingScope = SamplingScope.FULL
    accepted_values: tuple[str, ...] | None = None
    minimum: float | None = None
    maximum: float | None = None
    minimum_date: date | None = None
    maximum_date: date | None = None
    pattern: str | None = None
    threshold_percentage: float | None = None
    tolerance: float | None = None
    comparison_operator: ComparisonOperator | None = None
    comparison_value: float | None = None
    condition_operator: ComparisonOperator | None = None
    condition_value: float | None = None
    source_finding_ids: tuple[str, ...] = ()
    provenance: RuleProvenance = RuleProvenance.USER_AUTHORED
    last_result: RuleExecutionResult | None = None

    def __post_init__(self) -> None:
        if not self.rule_id:
            raise ValueError("ValidationRule.rule_id must not be empty")
        if not self.schema_version:
            raise ValueError("ValidationRule.schema_version must not be empty")
        if not self.name:
            raise ValueError("ValidationRule.name must not be empty")
        if not self.description:
            raise ValueError("ValidationRule.description must not be empty")
        if self.rule_type not in SUPPORTED_RULE_TYPES:
            raise ValueError(
                f"ValidationRule.rule_type {self.rule_type.value!r} is not a supported rule type"
            )
        if self.scope is not SamplingScope.FULL:
            raise ValueError("ValidationRule.scope must be FULL (no rule-execution sampling yet)")

        self._check_columns()
        self._check_parameters()

    def _check_columns(self) -> None:
        rule_type = self.rule_type
        count = len(self.columns)
        if rule_type in _SINGLE_COLUMN_TYPES and count != 1:
            raise ValueError(f"ValidationRule.columns must have exactly 1 entry for {rule_type}")
        if rule_type in _MULTI_COLUMN_TYPES and count < 1:
            raise ValueError(f"ValidationRule.columns must have at least 1 entry for {rule_type}")
        if rule_type is ValidationRuleType.APPROXIMATE_EQUALITY and count < 2:
            raise ValueError(
                "ValidationRule.columns must have at least 2 entries for approximate_equality "
                "(columns[0] is the total, the rest are its components)"
            )
        if rule_type is ValidationRuleType.EXPRESSION_COMPARISON and count not in (1, 2):
            raise ValueError(
                "ValidationRule.columns must have exactly 1 (vs a literal) or 2 (vs another "
                "column) entries for expression_comparison"
            )
        if rule_type is ValidationRuleType.CONDITIONAL_RULE and count != 2:
            raise ValueError(
                "ValidationRule.columns must have exactly 2 entries for conditional_rule "
                "(columns[0] is the WHEN column, columns[1] is the THEN column)"
            )

    def _check_parameters(self) -> None:
        rule_type = self.rule_type
        by_type: dict[ValidationRuleType, tuple[str, ...]] = {
            ValidationRuleType.ACCEPTED_VALUES: ("accepted_values",),
            ValidationRuleType.NUMERIC_RANGE: ("minimum", "maximum"),
            ValidationRuleType.DATE_RANGE: ("minimum_date", "maximum_date"),
            ValidationRuleType.REGEX: ("pattern",),
            ValidationRuleType.MAX_MISSING_PERCENTAGE: ("threshold_percentage",),
            ValidationRuleType.MAX_DUPLICATE_PERCENTAGE: ("threshold_percentage",),
            ValidationRuleType.APPROXIMATE_EQUALITY: ("tolerance",),
            ValidationRuleType.EXPRESSION_COMPARISON: ("comparison_operator", "comparison_value"),
            ValidationRuleType.CONDITIONAL_RULE: (
                "condition_operator",
                "condition_value",
                "comparison_operator",
                "comparison_value",
            ),
        }
        owned = by_type.get(rule_type, ())
        all_parameter_fields = (
            "accepted_values",
            "minimum",
            "maximum",
            "minimum_date",
            "maximum_date",
            "pattern",
            "threshold_percentage",
            "tolerance",
            "comparison_operator",
            "comparison_value",
            "condition_operator",
            "condition_value",
        )
        for field_name in all_parameter_fields:
            value = getattr(self, field_name)
            if field_name not in owned and value is not None:
                raise ValueError(
                    f"ValidationRule.{field_name} must be None for rule_type {rule_type}"
                )

        if rule_type is ValidationRuleType.ACCEPTED_VALUES and not self.accepted_values:
            raise ValueError("ValidationRule.accepted_values must be non-empty")
        if rule_type is ValidationRuleType.NUMERIC_RANGE:
            if self.minimum is None and self.maximum is None:
                raise ValueError("ValidationRule: numeric_range requires minimum and/or maximum")
            if (
                self.minimum is not None
                and self.maximum is not None
                and self.minimum > self.maximum
            ):
                raise ValueError("ValidationRule.minimum must not exceed maximum")
        if rule_type is ValidationRuleType.DATE_RANGE:
            if self.minimum_date is None and self.maximum_date is None:
                raise ValueError(
                    "ValidationRule: date_range requires minimum_date and/or maximum_date"
                )
            if (
                self.minimum_date is not None
                and self.maximum_date is not None
                and self.minimum_date > self.maximum_date
            ):
                raise ValueError("ValidationRule.minimum_date must not exceed maximum_date")
        if rule_type is ValidationRuleType.REGEX:
            if not self.pattern:
                raise ValueError("ValidationRule.pattern must not be empty")
            if len(self.pattern) > MAX_REGEX_PATTERN_LENGTH:
                raise ValueError(
                    f"ValidationRule.pattern must not exceed {MAX_REGEX_PATTERN_LENGTH} characters"
                )
        if rule_type in (
            ValidationRuleType.MAX_MISSING_PERCENTAGE,
            ValidationRuleType.MAX_DUPLICATE_PERCENTAGE,
        ):
            threshold = self.threshold_percentage
            if threshold is None or not 0.0 <= threshold <= 100.0:
                raise ValueError("ValidationRule.threshold_percentage must be set and within 0-100")
        if rule_type is ValidationRuleType.APPROXIMATE_EQUALITY and (
            self.tolerance is None or self.tolerance < 0.0
        ):
            raise ValueError("ValidationRule.tolerance must be set and non-negative")
        if rule_type is ValidationRuleType.EXPRESSION_COMPARISON:
            if self.comparison_operator is None:
                raise ValueError(
                    "ValidationRule: expression_comparison requires comparison_operator"
                )
            if len(self.columns) == 1 and self.comparison_value is None:
                raise ValueError(
                    "ValidationRule: expression_comparison against a literal (1 column) "
                    "requires comparison_value"
                )
            if len(self.columns) == 2 and self.comparison_value is not None:
                raise ValueError(
                    "ValidationRule.comparison_value must be None for expression_comparison "
                    "against another column (2 columns)"
                )
        if rule_type is ValidationRuleType.CONDITIONAL_RULE:
            if self.condition_operator is None or self.condition_value is None:
                raise ValueError(
                    "ValidationRule: conditional_rule requires condition_operator and "
                    "condition_value (the WHEN clause)"
                )
            if self.comparison_operator is None or self.comparison_value is None:
                raise ValueError(
                    "ValidationRule: conditional_rule requires comparison_operator and "
                    "comparison_value (the THEN clause)"
                )


__all__ = [
    "MAX_EXAMPLE_FAILURES",
    "MAX_REGEX_PATTERN_LENGTH",
    "SUPPORTED_RULE_TYPES",
    "ComparisonOperator",
    "NullHandling",
    "RuleExecutionResult",
    "RuleFailureExample",
    "RuleProvenance",
    "ValidationRule",
]
