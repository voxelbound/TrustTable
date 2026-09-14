"""Benchmark-only runtime adapters (`AI-06` hands-on evaluation support).

Every module under this package provides an `AIProvider`-conformant
class for the sole purpose of letting `ai_benchmark.runner.run_benchmark`
exercise a real, locally running inference runtime during the "hands-on
benchmark/model evaluation" step (`docs/decision-log.md` D-032/D-033).

**Not product code.** Nothing here is the production `AIProvider`
(`AI-03`). Nothing here is registered in `ai_provider.factory.
create_provider`, selectable via `Settings.llm_provider`, or reachable
from any FastAPI route or application service. Deliberately not
re-exported from `ai_benchmark`'s own top-level `__init__.py` — reach a
concrete adapter by importing its module directly (e.g.
`from trusttable_backend.ai_benchmark.adapters.llama_cpp_http import
LlamaCppHttpProvider`), matching this package's "explicit opt-in only"
posture.

`AI-03` (the real local-inference provider selected via the human-owned
runtime/model/quantization decision gate) remains fully unstarted; a
module existing here does not imply a runtime or model has been chosen.
"""

from __future__ import annotations

__all__: list[str] = []
