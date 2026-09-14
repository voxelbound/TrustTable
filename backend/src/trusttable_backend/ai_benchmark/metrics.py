"""Per-task and aggregate benchmark scoring shapes (`AI-06`).

`TaskResult` records one `BenchmarkTask`'s outcome; `BenchmarkReport`
aggregates a full run. "Groundedness" is not a separately computed
field here — it is exactly what `TaskResult.accepted`/
`rejection_reasons` already prove, since `ai_boundary.validation.
validate_model_output` (`SEC-02`) only accepts an output whose evidence
IDs, columns, and numeric claims are all actually grounded in what was
sent (`docs/decision-log.md` D-032, this package's own Recorded
assumption 1).

RAM/VRAM fit and "practical usefulness" (`docs/implementation-
backlog.md#AI-06`'s own listed criteria) are not computed by this
module — see `BenchmarkReport.hardware_profile`/`notes` and this
package's Non-goals.

Framework-independent: no FastAPI/SQLAlchemy/pydantic import. Stdlib
only.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..ai_boundary.validation import RejectionReason
from ..ai_provider.contract import AIOperation


@dataclass(frozen=True, slots=True)
class TaskResult:
    """One `BenchmarkTask`'s outcome.

    `provider_error` is set (and every other outcome field left at its
    default/empty value) when the provider itself raised a
    `ProviderError` rather than returning a response — a distinct
    failure mode from a structurally-rejected-but-returned output
    (Recorded assumption 5). `consistent` is `False` whenever
    `provider_error` is set: consistency cannot be proven for a task
    that never received a response at all.
    """

    task_id: str
    operation: AIOperation
    accepted: bool
    rejection_reasons: tuple[RejectionReason, ...]
    duration_ms: float
    retries_used: int
    consistent: bool
    provider_error: str | None = None

    def __post_init__(self) -> None:
        if not self.task_id:
            raise ValueError("TaskResult.task_id must not be empty")
        if self.duration_ms < 0:
            raise ValueError("TaskResult.duration_ms must not be negative")
        if self.retries_used < 0:
            raise ValueError("TaskResult.retries_used must not be negative")


@dataclass(frozen=True, slots=True)
class BenchmarkReport:
    """One full benchmark run's results.

    `hardware_profile` is a caller-supplied label matching
    `docs/decision-log.md` D-029's two named profiles (`"baseline"`,
    `"accelerated"`) — not measured by this module. `notes` is an
    optional free-text field for a human evaluator's own practical-
    usefulness judgment; also not computed.
    """

    provider_name: str
    model_identifier: str
    hardware_profile: str
    fixture_set_version: str
    task_results: tuple[TaskResult, ...]
    task_count: int
    accepted_count: int
    validity_rate: float
    average_duration_ms: float
    average_retries_used: float
    consistency_rate: float
    notes: str = ""

    def __post_init__(self) -> None:
        if not self.provider_name:
            raise ValueError("BenchmarkReport.provider_name must not be empty")
        if not self.fixture_set_version:
            raise ValueError("BenchmarkReport.fixture_set_version must not be empty")
        if self.task_count != len(self.task_results):
            raise ValueError("BenchmarkReport.task_count must equal len(task_results)")
        if self.accepted_count > self.task_count:
            raise ValueError("BenchmarkReport.accepted_count must not exceed task_count")
        if self.accepted_count < 0:
            raise ValueError("BenchmarkReport.accepted_count must not be negative")


__all__ = ["BenchmarkReport", "TaskResult"]
