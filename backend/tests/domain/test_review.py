"""Tests for `domain.review.FindingReview`/`FindingReviewState` (`REV-01`,
`WP-083`).

Covers the closed review-state enum and `FindingReview`'s own invariant:
`dismissal_reason` required and non-empty exactly when `state` is
`dismissed`, forbidden otherwise, and `note` never an empty string.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from trusttable_backend.domain.review import FindingReview, FindingReviewState

REVIEWED_AT = datetime(2026, 9, 28, 12, 0, tzinfo=UTC)


def test_review_state_is_closed_four_value_enumeration() -> None:
    assert frozenset(FindingReviewState) == frozenset(
        {
            FindingReviewState.UNREVIEWED,
            FindingReviewState.CONFIRMED,
            FindingReviewState.DISMISSED,
            FindingReviewState.NEEDS_INVESTIGATION,
        }
    )


@pytest.mark.parametrize(
    "state",
    [
        FindingReviewState.UNREVIEWED,
        FindingReviewState.CONFIRMED,
        FindingReviewState.NEEDS_INVESTIGATION,
    ],
)
def test_non_dismissed_states_construct_without_a_dismissal_reason(
    state: FindingReviewState,
) -> None:
    review = FindingReview(
        finding_id="0",
        state=state,
        note=None,
        dismissal_reason=None,
        reviewed_at=REVIEWED_AT,
    )
    assert review.state is state
    assert review.dismissal_reason is None


def test_dismissed_requires_a_dismissal_reason() -> None:
    with pytest.raises(ValueError, match="dismissal_reason is required"):
        FindingReview(
            finding_id="0",
            state=FindingReviewState.DISMISSED,
            note=None,
            dismissal_reason=None,
            reviewed_at=REVIEWED_AT,
        )


def test_dismissed_rejects_an_empty_dismissal_reason() -> None:
    with pytest.raises(ValueError, match="dismissal_reason is required"):
        FindingReview(
            finding_id="0",
            state=FindingReviewState.DISMISSED,
            note=None,
            dismissal_reason="",
            reviewed_at=REVIEWED_AT,
        )


def test_dismissed_with_a_reason_constructs() -> None:
    review = FindingReview(
        finding_id="0",
        state=FindingReviewState.DISMISSED,
        note=None,
        dismissal_reason="Known-fixed currency code, not a defect.",
        reviewed_at=REVIEWED_AT,
    )
    assert review.dismissal_reason == "Known-fixed currency code, not a defect."


@pytest.mark.parametrize(
    "state",
    [
        FindingReviewState.UNREVIEWED,
        FindingReviewState.CONFIRMED,
        FindingReviewState.NEEDS_INVESTIGATION,
    ],
)
def test_non_dismissed_states_reject_a_dismissal_reason(state: FindingReviewState) -> None:
    with pytest.raises(ValueError, match="must be None unless state is dismissed"):
        FindingReview(
            finding_id="0",
            state=state,
            note=None,
            dismissal_reason="should not be allowed here",
            reviewed_at=REVIEWED_AT,
        )


def test_empty_finding_id_rejected() -> None:
    with pytest.raises(ValueError, match="finding_id must not be empty"):
        FindingReview(
            finding_id="",
            state=FindingReviewState.UNREVIEWED,
            note=None,
            dismissal_reason=None,
            reviewed_at=REVIEWED_AT,
        )


def test_empty_note_rejected_use_none_instead() -> None:
    with pytest.raises(ValueError, match="note must not be an empty string"):
        FindingReview(
            finding_id="0",
            state=FindingReviewState.CONFIRMED,
            note="",
            dismissal_reason=None,
            reviewed_at=REVIEWED_AT,
        )


def test_note_is_optional_and_stored_verbatim() -> None:
    review = FindingReview(
        finding_id="3",
        state=FindingReviewState.NEEDS_INVESTIGATION,
        note="Check with the source-system owner before confirming.",
        dismissal_reason=None,
        reviewed_at=REVIEWED_AT,
    )
    assert review.note == "Check with the source-system owner before confirming."
