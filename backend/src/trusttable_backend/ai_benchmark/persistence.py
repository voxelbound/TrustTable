"""Durable, comparable benchmark-result persistence (`AI-06`, r3).

`save_report`/`load_report` serialize a `BenchmarkReport` (plus the
`BenchmarkConfig` that produced it), an explicit `CandidateMetadata`
identity, and optional `ResourceObservations`, to a single deterministic
JSON document, so multiple runs — across candidate runtimes, models,
and quantizations, potentially run weeks apart on different hardware —
can be inspected and compared later. This module never chooses a
location, a database, an API, or a network destination on its own: the
caller supplies the exact `path` to write, matching this package's
existing "caller-controlled, explicit" posture (`runner.py`'s own
docstring).

This module introduces no new product/runtime/model decision, no
database, no API, no UI, and no network dependency — only a file-I/O
serialization/deserialization pair for already-in-memory data. It does
**not** measure resource usage itself: `ResourceObservations` fields are
caller-supplied numbers only — no `psutil`, no GPU library, no
subprocess probing, no automatic hardware measurement is added here
(see this module's own r3 Non-goals in `docs/architecture.md`).

Framework-independent: no FastAPI/SQLAlchemy/pydantic import. Stdlib
only (`json`, `pathlib`, `uuid`, `datetime`, `dataclasses`).
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .metrics import BenchmarkReport
from .runner import BenchmarkConfig

#: Bumped whenever the persisted document's own top-level shape changes
#: in a way a future comparison tool needs to distinguish. Independent
#: of `fixtures.FIXTURE_SET_VERSION` (which versions the *fixtures*, not
#: the *result document* shape) — the two evolve for different reasons.
#: r3 bumps this: the document gained `candidate`/`resource_observations`.
BENCHMARK_RESULT_SCHEMA_VERSION = "2"


@dataclass(frozen=True, slots=True)
class CandidateMetadata:
    """Explicit, caller-supplied identity of the runtime/model/
    quantization/hardware-profile *candidate* a benchmark run evaluates
    — for the later hands-on comparison phase (`docs/decision-log.md`
    D-032/D-033).

    Deliberately distinct from `BenchmarkReport.provider_name`/
    `model_identifier` (the `AIProvider`'s own self-report, e.g.
    `"mock"`/`"mock-v1"` during this package's own tests): a future
    comparison tool must not have to parse free-form provider/model
    strings to know which candidate a persisted run belongs to — the
    caller states it explicitly here instead.

    `quantization_identifier` is the one field expected to be legitimately
    unknown/not-applicable for some candidates (e.g. an unquantized
    reference run) and is therefore nullable; the other three fields are
    always required.
    """

    runtime_identifier: str
    model_identifier: str
    hardware_profile: str
    quantization_identifier: str | None = None

    def __post_init__(self) -> None:
        if not self.runtime_identifier:
            raise ValueError("CandidateMetadata.runtime_identifier must not be empty")
        if not self.model_identifier:
            raise ValueError("CandidateMetadata.model_identifier must not be empty")
        if not self.hardware_profile:
            raise ValueError("CandidateMetadata.hardware_profile must not be empty")


@dataclass(frozen=True, slots=True)
class ResourceObservations:
    """Optional, caller-supplied observed resource usage for the later
    hands-on run.

    Both fields are plain numbers a caller measured by whatever means it
    chooses (e.g. reading a process monitor by hand, or a future,
    separately-approved host-telemetry package) — this module never
    measures them itself. Either or both may be omitted when not yet
    observed (e.g. every run in this package's own test suite, which
    uses `MockProvider`/`DisabledProvider`, has none to report).
    """

    peak_rss_mb: float | None = None
    peak_vram_mb: float | None = None

    def __post_init__(self) -> None:
        if self.peak_rss_mb is not None and self.peak_rss_mb < 0:
            raise ValueError("ResourceObservations.peak_rss_mb must not be negative")
        if self.peak_vram_mb is not None and self.peak_vram_mb < 0:
            raise ValueError("ResourceObservations.peak_vram_mb must not be negative")


def report_to_dict(
    report: BenchmarkReport,
    config: BenchmarkConfig,
    *,
    run_id: str,
    created_at: datetime,
    candidate: CandidateMetadata,
    resource_observations: ResourceObservations | None = None,
) -> dict[str, Any]:
    """Build the exact JSON-serializable document `save_report` writes,
    without performing any file I/O — used directly by `save_report` and
    independently by tests proving the document's shape.

    `report`/`config` are recorded together because `BenchmarkReport`
    itself only carries `hardware_profile`/`notes` from the config that
    produced it — `max_retries`/`consistency_repeats` are not otherwise
    recoverable from the report alone, and a future comparison needs the
    full configuration a run was produced under. `candidate` is required
    (not optional) — a persisted run without an explicit candidate
    identity cannot be meaningfully compared against another later.
    `resource_observations` is optional; when omitted, the document's
    `resource_observations` value is `null`, meaning "not observed for
    this run," not "observed as zero."
    """
    return {
        "schema_version": BENCHMARK_RESULT_SCHEMA_VERSION,
        "run_id": run_id,
        "created_at": created_at.isoformat(),
        "fixture_set_version": report.fixture_set_version,
        "provider_name": report.provider_name,
        "model_identifier": report.model_identifier,
        "hardware_profile": report.hardware_profile,
        "candidate": {
            "runtime_identifier": candidate.runtime_identifier,
            "model_identifier": candidate.model_identifier,
            "quantization_identifier": candidate.quantization_identifier,
            "hardware_profile": candidate.hardware_profile,
        },
        "resource_observations": (
            {
                "peak_rss_mb": resource_observations.peak_rss_mb,
                "peak_vram_mb": resource_observations.peak_vram_mb,
            }
            if resource_observations is not None
            else None
        ),
        "config": {
            "hardware_profile": config.hardware_profile,
            "max_retries": config.max_retries,
            "consistency_repeats": config.consistency_repeats,
            "notes": config.notes,
        },
        "task_results": [
            {
                "task_id": result.task_id,
                "operation": result.operation.value,
                "accepted": result.accepted,
                "rejection_reasons": [reason.value for reason in result.rejection_reasons],
                "duration_ms": result.duration_ms,
                "retries_used": result.retries_used,
                "consistent": result.consistent,
                "provider_error": result.provider_error,
            }
            for result in report.task_results
        ],
        "aggregate": {
            "task_count": report.task_count,
            "accepted_count": report.accepted_count,
            "validity_rate": report.validity_rate,
            "average_duration_ms": report.average_duration_ms,
            "average_retries_used": report.average_retries_used,
            "consistency_rate": report.consistency_rate,
        },
        "notes": report.notes,
    }


def save_report(
    report: BenchmarkReport,
    config: BenchmarkConfig,
    path: str | Path,
    *,
    candidate: CandidateMetadata,
    resource_observations: ResourceObservations | None = None,
    run_id: str | None = None,
    created_at: datetime | None = None,
) -> dict[str, Any]:
    """Serialize `report`/`config`/`candidate`/`resource_observations` to
    a deterministic JSON document and write it to exactly `path` — the
    one explicit write this function performs; it never picks a
    location itself.

    `run_id` defaults to a fresh `uuid4` string; `created_at` defaults
    to the current UTC instant. Both are accepted as explicit
    parameters so tests (and a future comparison tool) can also produce
    fully deterministic documents. Returns the exact dict written, so a
    caller can inspect it without re-reading the file.

    The written JSON text uses `sort_keys=True` so the same logical
    content always produces byte-identical file content, regardless of
    any incidental construction-order differences — the "deterministic/
    stable enough to compare later" requirement.
    """
    resolved_run_id = run_id if run_id is not None else str(uuid.uuid4())
    resolved_created_at = created_at if created_at is not None else datetime.now(UTC)
    document = report_to_dict(
        report,
        config,
        run_id=resolved_run_id,
        created_at=resolved_created_at,
        candidate=candidate,
        resource_observations=resource_observations,
    )
    target = Path(path)
    target.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return document


def load_report(path: str | Path) -> dict[str, Any]:
    """Read a `save_report`-written JSON document back into a plain
    dict, for inspection/comparison — not a `BenchmarkReport`
    reconstruction API; callers compare on the dict shape directly.

    Raises `FileNotFoundError` if `path` does not exist (the standard
    `pathlib`/`open` behavior, not swallowed) and `ValueError` if the
    file's top-level JSON value is not an object.
    """
    target = Path(path)
    raw = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(
            f"{path}: expected a JSON object at the top level, got {type(raw).__name__}"
        )
    return raw


__all__ = [
    "BENCHMARK_RESULT_SCHEMA_VERSION",
    "CandidateMetadata",
    "ResourceObservations",
    "load_report",
    "report_to_dict",
    "save_report",
]
