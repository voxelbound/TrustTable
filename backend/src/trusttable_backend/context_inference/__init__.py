"""Deterministic dataset-context inference (`CTX-01`) — the "Build
deterministic context hypotheses" analysis-pipeline step named in
`docs/architecture.md` §6, immediately before `CTX-02`'s "Optional
validated AI context inference".

Pure, framework-independent, stdlib-only heuristics computing
`domain.context.ContextHypothesis`/`DatasetContext` from `PROF-03`'s
already-computed `DatasetProfile`. No AI/LLM input path exists anywhere
in this package (mirrors `risk.scoring`'s own "AI cannot alter" no-
`ai_boundary`/`ai_provider`-import structural guarantee).

See `heuristics.py` for the public API.
"""

from __future__ import annotations

from .heuristics import (
    consolidate_dataset_context,
    infer_context_hypotheses,
    infer_dataset_context,
)

__all__ = [
    "consolidate_dataset_context",
    "infer_context_hypotheses",
    "infer_dataset_context",
]
