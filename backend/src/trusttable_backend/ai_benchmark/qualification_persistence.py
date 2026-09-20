"""Durable result document for a finding-analysis qualification run
(`REL-02`, `docs/decision-log.md` D-043).

`save_qualification_report` writes one deterministic JSON document (sorted
keys) at exactly the path the caller names — it never picks a location and
never creates a directory — so runs across candidate models, quantizations and
hardware, made weeks apart, can be compared later.

**What a document may carry.** Case ids (detector id and finding index),
outcomes, reason codes, exception *class* names, durations, aggregates, the
explicit candidate identity and optional caller-supplied resource observations.

**What it never carries.** Model output, exception message text (which can echo
model output or a URL), dataset values, the server URL, or an absolute host
path: model identifiers are reduced to their final path segment with the same
`ai_provider.display.sanitize_model_identifier` the product API uses. The
free-text `notes` field and the caller-chosen candidate labels are written as
given; do not put paths or secrets in them.

Reuses `persistence.CandidateMetadata`/`ResourceObservations` unchanged.
Stdlib only.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..ai_provider.display import sanitize_model_identifier
from .persistence import CandidateMetadata, ResourceObservations
from .qualification import (
    CaseResult,
    QualificationAggregate,
    QualificationReport,
)

#: Bumped whenever the document's own shape changes in a way a comparison tool
#: must distinguish. Independent of the case-set version and of the `AI-06`
#: result schema.
QUALIFICATION_RESULT_SCHEMA_VERSION = "1"

#: The harness identifier, so a comparison tool never confuses this document
#: with an `AI-06` benchmark result.
QUALIFICATION_HARNESS = "finding_analysis_qualification"


def _aggregate_to_dict(aggregate: QualificationAggregate) -> dict[str, Any]:
    latency = aggregate.case_latency
    return {
        "case_count": aggregate.case_count,
        "accepted_count": aggregate.accepted_count,
        "first_attempt_accepted_count": aggregate.first_attempt_accepted_count,
        "fallback_count": aggregate.fallback_count,
        "fill_rate": aggregate.fill_rate,
        "first_attempt_fill_rate": aggregate.first_attempt_fill_rate,
        "fallback_rate": aggregate.fallback_rate,
        "outcome_counts": dict(aggregate.outcome_counts),
        "rejection_reason_counts": dict(aggregate.rejection_reason_counts),
        "provider_error_kind_counts": dict(aggregate.provider_error_kind_counts),
        "retries_total": aggregate.retries_total,
        "attempt_count": aggregate.attempt_count,
        "case_latency_ms": {
            "count": latency.count,
            "mean": latency.mean_ms,
            "p50": latency.p50_ms,
            "p95": latency.p95_ms,
            "max": latency.max_ms,
        },
        "slowest_attempt_ms": aggregate.slowest_attempt_ms,
        "slowest_completed_attempt_ms": aggregate.slowest_completed_attempt_ms,
    }


def _case_result_to_dict(result: CaseResult) -> dict[str, Any]:
    return {
        "case_id": result.case_id,
        "detector_id": result.detector_id,
        "condition": result.condition.value,
        "outcome": result.outcome.value,
        "product_ai_call_status": result.product_ai_call_status,
        "retries_used": result.retries_used,
        "rejection_reasons": [reason.value for reason in result.rejection_reasons],
        "provider_error_kind": result.provider_error_kind,
        "attempts": [
            {"duration_ms": attempt.duration_ms, "error_kind": attempt.error_kind}
            for attempt in result.attempts
        ],
        "total_duration_ms": result.total_duration_ms,
        "confirmed_context_sent": result.confirmed_context_sent,
    }


def qualification_report_to_dict(
    report: QualificationReport,
    *,
    run_id: str,
    created_at: datetime,
    candidate: CandidateMetadata,
    resource_observations: ResourceObservations | None = None,
) -> dict[str, Any]:
    """Build exactly the JSON-serializable document `save_qualification_report`
    writes, with no file I/O."""
    return {
        "schema_version": QUALIFICATION_RESULT_SCHEMA_VERSION,
        "harness": QUALIFICATION_HARNESS,
        "run_id": run_id,
        "created_at": created_at.isoformat(),
        "case_set_version": report.case_set_version,
        "scope": report.scope.value,
        "conditions": [condition.value for condition in report.conditions],
        "provider_name": report.provider_name,
        "model_identifier": report.model_identifier,
        "server_available_at_start": report.server_available_at_start,
        "candidate": {
            "runtime_identifier": candidate.runtime_identifier,
            "model_identifier": sanitize_model_identifier(candidate.model_identifier) or "unknown",
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
            "max_retries": report.max_retries,
            "configured_timeout_seconds": report.configured_timeout_seconds,
            "notes": report.notes,
        },
        "case_results": [_case_result_to_dict(result) for result in report.case_results],
        "aggregate": _aggregate_to_dict(report.aggregate),
        "aggregate_by_condition": {
            name: _aggregate_to_dict(aggregate)
            for name, aggregate in report.aggregate_by_condition.items()
        },
    }


def save_qualification_report(
    report: QualificationReport,
    path: str | Path,
    *,
    candidate: CandidateMetadata,
    resource_observations: ResourceObservations | None = None,
    run_id: str | None = None,
    created_at: datetime | None = None,
) -> dict[str, Any]:
    """Serialize `report` to a deterministic JSON document at exactly `path`.

    `run_id` defaults to a fresh `uuid4`; `created_at` to the current UTC
    instant. Returns the exact dict written. Raises `OSError` when the parent
    directory does not exist (no directory is created).
    """
    document = qualification_report_to_dict(
        report,
        run_id=run_id if run_id is not None else str(uuid.uuid4()),
        created_at=created_at if created_at is not None else datetime.now(UTC),
        candidate=candidate,
        resource_observations=resource_observations,
    )
    Path(path).write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return document


def load_qualification_report(path: str | Path) -> dict[str, Any]:
    """Read a written document back as a plain dict for inspection or
    comparison. Raises `FileNotFoundError` for a missing file and `ValueError`
    when the top-level JSON value is not an object."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(
            f"{path}: expected a JSON object at the top level, got {type(raw).__name__}"
        )
    return raw


__all__ = [
    "QUALIFICATION_HARNESS",
    "QUALIFICATION_RESULT_SCHEMA_VERSION",
    "load_qualification_report",
    "qualification_report_to_dict",
    "save_qualification_report",
]
