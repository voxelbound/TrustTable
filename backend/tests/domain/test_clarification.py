"""Tests for the guided-question and answer contracts (CTX-03/API-02).

Covers `CTX-03`'s AC-01: `QuestionAnsweredState`'s closed enumeration
and `ClarificationQuestion`'s positive, negative, and boundary cases.
Also covers `API-02`'s (`WP-059`) AC-01: `ClarificationAnswer`'s
positive, negative, and boundary cases.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from trusttable_backend.domain.clarification import (
    ClarificationAnswer,
    ClarificationQuestion,
    QuestionAnsweredState,
)
from trusttable_backend.domain.context import ContextField
from trusttable_backend.domain.value_objects import Provenance

FIXED_NOW = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)


def make_question(**overrides: object) -> ClarificationQuestion:
    fields: dict[str, object] = {
        "question_id": "cq-1",
        "context_field": ContextField.PROBABLE_DOMAIN,
        "concise_text": "What kind of dataset is this?",
        "explanation": "Helps focus which checks are relevant.",
        "suggested_answers": ("Sales", "Other"),
        "inferred_default": None,
        "affected_assumptions": ("which checks are prioritized",),
        "free_text_allowed": True,
    }
    fields.update(overrides)
    return ClarificationQuestion(**fields)  # type: ignore[arg-type]


def test_question_answered_state_is_a_closed_enumeration() -> None:
    assert {member.value for member in QuestionAnsweredState} == {
        "unanswered",
        "answered",
        "skipped",
    }


def test_clarification_question_constructs_with_valid_fields() -> None:
    question = make_question()

    assert question.question_id == "cq-1"
    assert question.context_field is ContextField.PROBABLE_DOMAIN
    assert question.answered_state is QuestionAnsweredState.UNANSWERED


def test_clarification_question_is_immutable() -> None:
    question = make_question()

    with pytest.raises(AttributeError):
        question.concise_text = "other"  # type: ignore[misc]


def test_clarification_question_rejects_empty_question_id() -> None:
    with pytest.raises(ValueError, match="question_id"):
        make_question(question_id="")


def test_clarification_question_rejects_empty_concise_text() -> None:
    with pytest.raises(ValueError, match="concise_text"):
        make_question(concise_text="")


def test_clarification_question_rejects_empty_explanation() -> None:
    with pytest.raises(ValueError, match="explanation"):
        make_question(explanation="")


def test_clarification_question_rejects_empty_affected_assumptions() -> None:
    with pytest.raises(ValueError, match="affected_assumptions"):
        make_question(affected_assumptions=())


def test_clarification_question_supports_inferred_default() -> None:
    question = make_question(inferred_default="Sales / order transactions")
    assert question.inferred_default == "Sales / order transactions"


def test_clarification_question_supports_no_suggested_answers() -> None:
    question = make_question(suggested_answers=())
    assert question.suggested_answers == ()


def test_clarification_question_supports_every_answered_state() -> None:
    for state in QuestionAnsweredState:
        question = make_question(answered_state=state)
        assert question.answered_state is state


def test_clarification_question_supports_every_context_field() -> None:
    for field in ContextField:
        question = make_question(context_field=field)
        assert question.context_field is field


# ---------------------------------------------------------------------------
# ClarificationAnswer (API-02, WP-059)
# ---------------------------------------------------------------------------


def make_answer(**overrides: object) -> ClarificationAnswer:
    fields: dict[str, object] = {
        "question_id": "cq-1",
        "selected_answer_or_free_text": "Sales / order transactions",
        "answered_timestamp": FIXED_NOW,
        "resulting_context_changes": (ContextField.PROBABLE_DOMAIN,),
        "provenance": Provenance.USER_CONFIRMED,
    }
    fields.update(overrides)
    return ClarificationAnswer(**fields)  # type: ignore[arg-type]


def test_clarification_answer_constructs_with_valid_fields() -> None:
    answer = make_answer()

    assert answer.question_id == "cq-1"
    assert answer.provenance is Provenance.USER_CONFIRMED
    assert answer.resulting_context_changes == (ContextField.PROBABLE_DOMAIN,)


def test_clarification_answer_is_immutable() -> None:
    answer = make_answer()

    with pytest.raises(AttributeError):
        answer.selected_answer_or_free_text = "other"  # type: ignore[misc]


def test_clarification_answer_rejects_empty_question_id() -> None:
    with pytest.raises(ValueError, match="question_id"):
        make_answer(question_id="")


def test_clarification_answer_rejects_empty_selected_answer_or_free_text() -> None:
    with pytest.raises(ValueError, match="selected_answer_or_free_text"):
        make_answer(selected_answer_or_free_text="")


def test_clarification_answer_rejects_empty_resulting_context_changes() -> None:
    with pytest.raises(ValueError, match="resulting_context_changes"):
        make_answer(resulting_context_changes=())


@pytest.mark.parametrize(
    "provenance",
    [Provenance.CALCULATED, Provenance.AI_INTERPRETATION, Provenance.DETERMINISTIC_FALLBACK],
)
def test_clarification_answer_rejects_non_user_provenance(provenance: Provenance) -> None:
    with pytest.raises(ValueError, match="provenance"):
        make_answer(provenance=provenance)


def test_clarification_answer_accepts_user_corrected_provenance() -> None:
    answer = make_answer(provenance=Provenance.USER_CORRECTED)
    assert answer.provenance is Provenance.USER_CORRECTED


def test_clarification_answer_supports_multiple_resulting_context_changes() -> None:
    answer = make_answer(
        resulting_context_changes=(ContextField.PROBABLE_DOMAIN, ContextField.ROW_GRAIN)
    )
    assert answer.resulting_context_changes == (
        ContextField.PROBABLE_DOMAIN,
        ContextField.ROW_GRAIN,
    )
