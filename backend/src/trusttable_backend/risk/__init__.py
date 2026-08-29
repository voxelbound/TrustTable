"""Deterministic risk scoring (`RISK-01`) — the "Risk scoring" backend
layer named in `docs/architecture.md` §3.

Pure, framework-independent, stdlib-only functions computing a
per-finding deterministic priority score and a dataset-level trust
assessment from `DET-01`'s existing `FindingCandidate` output and
`PROF-03`'s `DatasetProfile` context. No AI/LLM input path exists
anywhere in this package (`docs/product-requirements.md` §5.3: "The LLM
cannot... lower or replace the deterministic risk score").

See `scoring.py` for the public API.
"""

from __future__ import annotations

from .scoring import (
    TrustAssessment,
    TrustLabel,
    calculate_finding_priority_score,
    calculate_finding_priority_scores,
    calculate_trust_assessment,
)

__all__ = [
    "TrustAssessment",
    "TrustLabel",
    "calculate_finding_priority_score",
    "calculate_finding_priority_scores",
    "calculate_trust_assessment",
]
