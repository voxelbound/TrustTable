"""Durable, comparable benchmark-result persistence (`AI-06`, r2).

`save_report`/`load_report` serialize a `BenchmarkReport` (plus the
`BenchmarkConfig` that produced it) to a single deterministic JSON
document, so multiple runs — across candidate runtimes, models, and
quantizations, potentially run weeks apart on different hardware — can
be inspected and compared later. This module never chooses a location,
a database, an API, or a network destination on its own: the caller
supplies the exact `path` to write, matching this package's existing
"caller-controlled, explicit" posture (`runner.py`'s own docstring).

This module introduces no new product/runtime/model decision, no
database, no API, no UI, and no network dependency — only a file-I/O
serialization/deserialization pair for an already-in-memory
`BenchmarkReport`.

Framework-independent: no FastAPI/SQLAlchemy/pydantic import. Stdlib
only (`json`, `pathlib`, `uuid`, `datetime`).
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .metrics import BenchmarkReport
from .runner import BenchmarkConfig

#: Bumped whenever the persisted document's own top-level shape changes
#: in a way a future comparison tool needs to distinguish. Independent
#: of `fixtures.FIXTURE_SET_VERSION` (which versions the *fixtures*, not
#: the *result document* shape) — the two evolve for different reasons.
BENCHMARK_RESULT_SCHEMA_VERSION = "1"


def report_to_dict(
    report: BenchmarkReport,
    config: BenchmarkConfig,
    *,
    run_id: str,
    created_at: datetime,
) -> dict[str, Any]:
    """Build the exact JSON-serializable document `save_report` writes,
    without performing any file I/O — used directly by `save_report` and
    independently by tests proving the document's shape.

    `report`/`config` are recorded together because `BenchmarkReport`
    itself only carries `hardware_profile`/`notes` from the config that
    produced it — `max_retries`/`consistency_repeats` are not otherwise
    recoverable from the report alone, and a future comparison needs the
    full configuration a run was produced under.
    """
    return {
        "schema_version": BENCHMARK_RESULT_SCHEMA_VERSION,
        "run_id": run_id,
        "created_at": created_at.isoformat(),
        "fixture_set_version": report.fixture_set_version,
        "provider_name": report.provider_name,
        "model_identifier": report.model_identifier,
        "hardware_profile": report.hardware_profile,
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
    run_id: str | None = None,
    created_at: datetime | None = None,
) -> dict[str, Any]:
    """Serialize `report`/`config` to a deterministic JSON document and
    write it to exactly `path` — the one explicit write this function
    performs; it never picks a location itself.

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
        report, config, run_id=resolved_run_id, created_at=resolved_created_at
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


__all__ = ["BENCHMARK_RESULT_SCHEMA_VERSION", "load_report", "report_to_dict", "save_report"]
