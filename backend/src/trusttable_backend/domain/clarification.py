"""Guided-question contracts (`CTX-03`), matching `docs/domain-model.md`
§10 (`ClarificationQuestion`).

`ClarificationAnswer` (§11) is deliberately not defined here —
`docs/implementation-backlog.md#API-02` ("Confirm, correct, answer, and
finalize") is the named backlog item for answer processing, a distinct,
human-input-carrying aggregate this package does not construct, store,
or consume.

`context_field` is a new, disclosed field (not literally named by §10's
field list): traceability back to which `context_inference.
DatasetContext` field this question targets, needed by a future
consumer (`API-02`) to know which field an answer should update. Same
disclosed-addition pattern already established by `domain.context.
ContextHypothesis.related_columns`.

Framework-independent: no FastAPI/SQLAlchemy/pydantic import. Stdlib
only (`dataclasses`, `enum`).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .context import ContextField


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
