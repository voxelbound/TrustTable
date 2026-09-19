"""Finding analysis (`AI-05`, extended by `AI-08`): `deterministic.py`'s
always-available, no-AI explanation (`docs/product-requirements.md`
§5.7) with `guidance.py`'s built-in business impact, advisory remediation
and proposed rule, and `ai_explanation.py`'s validated, structurally
constrained AI analysis of the same four sections.

`deterministic.py`/`guidance.py` are pure and framework-independent — no
AI/LLM input path exists in them (mirrors `context_inference.
heuristics`'s own "AI cannot alter" structural guarantee).
`ai_explanation.py` deliberately imports `ai_boundary`/`ai_provider`,
since its entire purpose is calling a real `AIProvider` through
`SEC-02`'s trust boundary.

See each module for its public API.
"""

from __future__ import annotations

from .ai_explanation import (
    AI_EXPLANATION_TASK,
    DEFAULT_MAX_RETRIES,
    FindingExplanationResult,
    build_finding_analysis_task,
    build_finding_explanation_envelope,
    confirmed_context_for_finding_analysis,
    run_finding_explanation,
)
from .deterministic import build_deterministic_explanation
from .guidance import GUIDED_DETECTOR_IDS, FindingGuidance, build_deterministic_guidance

__all__ = [
    "AI_EXPLANATION_TASK",
    "DEFAULT_MAX_RETRIES",
    "GUIDED_DETECTOR_IDS",
    "FindingExplanationResult",
    "FindingGuidance",
    "build_deterministic_explanation",
    "build_deterministic_guidance",
    "build_finding_analysis_task",
    "build_finding_explanation_envelope",
    "confirmed_context_for_finding_analysis",
    "run_finding_explanation",
]
