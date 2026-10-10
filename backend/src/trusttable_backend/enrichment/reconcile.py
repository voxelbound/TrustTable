"""Interrupted-enrichment-on-restart reconciliation (`UX-05b`).

An enrichment found `preparing` at startup belongs to a process that is gone:
no worker exists that could finish it. It is failed (`interrupted`) so it
never stays "preparing" for ever, and the attempt it may have made is recorded
in the analysis's AI call counters, because evidence may already have been sent
to the model (D-038, D-047). A failed enrichment is started again only by an
explicit request.

`main.create_app()` calls this unconditionally, before the enrichment pool
accepts work.
"""

from __future__ import annotations

from ..ai_provider.location import model_location_for
from ..analysis.service import AnalysisStoreProtocol, record_ai_enrichment_call
from ..config import Settings
from ..domain.ai_enrichment import EnrichmentOutcome
from ..persistence.enrichment_store import SqlEnrichmentStore


def reconcile_interrupted_enrichments(
    enrichment_store: SqlEnrichmentStore,
    analysis_store: AnalysisStoreProtocol,
    settings: Settings,
) -> int:
    """Fail every `preparing` enrichment. Returns how many were failed."""
    interrupted = enrichment_store.interrupt_preparing()
    location = model_location_for(settings.llm_provider, settings.llm_base_url)
    for enrichment in interrupted:
        record_ai_enrichment_call(
            analysis_store,
            enrichment.analysis_id,
            outcome=EnrichmentOutcome.PROVIDER_ERROR,
            evidence_sent=enrichment.evidence_sent_to_model,
            confirmed_context_sent=enrichment.confirmed_context_sent_to_model,
            location=location,
        )
    return len(interrupted)
