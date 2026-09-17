"""Guided-question and answer contracts (`CTX-03`/`API-02`), matching
`docs/domain-model.md` §10 (`ClarificationQuestion`) and §11
(`ClarificationAnswer`, added by `API-02`, `WP-059`).

`context_field` on `ClarificationQuestion` is a new, disclosed field
(not literally named by §10's field list): traceability back to which
`context_inference.DatasetContext` field this question targets, needed
by `API-02`'s answer-processing logic to know which field an answer
should update. Same disclosed-addition pattern already established by
`domain.context.ContextHypothesis.related_columns`.

Framework-independent: no FastAPI/SQLAlchemy/pydantic import. Stdlib
only (`dataclasses`, `datetime`, `enum`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from .context import ContextField
from .value_objects import Provenance

_VALID_ANSWER_PROVENANCE = frozenset({Provenance.USER_CONFIRMED, Provenance.USER_CORRECTED})


class QuestionAnsweredState(StrEnum):
    """Closed set of `ClarificationQuestion` "answered state" values
    (`docs/domain-model.md` §10). Every question this package generates
    starts `UNANSWERED`; transitions to `ANSWERED`/`SKIPPED` are a
    future consumer's responsibility (`API-02`), not this package's."""

    UNANSWERED = "unanswered"
    ANSWERED = "answered"
    SKIPPED = "skipped"


@dataclass(frozen=True, slots=True)
class ClarificationQuestion:
    """Requests business information that can materially affect
    validity or prioritization (`docs/domain-model.md` §10).

    Fields:
        question_id: stable, unique identifier for this question.
        context_field: which `DatasetContext` field this question
            targets (a disclosed addition, see module docstring).
        concise_text: the question itself, in plain business language
            ("questions avoid unnecessary technical terminology").
        explanation: why the answer matters ("every question identifies
            why the answer matters").
        suggested_answers: zero or more short suggested answers a user
            may pick instead of typing free text.
        inferred_default: an existing best-guess value, if any, offered
            as a pre-filled default — `None` when no guess exists.
        affected_assumptions: at least one plain-language description of
            what this answer would affect (paired with `explanation` to
            satisfy the "why the answer matters" invariant concretely).
        free_text_allowed: whether a free-text answer is accepted in
            addition to (or instead of) `suggested_answers`.
        answered_state: this question's current lifecycle state.
    """

    question_id: str
    context_field: ContextField
    concise_text: str
    explanation: str
    suggested_answers: tuple[str, ...]
    inferred_default: str | None
    affected_assumptions: tuple[str, ...]
    free_text_allowed: bool
    answered_state: QuestionAnsweredState = QuestionAnsweredState.UNANSWERED

    def __post_init__(self) -> None:
        if not self.question_id:
            raise ValueError("ClarificationQuestion.question_id must not be empty")
        if not self.concise_text:
            raise ValueError("ClarificationQuestion.concise_text must not be empty")
        if not self.explanation:
            raise ValueError("ClarificationQuestion.explanation must not be empty")
        if not self.affected_assumptions:
            raise ValueError("ClarificationQuestion.affected_assumptions must not be empty")


@dataclass(frozen=True, slots=True)
class ClarificationAnswer:
    """Records one answer to a `ClarificationQuestion`
    (`docs/domain-model.md` §11).

    `provenance` is restricted to `Provenance.USER_CONFIRMED`/
    `USER_CORRECTED` — the two-value closed set §11 itself names. An
    answer matching the question's own inferred default/suggested
    answer is `USER_CONFIRMED`; a genuinely different value (including
    free text where no default existed) is `USER_CORRECTED`
    (`API-02`'s own disclosed interpretation of "the user provided a
    corrected/concrete value where none existed").
    """

    question_id: str
    selected_answer_or_free_text: str
    answered_timestamp: datetime
    resulting_context_changes: tuple[ContextField, ...]
    provenance: Provenance

    def __post_init__(self) -> None:
        if not self.question_id:
            raise ValueError("ClarificationAnswer.question_id must not be empty")
        if not self.selected_answer_or_free_text:
            raise ValueError("ClarificationAnswer.selected_answer_or_free_text must not be empty")
        if not self.resulting_context_changes:
            raise ValueError("ClarificationAnswer.resulting_context_changes must not be empty")
        if self.provenance not in _VALID_ANSWER_PROVENANCE:
            raise ValueError(
                "ClarificationAnswer.provenance must be USER_CONFIRMED or USER_CORRECTED"
            )
