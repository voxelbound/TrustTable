"""The binding a saved AI enrichment is valid for (D-066 item 7).

A saved result is bound to the finding identity, the confirmed-context version,
the model identity and the prompt/contract version. If any of them changes the
saved result is stale: it is neither shown as current nor reused.

Only a digest is stored (`FindingEnrichmentRecord.binding_digest`): the model
identity is often an absolute path and must not be written out in the clear.
The context part is the *effective* confirmed context: nothing is sent to a
model before the context is finalized (`AI-08`), so before that point only the
absence of context is bound.
"""

from __future__ import annotations

import hashlib
import json
from typing import Final

from ..ai_boundary.finding_analysis import FINDING_ANALYSIS_SCHEMA_VERSION
from ..ai_boundary.prompt import PROMPT_TEMPLATE_VERSION

#: Bumped only if the binding's own composition changes.
BINDING_FORMAT_VERSION: Final[str] = "1"


def compute_binding_digest(
    *,
    finding_id: str,
    context_version: int,
    context_finalized: bool,
    provider_name: str,
    model_identifier: str | None,
) -> str:
    """SHA-256 over the binding parts, in a fixed, unambiguous encoding."""
    parts = {
        "binding": BINDING_FORMAT_VERSION,
        "finding_id": finding_id,
        "context_version": context_version if context_finalized else 0,
        "provider": provider_name,
        "model": model_identifier or "",
        "contract": FINDING_ANALYSIS_SCHEMA_VERSION,
        "prompt": PROMPT_TEMPLATE_VERSION,
    }
    encoded = json.dumps(parts, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
