"""A persisted AI enrichment of one finding (`UX-05b`, D-066 item 7).

The enrichment is an optional, additive layer over the deterministic result:
it never replaces or delays it. A saved result is valid only for the binding
it was produced under (see `enrichment.binding`); when the binding changes the
result is *stale* and is neither shown as current nor reused.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from .explanation import FindingExplanation


class EnrichmentStatus(StrEnum):
    """What is stored. `stale`, `unavailable` and `not_requested` are never
    stored: they are derived from the binding, the configuration and the
    absence of a row (`enrichment.state`)."""

    PREPARING = "preparing"
    READY = "ready"
    FAILED = "failed"


class EnrichmentReason(StrEnum):
    """Why an enrichment is `failed`. Fixed, content-free codes."""

    INTERRUPTED = "interrupted"
    PROVIDER_ERROR = "provider_error"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"
    UNREADABLE = "unreadable"


@dataclass(frozen=True, slots=True)
class FindingEnrichment:
    """One stored enrichment row.

    `ai_call_status`, `evidence_sent_to_model` and
    `confirmed_context_sent_to_model` are the same per-call disclosure the
    explanation response carries (D-038, D-047). While `PREPARING` they are
    deliberately conservative ("may have been sent"); a completed attempt
    overwrites them with what actually happened.

    `explanation` is set only for a `READY` row: it is the validated
    structured result and is the only model output ever stored.
    """

    analysis_id: str
    finding_id: str
    status: EnrichmentStatus
    binding_digest: str
    reason: EnrichmentReason | None
    ai_call_status: str
    evidence_sent_to_model: bool
    confirmed_context_sent_to_model: bool
    explanation: FindingExplanation | None
    created_at: datetime
    updated_at: datetime

    def __post_init__(self) -> None:
        if (self.status is EnrichmentStatus.READY) != (self.explanation is not None):
            raise ValueError("a saved explanation exists exactly when the enrichment is ready")
        if (self.status is EnrichmentStatus.FAILED) != (self.reason is not None):
            raise ValueError("a failure reason exists exactly when the enrichment has failed")
