"""Tests for durable benchmark-result persistence (`AI-06`, r2).

Covers this package's r2 acceptance criteria AC-12..AC-16: round-trip
fidelity, deterministic/stable serialization, schema shape, and
relevant failure/boundary cases.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from trusttable_backend.ai_benchmark.fixtures import build_fixture_tasks
from trusttable_backend.ai_benchmark.metrics import BenchmarkReport
from trusttable_backend.ai_benchmark.persistence import (
    BENCHMARK_RESULT_SCHEMA_VERSION,
    load_report,
    report_to_dict,
    save_report,
)
from trusttable_backend.ai_benchmark.runner import BenchmarkConfig, run_benchmark
from trusttable_backend.ai_boundary.validation import MODEL_OUTPUT_SCHEMA_VERSION, RejectionReason
from trusttable_backend.ai_provider.contract import AIOperation, ProviderRequest
from trusttable_backend.ai_provider.disabled import DisabledProvider
from trusttable_backend.ai_provider.mock import MockProvider
from trusttable_backend.domain.value_objects import Provenance

_FIXED_CREATED_AT = datetime(2026, 9, 14, 12, 0, 0, tzinfo=UTC)
_FIXED_RUN_ID = "run-fixed-0001"


def _sample_report_and_config() -> tuple[BenchmarkReport, BenchmarkConfig]:
    config = BenchmarkConfig(hardware_profile="baseline", max_retries=2, consistency_repeats=1)
    report = run_benchmark(
        MockProvider(model_identifier="mock-bench-v1"), build_fixture_tasks(), config=config
    )
    return report, config


# ---------------------------------------------------------------------------
# AC-12: document shape / metadata completeness


def test_report_to_dict_contains_all_required_top_level_keys() -> None:
    report, config = _sample_report_and_config()
    document = report_to_dict(report, config, run_id=_FIXED_RUN_ID, created_at=_FIXED_CREATED_AT)
    assert set(document.keys()) == {
        "schema_version",
        "run_id",
        "created_at",
        "fixture_set_version",
        "provider_name",
        "model_identifier",
        "hardware_profile",
        "config",
        "task_results",
        "aggregate",
        "notes",
    }
    assert document["schema_version"] == BENCHMARK_RESULT_SCHEMA_VERSION
    assert document["run_id"] == _FIXED_RUN_ID
    assert document["created_at"] == _FIXED_CREATED_AT.isoformat()
    assert document["provider_name"] == "mock"
    assert document["model_identifier"] == "mock-bench-v1"
    assert document["hardware_profile"] == "baseline"


def test_report_to_dict_config_section_matches_supplied_config() -> None:
    report, config = _sample_report_and_config()
    document = report_to_dict(report, config, run_id=_FIXED_RUN_ID, created_at=_FIXED_CREATED_AT)
    assert document["config"] == {
        "hardware_profile": "baseline",
        "max_retries": 2,
        "consistency_repeats": 1,
        "notes": "",
    }


def test_report_to_dict_task_results_are_json_native_types() -> None:
    """Boundary: `AIOperation`/`RejectionReason` StrEnum values and
    `None` are converted to plain JSON-serializable values, not left as
    Enum instances (which `json.dumps` cannot handle for a strict
    round-trip comparison)."""
    report, config = _sample_report_and_config()
    document = report_to_dict(report, config, run_id=_FIXED_RUN_ID, created_at=_FIXED_CREATED_AT)
    assert len(document["task_results"]) == 6
    for entry in document["task_results"]:
        assert isinstance(entry["operation"], str)
        assert entry["operation"] in {op.value for op in AIOperation}
        assert isinstance(entry["rejection_reasons"], list)
        for reason in entry["rejection_reasons"]:
            assert isinstance(reason, str)
        assert entry["provider_error"] is None


def test_report_to_dict_aggregate_matches_report_fields() -> None:
    report, config = _sample_report_and_config()
    document = report_to_dict(report, config, run_id=_FIXED_RUN_ID, created_at=_FIXED_CREATED_AT)
    assert document["aggregate"] == {
        "task_count": report.task_count,
        "accepted_count": report.accepted_count,
        "validity_rate": report.validity_rate,
        "average_duration_ms": report.average_duration_ms,
        "average_retries_used": report.average_retries_used,
        "consistency_rate": report.consistency_rate,
    }


# ---------------------------------------------------------------------------
# AC-13: round-trip fidelity through save_report/load_report


def test_save_report_then_load_report_round_trips_exactly(tmp_path: Path) -> None:
    report, config = _sample_report_and_config()
    target = tmp_path / "run.json"
    written = save_report(
        report, config, target, run_id=_FIXED_RUN_ID, created_at=_FIXED_CREATED_AT
    )
    loaded = load_report(target)
    assert loaded == written
    assert loaded == report_to_dict(
        report, config, run_id=_FIXED_RUN_ID, created_at=_FIXED_CREATED_AT
    )


def test_save_report_accepts_str_path_as_well_as_path_object(tmp_path: Path) -> None:
    report, config = _sample_report_and_config()
    target = tmp_path / "run-str.json"
    save_report(report, config, str(target), run_id=_FIXED_RUN_ID, created_at=_FIXED_CREATED_AT)
    assert target.exists()
    loaded = load_report(str(target))
    assert loaded["run_id"] == _FIXED_RUN_ID


# ---------------------------------------------------------------------------
# AC-14: deterministic/stable serialization


def test_save_report_produces_byte_identical_output_for_identical_input(tmp_path: Path) -> None:
    report, config = _sample_report_and_config()
    first_path = tmp_path / "first.json"
    second_path = tmp_path / "second.json"
    save_report(report, config, first_path, run_id=_FIXED_RUN_ID, created_at=_FIXED_CREATED_AT)
    save_report(report, config, second_path, run_id=_FIXED_RUN_ID, created_at=_FIXED_CREATED_AT)
    assert first_path.read_text(encoding="utf-8") == second_path.read_text(encoding="utf-8")


def test_save_report_default_run_id_and_created_at_are_distinct_across_calls(
    tmp_path: Path,
) -> None:
    """Boundary: when not supplied, `run_id`/`created_at` are still
    populated (not left blank/null) and vary call to call, so two
    default-invoked runs remain distinguishable."""
    report, config = _sample_report_and_config()
    first = save_report(report, config, tmp_path / "a.json")
    second = save_report(report, config, tmp_path / "b.json")
    assert first["run_id"] != ""
    assert second["run_id"] != ""
    assert first["run_id"] != second["run_id"]
    assert first["created_at"] != ""


# ---------------------------------------------------------------------------
# AC-15: a real adversarial/rejected/provider-error run also persists correctly


def test_save_report_persists_rejected_and_provider_error_results_correctly(tmp_path: Path) -> None:
    provider = DisabledProvider()
    config = BenchmarkConfig(consistency_repeats=0)
    report = run_benchmark(provider, build_fixture_tasks(), config=config)
    target = tmp_path / "disabled-run.json"
    document = save_report(
        report, config, target, run_id=_FIXED_RUN_ID, created_at=_FIXED_CREATED_AT
    )
    reloaded = load_report(target)
    assert reloaded == document
    for entry in reloaded["task_results"]:
        assert entry["accepted"] is False
        assert entry["provider_error"] is not None
        assert "ProviderConnectionError" in entry["provider_error"]
    assert reloaded["aggregate"]["accepted_count"] == 0


def _hostile_factory(request: ProviderRequest) -> dict[str, object]:
    return {
        "schema_version": MODEL_OUTPUT_SCHEMA_VERSION,
        "narrative": "Hostile.",
        "provenance": Provenance.AI_INTERPRETATION.value,
        "override_findings": True,
    }


def test_save_report_persists_non_empty_rejection_reasons(tmp_path: Path) -> None:
    provider = MockProvider(response_factory=_hostile_factory)
    config = BenchmarkConfig(max_retries=0, consistency_repeats=0)
    tasks = build_fixture_tasks()[:1]
    report = run_benchmark(provider, tasks, config=config)
    target = tmp_path / "hostile-run.json"
    save_report(report, config, target, run_id=_FIXED_RUN_ID, created_at=_FIXED_CREATED_AT)
    reloaded = load_report(target)
    result_reasons = reloaded["task_results"][0]["rejection_reasons"]
    assert reloaded["task_results"][0]["accepted"] is False
    assert RejectionReason.UNSUPPORTED_CONTROL_FIELD.value in result_reasons


# ---------------------------------------------------------------------------
# AC-16: failure/boundary cases


def test_load_report_raises_file_not_found_for_missing_path(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_report(tmp_path / "does-not-exist.json")


def test_load_report_raises_value_error_for_non_object_top_level_json(tmp_path: Path) -> None:
    target = tmp_path / "not-an-object.json"
    target.write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(ValueError, match="expected a JSON object"):
        load_report(target)


def test_save_report_raises_for_a_nonexistent_parent_directory(tmp_path: Path) -> None:
    """Boundary: this function performs exactly the one explicit write
    it is told to — it does not silently create missing parent
    directories on the caller's behalf."""
    report, config = _sample_report_and_config()
    target = tmp_path / "missing-parent" / "run.json"
    with pytest.raises(OSError):
        save_report(report, config, target, run_id=_FIXED_RUN_ID, created_at=_FIXED_CREATED_AT)
