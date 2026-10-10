"""Persisted, non-blocking AI enrichment of one finding (`UX-05b`, D-066 item 7).

`binding` says which saved result is still valid; `state` derives the state a
caller sees. Storage is `persistence.enrichment_store`; execution is
`jobs.enrichment_pool`; the routes live in `api.v1.analyses`.
"""

from .binding import compute_binding_digest
from .state import AiEnrichmentState, derive_state

__all__ = ["AiEnrichmentState", "compute_binding_digest", "derive_state"]
