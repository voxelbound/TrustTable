"""Dataset context inference: `CTX-01`'s deterministic heuristics
(`heuristics.py`), `CTX-02`'s validated AI augmentation
(`ai_context.py`), and `CTX-03`'s deterministic guided-question
generation (`guided_questions.py`) — the "Build deterministic context
hypotheses" and "Optional validated AI context inference"
analysis-pipeline steps named in `docs/architecture.md` §6, plus the
guided-questions capability `docs/product-requirements.md` §8.4 names.

`heuristics.py` and `guided_questions.py` are pure, framework-
independent, and stdlib-only — no AI/LLM input path exists anywhere in
either (mirrors `risk.scoring`'s own "AI cannot alter" no-`ai_boundary`/
`ai_provider`-import structural guarantee). `ai_context.py` deliberately
imports both, since its entire purpose is calling a real `AIProvider`
through `SEC-02`'s trust boundary; it is an enabling slice, not yet
wired into the live analysis pipeline (see its own module docstring).

See `heuristics.py`/`ai_context.py`/`guided_questions.py` for the
public API.
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
from .guided_questions import MAX_GUIDED_QUESTIONS, generate_guided_questions
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
    "MAX_GUIDED_QUESTIONS",
    "ContextInferenceResult",
    "build_context_inference_envelope",
    "combine_hypotheses",
    "consolidate_dataset_context",
    "generate_guided_questions",
    "infer_context_hypotheses",
    "infer_dataset_context",
    "run_context_inference",
]
