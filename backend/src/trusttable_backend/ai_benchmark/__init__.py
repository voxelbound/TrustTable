"""The local AI benchmark harness (`AI-06`), matching
`docs/implementation-backlog.md#AI-06` and `docs/decision-log.md`
D-029/D-032/D-033: a persistent, reusable, config-driven evaluation
capability — fixed/versioned task fixtures built from real
`analysis.service`-computed evidence over the committed demo dataset
(`fixtures.py`), a runner that exercises any `AIProvider` (`AI-01`)
against those fixtures and scores structured-output validity/
groundedness, latency, bounded retry-rate, and repeated-call
consistency (`runner.py`), and the result shapes that scoring produces
(`metrics.py`).

This package builds and proves the harness itself, using `AI-02`'s
already-merged `MockProvider`/`DisabledProvider` — it does not perform
the separate "hands-on benchmark/model evaluation" step against a real
local model/runtime (`D-033`), which remains open, human-owned
follow-on work. Not product UI; not the production AI provider
integration; not wired into CI as a live-model-executing job (`D-032`).
"""

from __future__ import annotations

from .fixtures import FIXTURE_SET_VERSION, BenchmarkTask, FixtureGroundingError, build_fixture_tasks
from .metrics import BenchmarkReport, TaskResult
from .runner import BenchmarkConfig, HardwareProfile, run_benchmark

__all__ = [
    "FIXTURE_SET_VERSION",
    "BenchmarkConfig",
    "BenchmarkReport",
    "BenchmarkTask",
    "FixtureGroundingError",
    "HardwareProfile",
    "TaskResult",
    "build_fixture_tasks",
    "run_benchmark",
]
