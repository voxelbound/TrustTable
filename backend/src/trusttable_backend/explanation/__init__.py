"""Finding explanations (`AI-05`): `deterministic.py`'s always-available,
no-AI explanation (`docs/product-requirements.md` §5.7) and
`ai_explanation.py`'s validated AI-grounded explanation (enabling
slice, not yet wired into the live analysis pipeline — see its own
module docstring).

`deterministic.py` is pure and framework-independent — no AI/LLM input
path exists in it (mirrors `context_inference.heuristics`'s own
"AI cannot alter" structural guarantee). `ai_explanation.py`
deliberately imports `ai_boundary`/`ai_provider`, since its entire
purpose is calling a real `AIProvider` through `SEC-02`'s trust
boundary.

See `deterministic.py`/`ai_explanation.py` for the public API.
"""

from __future__ import annotations

from .ai_explanation import (
    AI_EXPLANATION_TASK,
    DEFAULT_MAX_RETRIES,
    FindingExplanationResult,
    build_finding_explanation_envelope,
    run_finding_explanation,
)
from .deterministic import build_deterministic_explanation

__all__ = [
    "AI_EXPLANATION_TASK",
    "DEFAULT_MAX_RETRIES",
    "FindingExplanationResult",
    "build_deterministic_explanation",
    "build_finding_explanation_envelope",
    "run_finding_explanation",
]
