"""`FindingReview` (`REV-01`, `docs/domain-model.md` §12's "review
state"/"user note" fields, `WP-083`) — a user-set, persisted review
decision for one finding, keyed by `finding_id` and stored separately
from the immutable, detector-computed `FindingCandidate`
(`detectors.contract.FindingCandidate`'s own docstring: "a later package
assigns a finding ID, review state, and created timestamp" — this module
is that later package's review-state half; `finding_id` itself stays the
existing stringified-index scheme `analysis.service.get_finding` already
established).

A finding with no `FindingReview` recorded is implicitly `unreviewed`
with no note — this module never materializes that default as a stored
record; `Analysis.finding_reviews` (`analysis/service.py`) is a mapping
of only the findings someone has actually reviewed.

`dismissal_reason` (`docs/implementation-backlog.md#REV-01`: "status,
note, timestamp, and dismissal reason") is meaningful only for
`DISMISSED`: required and non-empty there, and forbidden (must be
`None`) for every other state — enforced in `__post_init__`, not left to
the API layer alone, so no code path can ever construct an inconsistent
`FindingReview`.

Framework-independent: no FastAPI/SQLAlchemy/pydantic import. Stdlib
only besides `value_objects`-style conventions already used elsewhere in
`domain/`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class FindingReviewState(StrEnum):
    """The closed review-state set `docs/product-requirements.md` §8.6
    documents for a finding."""

    UNREVIEWED = "unreviewed"
    CONFIRMED = "confirmed"
    DISMISSED = "dismissed"
    NEEDS_INVESTIGATION = "needs_investigation"


@dataclass(frozen=True, slots=True)
class FindingReview:
    """One finding's current review decision. Replaces any prior review
    for the same `finding_id` wholesale (`analysis.service.
    set_finding_review`) — no history is retained, matching
    `domain.rules.ValidationRule`'s own no-history precedent."""

    finding_id: str
    state: FindingReviewState
    note: str | None
    dismissal_reason: str | None
    reviewed_at: datetime

    def __post_init__(self) -> None:
        if not self.finding_id:
            raise ValueError("FindingReview.finding_id must not be empty")
        if self.state is FindingReviewState.DISMISSED:
            if not self.dismissal_reason:
                raise ValueError(
                    "FindingReview.dismissal_reason is required when state is dismissed"
                )
        elif self.dismissal_reason is not None:
            raise ValueError(
                "FindingReview.dismissal_reason must be None unless state is dismissed"
            )
        if self.note is not None and not self.note:
            raise ValueError("FindingReview.note must not be an empty string (use None)")


__all__ = ["FindingReview", "FindingReviewState"]
