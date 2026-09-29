"""Per-analysis record of optional AI enrichment calls (`EXP-01` slice 4).

Counters and flags only. It never holds a prompt, a model output, a model
name, a URL or any dataset value, so it can be stored and disclosed
without widening what the product retains.

`Analysis.ai_enrichment` is `None` for an analysis persisted before
recording existed: that means *not recorded*, never *no calls*. A new
analysis starts with the zero record. A zero record is therefore a claim
that no call was made, and it is only true because every code path that
can reach a model records itself (`record_ai_enrichment_call`).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import StrEnum


class EnrichmentOutcome(StrEnum):
    """The `ai_call_status` outcomes of an attempted call."""

    ACCEPTED = "accepted"
    REJECTED = "rejected"
    PROVIDER_ERROR = "provider_error"


class EnrichmentModelLocation(StrEnum):
    """Where the model that may have received bounded metadata runs.

    `LOCAL` is claimed only for a known local runtime on this machine;
    everything else is `UNKNOWN`. There is deliberately no `REMOTE`: a
    non-local address is not proof that it is remote.
    """

    LOCAL = "local"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class AiEnrichmentRecord:
    """Counts of attempted enrichment calls by outcome, whether bounded
    finding evidence or confirmed context may have been sent, and where
    the model runs. The zero record means no call has been attempted.
    """

    accepted_count: int = 0
    rejected_count: int = 0
    provider_error_count: int = 0
    evidence_sent_to_model: bool = False
    confirmed_context_sent_to_model: bool = False
    model_location: EnrichmentModelLocation | None = None

    def __post_init__(self) -> None:
        for name in ("accepted_count", "rejected_count", "provider_error_count"):
            if getattr(self, name) < 0:
                raise ValueError(f"AiEnrichmentRecord.{name} must not be negative")
        if self.attempt_count == 0:
            if self.evidence_sent_to_model or self.confirmed_context_sent_to_model:
                raise ValueError("AiEnrichmentRecord reports data sent with no attempts")
            if self.model_location is not None:
                raise ValueError("AiEnrichmentRecord has a model location with no attempts")
        elif self.model_location is None:
            raise ValueError("AiEnrichmentRecord with attempts requires a model location")

    @property
    def attempt_count(self) -> int:
        return self.accepted_count + self.rejected_count + self.provider_error_count

    def with_call(
        self,
        outcome: EnrichmentOutcome,
        *,
        evidence_sent: bool,
        confirmed_context_sent: bool,
        location: EnrichmentModelLocation,
    ) -> AiEnrichmentRecord:
        """This record plus one attempted call. Sent flags only ever turn
        on; a location that differs from an earlier call's becomes
        `UNKNOWN` rather than silently keeping either."""
        merged_location = (
            location
            if self.model_location is None or self.model_location is location
            else EnrichmentModelLocation.UNKNOWN
        )
        return replace(
            self,
            accepted_count=self.accepted_count + (outcome is EnrichmentOutcome.ACCEPTED),
            rejected_count=self.rejected_count + (outcome is EnrichmentOutcome.REJECTED),
            provider_error_count=self.provider_error_count
            + (outcome is EnrichmentOutcome.PROVIDER_ERROR),
            evidence_sent_to_model=self.evidence_sent_to_model or evidence_sent,
            confirmed_context_sent_to_model=(
                self.confirmed_context_sent_to_model or confirmed_context_sent
            ),
            model_location=merged_location,
        )
