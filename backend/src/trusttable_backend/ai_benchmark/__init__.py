"""The local AI benchmark harness (`AI-06`), matching
`docs/implementation-backlog.md#AI-06` and `docs/decision-log.md`
D-029/D-032/D-033: a persistent, reusable, config-driven evaluation
capability — fixed/versioned task fixtures built from real
`analysis.service`-computed evidence over the committed demo dataset
(`fixtures.py`), a runner that exercises any `AIProvider` (`AI-01`)
against those fixtures and scores structured-output validity/
groundedness, latency, bounded retry-rate, and repeated-call
consistency (`runner.py`), the result shapes that scoring produces
(`metrics.py`), and durable, comparable result persistence — including
explicit candidate identity and optional observed resource usage for
the later hands-on comparison phase (`persistence.py`).

This package builds and proves the harness itself, using `AI-02`'s
already-merged `MockProvider`/`DisabledProvider` — it does not perform
the separate "hands-on benchmark/model evaluation" step against a real
local model/runtime (`D-033`), which remains open, human-owned
follow-on work. Not product UI; not the production AI provider
integration; not wired into CI as a live-model-executing job (`D-032`).

A second, separate instrument lives beside it (`qualification.py`,
`REL-02`, `docs/decision-log.md` D-043): the finding-analysis qualification
harness, which measures the *shipped* `finding_analysis_v1` product path (the
product's own envelope builder, provider, validator, retry and fallback)
rather than the older narrative contract this harness scores.

**Scoring boundary (explicit, confirmed 2026-09-14, r3):**

- **Measured by this harness itself:** structural validity/groundedness
  (via `ai_boundary.validation.validate_model_output` — evidence IDs,
  columns, numeric claims, schema, and provenance are all checked
  against what was actually sent), harness-measured latency, bounded
  retry rate, and repeated-call consistency.
- **Supplied/observed during the later hands-on run, not measured by
  this package:** runtime/model/quantization identity and the hardware
  profile (`persistence.CandidateMetadata`), and peak RSS/VRAM
  (`persistence.ResourceObservations`) — plain caller-supplied numbers;
  no `psutil`, GPU library, subprocess probing, or automatic hardware
  measurement is added by this package.
- **Still unscored, not implemented anywhere in this package:**
  narrative/explanation *quality*, semantic correctness beyond the
  existing grounding checks, *category accuracy*, and "practical
  usefulness" (a free-text `notes` field only).

No fixed numeric acceptance threshold for any metric — measured,
supplied, or unscored — is defined by this package or by any currently
accepted decision (`docs/decision-log.md` D-029/D-030/D-032 do not
specify one). If narrative-quality/category-accuracy scoring, or
automatic resource-usage measurement, or specific numeric acceptance
thresholds prove necessary before a final model-selection decision,
that is future benchmark-design work — not something this package
invents on its own authority.
"""

from __future__ import annotations

from .fixtures import FIXTURE_SET_VERSION, BenchmarkTask, FixtureGroundingError, build_fixture_tasks
from .metrics import BenchmarkReport, TaskResult
from .persistence import (
    BENCHMARK_RESULT_SCHEMA_VERSION,
    CandidateMetadata,
    ResourceObservations,
    load_report,
    report_to_dict,
    save_report,
)
from .qualification import (
    QUALIFICATION_CASE_SET_VERSION,
    CaseOutcome,
    CaseScope,
    Condition,
    MeasuringProvider,
    QualificationConfig,
    QualificationReport,
    QualificationSuite,
    build_qualification_suite,
    run_qualification,
)
from .qualification_persistence import (
    QUALIFICATION_RESULT_SCHEMA_VERSION,
    load_qualification_report,
    save_qualification_report,
)
from .runner import BenchmarkConfig, HardwareProfile, run_benchmark

__all__ = [
    "BENCHMARK_RESULT_SCHEMA_VERSION",
    "FIXTURE_SET_VERSION",
    "QUALIFICATION_CASE_SET_VERSION",
    "QUALIFICATION_RESULT_SCHEMA_VERSION",
    "BenchmarkConfig",
    "BenchmarkReport",
    "BenchmarkTask",
    "CandidateMetadata",
    "CaseOutcome",
    "CaseScope",
    "Condition",
    "FixtureGroundingError",
    "HardwareProfile",
    "MeasuringProvider",
    "QualificationConfig",
    "QualificationReport",
    "QualificationSuite",
    "ResourceObservations",
    "TaskResult",
    "build_fixture_tasks",
    "build_qualification_suite",
    "load_qualification_report",
    "load_report",
    "report_to_dict",
    "run_benchmark",
    "run_qualification",
    "save_qualification_report",
    "save_report",
]
