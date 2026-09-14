"""The config-driven benchmark runner (`AI-06`).

`run_benchmark` exercises one `AIProvider` against a sequence of
`BenchmarkTask` fixtures and scores the results: structured-output
validity/groundedness (via `SEC-02`'s real `validate_model_output`,
never the provider's own self-report), harness-measured latency (never
the provider's own self-reported `duration_ms` — the same "engine-owned
measured timing" precedent `DET-01`'s `engine.py` already established),
bounded retry-rate (reusing `AI-01`'s existing `ProviderRequest.
retry_feedback` field), and repeated-call consistency.

Does not itself execute a real model/runtime — this module drives
whatever `AIProvider` it is given; proving it against a real local
model is the separate "hands-on benchmark/model evaluation" step
(`docs/decision-log.md` D-032/D-033), not part of this package. Not
wired into CI as a live-model-executing job for the same reason;
CI exercises only this module's own unit tests against `AI-02`'s
`MockProvider`/`DisabledProvider`.

Framework-independent: no FastAPI/SQLAlchemy/pydantic import. Stdlib
only, plus reuse of `ai_provider`/`ai_boundary`'s own stdlib-only types.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace
from time import perf_counter
from typing import Literal

from ..ai_boundary.validation import RejectionReason, validate_model_output
from ..ai_provider.contract import AIProvider, ProviderError, ProviderRequest
from .fixtures import FIXTURE_SET_VERSION, BenchmarkTask
from .metrics import BenchmarkReport, TaskResult

#: Matches `docs/decision-log.md` D-029's two named hardware profiles.
HardwareProfile = Literal["baseline", "accelerated"]


@dataclass(frozen=True, slots=True)
class BenchmarkConfig:
    """Run-time configuration for `run_benchmark`.

    `hardware_profile` is recorded in the resulting `BenchmarkReport`
    unchanged — never measured or validated against the actual host.
    """

    hardware_profile: HardwareProfile = "baseline"
    max_retries: int = 2
    consistency_repeats: int = 2
    notes: str = ""

    def __post_init__(self) -> None:
        if self.max_retries < 0:
            raise ValueError("BenchmarkConfig.max_retries must not be negative")
        if self.consistency_repeats < 0:
            raise ValueError("BenchmarkConfig.consistency_repeats must not be negative")


def _attempt(
    provider: AIProvider, request: ProviderRequest
) -> tuple[dict[str, object] | None, float, str | None]:
    """Call `provider.complete(request)` once, returning
    `(raw_output, harness_measured_duration_ms, provider_error)`.
    Exactly one of `raw_output`/`provider_error` is non-`None`.
    """
    start = perf_counter()
    try:
        response = provider.complete(request)
    except ProviderError as exc:
        elapsed_ms = (perf_counter() - start) * 1000
        return None, elapsed_ms, f"{type(exc).__name__}: {exc}"
    elapsed_ms = (perf_counter() - start) * 1000
    return dict(response.raw_output), elapsed_ms, None


def _run_one_task(provider: AIProvider, task: BenchmarkTask, config: BenchmarkConfig) -> TaskResult:
    request = task.request
    retries_used = 0
    accepted = False
    rejection_reasons: tuple[RejectionReason, ...] = ()
    duration_ms = 0.0
    first_raw_output: dict[str, object] | None = None
    provider_error: str | None = None

    while True:
        raw_output, elapsed_ms, error = _attempt(provider, request)
        if error is not None:
            provider_error = error
            duration_ms = elapsed_ms
            break
        assert raw_output is not None  # narrows for mypy: error is None iff raw_output is set
        if retries_used == 0:
            duration_ms = elapsed_ms
            first_raw_output = raw_output
        outcome = validate_model_output(
            raw_output, request.envelope, known_numeric_facts=request.known_numeric_facts
        )
        accepted = outcome.accepted
        rejection_reasons = outcome.rejection_reasons
        if accepted or retries_used >= config.max_retries:
            break
        request = replace(request, retry_feedback=outcome.safe_summary)
        retries_used += 1

    consistent = False
    if provider_error is None:
        consistent = True
        for _ in range(config.consistency_repeats):
            repeat_raw_output, _elapsed, repeat_error = _attempt(provider, task.request)
            if repeat_error is not None or repeat_raw_output != first_raw_output:
                consistent = False
                break

    return TaskResult(
        task_id=task.task_id,
        operation=task.operation,
        accepted=accepted,
        rejection_reasons=rejection_reasons,
        duration_ms=duration_ms,
        retries_used=retries_used,
        consistent=consistent,
        provider_error=provider_error,
    )


def run_benchmark(
    provider: AIProvider,
    tasks: Sequence[BenchmarkTask],
    *,
    config: BenchmarkConfig | None = None,
) -> BenchmarkReport:
    """Run every task in `tasks` against `provider` and return the
    aggregated `BenchmarkReport`. Never raises for a provider failure —
    every failure mode is captured in the returned report.
    """
    cfg = config if config is not None else BenchmarkConfig()
    health = provider.health_check()
    task_results = tuple(_run_one_task(provider, task, cfg) for task in tasks)
    task_count = len(task_results)
    accepted_count = sum(1 for result in task_results if result.accepted)
    consistency_count = sum(1 for result in task_results if result.consistent)
    return BenchmarkReport(
        provider_name=provider.provider_name,
        model_identifier=health.model_identifier,
        hardware_profile=cfg.hardware_profile,
        fixture_set_version=FIXTURE_SET_VERSION,
        task_results=task_results,
        task_count=task_count,
        accepted_count=accepted_count,
        validity_rate=(accepted_count / task_count) if task_count else 0.0,
        average_duration_ms=(sum(r.duration_ms for r in task_results) / task_count)
        if task_count
        else 0.0,
        average_retries_used=(sum(r.retries_used for r in task_results) / task_count)
        if task_count
        else 0.0,
        consistency_rate=(consistency_count / task_count) if task_count else 0.0,
        notes=cfg.notes,
    )


__all__ = ["BenchmarkConfig", "HardwareProfile", "run_benchmark"]
