"""The state of one finding's AI enrichment, as a caller sees it (D-066 item 7).

`preparing`, `ready` and `failed` are stored. The others are derived here and
never stored: `unavailable` (no model is configured), `stale` (the saved row
was produced under a different binding) and `not_requested` (no row yet). A
stale or failed result never replaces deterministic content.
"""

from __future__ import annotations

from enum import StrEnum

from ..domain.finding_enrichment import EnrichmentStatus, FindingEnrichment


class AiEnrichmentState(StrEnum):
    UNAVAILABLE = "unavailable"
    NOT_REQUESTED = "not_requested"
    PREPARING = "preparing"
    READY = "ready"
    FAILED = "failed"
    STALE = "stale"


def derive_state(
    *,
    provider_enabled: bool,
    current_binding_digest: str,
    enrichment: FindingEnrichment | None,
) -> AiEnrichmentState:
    if not provider_enabled:
        return AiEnrichmentState.UNAVAILABLE
    if enrichment is None:
        return AiEnrichmentState.NOT_REQUESTED
    if enrichment.binding_digest != current_binding_digest:
        return AiEnrichmentState.STALE
    return {
        EnrichmentStatus.PREPARING: AiEnrichmentState.PREPARING,
        EnrichmentStatus.READY: AiEnrichmentState.READY,
        EnrichmentStatus.FAILED: AiEnrichmentState.FAILED,
    }[enrichment.status]
