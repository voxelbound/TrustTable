"""The local AI benchmark harness (`AI-06`), matching
`docs/implementation-backlog.md#AI-06` and `docs/decision-log.md`
D-029/D-032/D-033: a persistent, reusable, config-driven evaluation
capability — fixed/versioned task fixtures built from real
`analysis.service`-computed evidence over the committed demo dataset
(`fixtures.py`), a runner that exercises any `AIProvider` (`AI-01`)
against those fixtures and scores structured-output validity/
groundedness, latency, bounded retry-rate, and repeated-call
consistency (`runner.py`), the result shapes that scoring produces
(`metrics.py`), and durable, comparable result persistence
(`persistence.py`).

This package builds and proves the harness itself, using `AI-02`'s
already-merged `MockProvider`/`DisabledProvider` — it does not perform
the separate "hands-on benchmark/model evaluation" step against a real
local model/runtime (`D-033`), which remains open, human-owned
follow-on work. Not product UI; not the production AI provider
integration; not wired into CI as a live-model-executing job (`D-032`).

**Scoring boundary (explicit, 2026-09-14):** this harness measures
structural validity/groundedness (via `ai_boundary.validation.
validate_model_output` — evidence IDs, columns, numeric claims, schema,
and provenance are all checked against what was actually sent),
harness-measured latency, bounded retry rate, and repeated-call
consistency. It does **not** currently score narrative/explanation
*quality*, semantic correctness beyond the existing grounding checks,
or *category accuracy* — none of those exist as a computed field
anywhere in this package. No fixed numeric acceptance threshold for any
metric is defined by this package or by any currently accepted decision
(`docs/decision-log.md` D-029/D-030/D-032 do not specify one). If
narrative-quality or category-accuracy scoring proves necessary before
a final model-selection decision, that is future benchmark-design work
— an expected-answer/expected-category rubric or an LLM-judge/human-
review step — not yet built, and not something this package invents on
its own authority.
"""

from __future__ import annotations

from .fixtures import FIXTURE_SET_VERSION, BenchmarkTask, FixtureGroundingError, build_fixture_tasks
from .metrics import BenchmarkReport, TaskResult
from .persistence import (
    BENCHMARK_RESULT_SCHEMA_VERSION,
    load_report,
    report_to_dict,
    save_report,
)
from .runner import BenchmarkConfig, HardwareProfile, run_benchmark

__all__ = [
    "BENCHMARK_RESULT_SCHEMA_VERSION",
    "FIXTURE_SET_VERSION",
    "BenchmarkConfig",
    "BenchmarkReport",
    "BenchmarkTask",
    "FixtureGroundingError",
    "HardwareProfile",
    "TaskResult",
    "build_fixture_tasks",
    "load_report",
    "report_to_dict",
    "run_benchmark",
    "save_report",
]
