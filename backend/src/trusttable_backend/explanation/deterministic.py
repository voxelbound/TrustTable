"""Deterministic finding explanations (`AI-05`) — the first code in this
repository satisfying `docs/product-requirements.md` §5.7's "deterministic
explanations" bullet ("Without an LLM provider, the user still
receives: ... deterministic explanations ..."), a named AI-disabled-mode
requirement since `v0.1` baseline scope with no prior implementation.

Pure and framework-independent — no `ai_boundary`/`ai_provider` import
(mirrors `context_inference.heuristics`'s own structural "AI cannot
alter" guarantee): a deterministic explanation is built solely from a
`FindingCandidate`'s own already-safe, already-detector-authored fields
(`severity`, `category`, `calculated_observation`) — no raw dataset
re-read, no new data-access path, always available regardless of
whether any `AIProvider` is configured.

Stdlib only otherwise.
"""

from __future__ import annotations

from ..detectors.contract import FindingCandidate
from ..domain.explanation import FindingExplanation
from ..domain.value_objects import Provenance
from .guidance import build_deterministic_guidance

_SEVERITY_FRAMING = {
    "critical": "This is a critical-severity finding that likely requires immediate attention.",
    "high": "This is a high-severity finding that likely warrants prompt attention.",
    "medium": "This is a medium-severity finding worth reviewing.",
    "low": "This is a low-severity finding, included for completeness.",
    "informational": "This is an informational finding.",
}


def build_deterministic_explanation(finding: FindingCandidate) -> FindingExplanation:
    """Build a `FindingExplanation` for `finding` using only its own
    already-computed fields — no AI, always available.

    The narrative combines a fixed severity-framing sentence (see
    `_SEVERITY_FRAMING`) with the detector's own `calculated_observation`
    (already-safe, already-detector-authored display text — the same
    text the `FindingsRoute`/`FindingDetailRoute` UI already renders
    directly) and names the originating detector category/id for
    traceability. `referenced_evidence_ids`/`referenced_columns` mirror
    the finding's own `evidence_ids`/`affected_columns` exactly — a
    deterministic explanation cannot reference anything beyond what the
    finding itself already carries.

    `AI-08`: also carries the built-in guidance (`guidance.py`) — the
    conditional business impact, advisory remediation and proposed rule —
    so the four Finding Detail sections are useful with no AI at all.
    """
    guidance = build_deterministic_guidance(finding)
    framing = _SEVERITY_FRAMING.get(
        finding.severity.value, "This finding was flagged during analysis."
    )
    narrative = (
        f"{framing} Detector '{finding.detector_id}' ({finding.category.value}) "
        f"reports: {finding.calculated_observation}"
    )
    return FindingExplanation(
        narrative=narrative,
        provenance=Provenance.DETERMINISTIC_FALLBACK,
        referenced_evidence_ids=finding.evidence_ids,
        referenced_columns=finding.affected_columns,
        business_impact=guidance.business_impact,
        remediation=guidance.remediation,
        validation_rule=guidance.validation_rule,
    )


__all__ = ["build_deterministic_explanation"]
