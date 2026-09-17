"""Deterministic guided-question generation (`CTX-03`).

Generates zero or more `domain.clarification.ClarificationQuestion`
objects from an already-consolidated `domain.context.DatasetContext`
(`CTX-01`/`CTX-02`'s output) — one fixed-template question per eligible
`ContextField` still in `ConfirmationState.UNKNOWN`.

Only the five **single-value** `ContextField`s are eligible
(`PROBABLE_DOMAIN`, `ROW_GRAIN`, `PRIMARY_ENTITY`, `CURRENCY_BEHAVIOR`,
`EXPECTED_BUSINESS_RULES`) — the four **role** fields
(`CANDIDATE_KEYS`, `BUSINESS_DATES`, `MEASURE_ROLES`, `DIMENSIONS`) are
list-shaped and do not fit a single yes/no/short-text clarification
question the same way, a deliberate, disclosed scoping choice. Because
exactly five fields are eligible, `generate_guided_questions` can never
return more than `MAX_GUIDED_QUESTIONS` (`5`) questions — a structural
guarantee, not a separately-enforced runtime limit — matching
`docs/product-requirements.md` §8.4's and `docs/domain-model.md` §10's
own "no more than five" invariant exactly.

A question is generated only when the corresponding field's
`confirmation_state is ConfirmationState.UNKNOWN`; `INFERRED`,
`CONFIRMED`, and `CORRECTED` are all skipped ("confirmed facts are not
asked again", `docs/domain-model.md` §10).

Deliberately deterministic, not AI-generated — see this package's own
work-package definition for the full design-disclosure rationale (the
generic AI-output schema `CTX-02` already found insufficient for
structured per-field output has no list-of-questions shape at all).
No `ai_boundary`/`ai_provider` import anywhere in this module, matching
`heuristics.py`'s own "AI cannot alter" structural guarantee.

Framework-independent: no FastAPI/SQLAlchemy/pydantic/ai_boundary/
ai_provider import. Stdlib only.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Final

from ..domain.clarification import ClarificationQuestion
from ..domain.context import ConfirmationState, ContextField, DatasetContext

MAX_GUIDED_QUESTIONS: Final[int] = 5
"""Matches `docs/product-requirements.md` §8.4's and `docs/domain-
model.md` §10's "no more than five" guided-questions invariant. Never
exceeded by construction: exactly this many `ContextField`s are
eligible for a question at all (`_ELIGIBLE_FIELDS_IN_ORDER`)."""


def _probable_domain_question() -> ClarificationQuestion:
    return ClarificationQuestion(
        question_id="cq-probable_domain-1",
        context_field=ContextField.PROBABLE_DOMAIN,
        concise_text="What kind of dataset is this?",
        explanation=(
            "Knowing the general business domain (for example sales orders, "
            "inventory, or HR records) helps focus which quality checks and "
            "explanations are most relevant."
        ),
        suggested_answers=(
            "Sales / order transactions",
            "Inventory / stock records",
            "Customer / CRM records",
            "Financial / accounting records",
            "Other",
        ),
        inferred_default=None,
        affected_assumptions=(
            "which quality checks are prioritized",
            "how findings are explained",
        ),
        free_text_allowed=True,
    )


def _row_grain_question() -> ClarificationQuestion:
    return ClarificationQuestion(
        question_id="cq-row_grain-1",
        context_field=ContextField.ROW_GRAIN,
        concise_text="What does one row in this dataset represent?",
        explanation=(
            "Knowing the row grain (for example one row per order, or one "
            "row per customer) affects how duplicate-row and completeness "
            "findings are interpreted."
        ),
        suggested_answers=(),
        inferred_default=None,
        affected_assumptions=(
            "duplicate-row interpretation",
            "completeness scoring",
        ),
        free_text_allowed=True,
    )


def _primary_entity_question() -> ClarificationQuestion:
    return ClarificationQuestion(
        question_id="cq-primary_entity-1",
        context_field=ContextField.PRIMARY_ENTITY,
        concise_text="What is the main business entity this dataset tracks?",
        explanation=(
            "Identifying the primary entity (for example order, customer, or "
            "product) helps describe findings in familiar business terms."
        ),
        suggested_answers=(),
        inferred_default=None,
        affected_assumptions=(
            "finding descriptions",
            "report summaries",
        ),
        free_text_allowed=True,
    )


def _currency_behavior_question() -> ClarificationQuestion:
    return ClarificationQuestion(
        question_id="cq-currency_behavior-1",
        context_field=ContextField.CURRENCY_BEHAVIOR,
        concise_text=(
            "What currency are monetary values expressed in, and is it consistent throughout?"
        ),
        explanation=(
            "Currency assumptions affect how monetary findings (for example "
            "outliers or negative values) are interpreted and compared."
        ),
        suggested_answers=(
            "Single currency throughout",
            "Multiple currencies",
            "Not applicable — no monetary values",
        ),
        inferred_default=None,
        affected_assumptions=(
            "monetary-value findings",
            "risk scoring of monetary columns",
        ),
        free_text_allowed=True,
    )


def _expected_business_rules_question() -> ClarificationQuestion:
    return ClarificationQuestion(
        question_id="cq-expected_business_rules-1",
        context_field=ContextField.EXPECTED_BUSINESS_RULES,
        concise_text="Are there specific business rules this dataset should satisfy?",
        explanation=(
            "Known business rules (for example a total should equal quantity "
            "times price) let the analysis check for violations that generic "
            "detectors cannot find on their own."
        ),
        suggested_answers=(),
        inferred_default=None,
        affected_assumptions=(
            "rule-based validation",
            "cross-field consistency checks",
        ),
        free_text_allowed=True,
    )


_ELIGIBLE_FIELDS_IN_ORDER: Final[tuple[ContextField, ...]] = (
    ContextField.PROBABLE_DOMAIN,
    ContextField.ROW_GRAIN,
    ContextField.PRIMARY_ENTITY,
    ContextField.CURRENCY_BEHAVIOR,
    ContextField.EXPECTED_BUSINESS_RULES,
)

_TEMPLATES: Final[dict[ContextField, Callable[[], ClarificationQuestion]]] = {
    ContextField.PROBABLE_DOMAIN: _probable_domain_question,
    ContextField.ROW_GRAIN: _row_grain_question,
    ContextField.PRIMARY_ENTITY: _primary_entity_question,
    ContextField.CURRENCY_BEHAVIOR: _currency_behavior_question,
    ContextField.EXPECTED_BUSINESS_RULES: _expected_business_rules_question,
}


def generate_guided_questions(dataset_context: DatasetContext) -> tuple[ClarificationQuestion, ...]:
    """Generate guided questions for `dataset_context`, one per eligible
    `ContextField` still `ConfirmationState.UNKNOWN`, in
    `_ELIGIBLE_FIELDS_IN_ORDER`. Never returns more than
    `MAX_GUIDED_QUESTIONS` entries.
    """
    questions: list[ClarificationQuestion] = []
    for field in _ELIGIBLE_FIELDS_IN_ORDER:
        field_value = getattr(dataset_context, field.value)
        if field_value.confirmation_state is ConfirmationState.UNKNOWN:
            questions.append(_TEMPLATES[field]())
    return tuple(questions)


__all__ = ["MAX_GUIDED_QUESTIONS", "generate_guided_questions"]
