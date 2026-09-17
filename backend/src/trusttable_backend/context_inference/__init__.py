"""Dataset context inference: `CTX-01`'s deterministic heuristics
(`heuristics.py`) and `CTX-02`'s validated AI augmentation
(`ai_context.py`) — the "Build deterministic context hypotheses" and
"Optional validated AI context inference" analysis-pipeline steps named
in `docs/architecture.md` §6.

`heuristics.py` is pure, framework-independent, and stdlib-only — no
AI/LLM input path exists anywhere in it (mirrors `risk.scoring`'s own
"AI cannot alter" no-`ai_boundary`/`ai_provider`-import structural
guarantee). `ai_context.py` deliberately imports both, since its entire
purpose is calling a real `AIProvider` through `SEC-02`'s trust
boundary; it is an enabling slice, not yet wired into the live analysis
pipeline (see its own module docstring).

See `heuristics.py`/`ai_context.py` for the public API.
"""

from __future__ import annotations

from .ai_context import (
    AI_CONTEXT_HYPOTHESIS_CONFIDENCE,
    AI_CONTEXT_HYPOTHESIS_ID,
    AI_CONTEXT_TASK,
    DEFAULT_MAX_RETRIES,
    ContextInferenceResult,
    build_context_inference_envelope,
    combine_hypotheses,
    run_context_inference,
)
from .heuristics import (
    consolidate_dataset_context,
    infer_context_hypotheses,
    infer_dataset_context,
)

__all__ = [
    "AI_CONTEXT_HYPOTHESIS_CONFIDENCE",
    "AI_CONTEXT_HYPOTHESIS_ID",
    "AI_CONTEXT_TASK",
    "DEFAULT_MAX_RETRIES",
    "ContextInferenceResult",
    "build_context_inference_envelope",
    "combine_hypotheses",
    "consolidate_dataset_context",
    "infer_context_hypotheses",
    "infer_dataset_context",
    "run_context_inference",
]
