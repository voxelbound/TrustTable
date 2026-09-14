"""Tests for durable benchmark-result persistence (`AI-06`, r2/r3).

Covers this package's r2 acceptance criteria AC-12..AC-16 (round-trip
fidelity, deterministic/stable serialization, schema shape, relevant
failure/boundary cases) and r3 acceptance criteria AC-18..AC-22
(explicit candidate metadata and optional resource observations).
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from trusttable_backend.ai_benchmark.fixtures import build_fixture_tasks
from trusttable_backend.ai_benchmark.metrics import BenchmarkReport
from trusttable_backend.ai_benchmark.persistence import (
    BENCHMARK_RESULT_SCHEMA_VERSION,
    CandidateMetadata,
    ResourceObservations,
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

_CANDIDATE = CandidateMetadata(
    runtime_identifier="mock-runtime",
    model_identifier="mock-model",
    hardware_profile="baseline",
    quantization_identifier="Q4_K_M",
)


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
    document = report_to_dict(
        report, config, run_id=_FIXED_RUN_ID, created_at=_FIXED_CREATED_AT, candidate=_CANDIDATE
    )
    assert set(document.keys()) == {
        "schema_version",
        "run_id",
        "created_at",
        "fixture_set_version",
        "provider_name",
        "model_identifier",
        "hardware_profile",
        "candidate",
        "resource_observations",
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
    document = report_to_dict(
        report, config, run_id=_FIXED_RUN_ID, created_at=_FIXED_CREATED_AT, candidate=_CANDIDATE
    )
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
    document = report_to_dict(
        report, config, run_id=_FIXED_RUN_ID, created_at=_FIXED_CREATED_AT, candidate=_CANDIDATE
    )
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
    document = report_to_dict(
        report, config, run_id=_FIXED_RUN_ID, created_at=_FIXED_CREATED_AT, candidate=_CANDIDATE
    )
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
        report,
        config,
        target,
        candidate=_CANDIDATE,
        run_id=_FIXED_RUN_ID,
        created_at=_FIXED_CREATED_AT,
    )
    loaded = load_report(target)
    assert loaded == written
    assert loaded == report_to_dict(
        report, config, run_id=_FIXED_RUN_ID, created_at=_FIXED_CREATED_AT, candidate=_CANDIDATE
    )


def test_save_report_accepts_str_path_as_well_as_path_object(tmp_path: Path) -> None:
    report, config = _sample_report_and_config()
    target = tmp_path / "run-str.json"
    save_report(
        report,
        config,
        str(target),
        candidate=_CANDIDATE,
        run_id=_FIXED_RUN_ID,
        created_at=_FIXED_CREATED_AT,
    )
    assert target.exists()
    loaded = load_report(str(target))
    assert loaded["run_id"] == _FIXED_RUN_ID


# ---------------------------------------------------------------------------
# AC-14: deterministic/stable serialization


def test_save_report_produces_byte_identical_output_for_identical_input(tmp_path: Path) -> None:
    report, config = _sample_report_and_config()
    first_path = tmp_path / "first.json"
    second_path = tmp_path / "second.json"
    save_report(
        report,
        config,
        first_path,
        candidate=_CANDIDATE,
        run_id=_FIXED_RUN_ID,
        created_at=_FIXED_CREATED_AT,
    )
    save_report(
        report,
        config,
        second_path,
        candidate=_CANDIDATE,
        run_id=_FIXED_RUN_ID,
        created_at=_FIXED_CREATED_AT,
    )
    assert first_path.read_text(encoding="utf-8") == second_path.read_text(encoding="utf-8")


def test_save_report_default_run_id_and_created_at_are_distinct_across_calls(
    tmp_path: Path,
) -> None:
    """Boundary: when not supplied, `run_id`/`created_at` are still
    populated (not left blank/null) and vary call to call, so two
    default-invoked runs remain distinguishable."""
    report, config = _sample_report_and_config()
    first = save_report(report, config, tmp_path / "a.json", candidate=_CANDIDATE)
    second = save_report(report, config, tmp_path / "b.json", candidate=_CANDIDATE)
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
        report,
        config,
        target,
        candidate=_CANDIDATE,
        run_id=_FIXED_RUN_ID,
        created_at=_FIXED_CREATED_AT,
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
    save_report(
        report,
        config,
        target,
        candidate=_CANDIDATE,
        run_id=_FIXED_RUN_ID,
        created_at=_FIXED_CREATED_AT,
    )
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
        save_report(
            report,
            config,
            target,
            candidate=_CANDIDATE,
            run_id=_FIXED_RUN_ID,
            created_at=_FIXED_CREATED_AT,
        )


# ---------------------------------------------------------------------------
# AC-18 (r3): CandidateMetadata — construction, required fields, nullable
# quantization


def test_candidate_metadata_constructs_with_all_fields() -> None:
    candidate = CandidateMetadata(
        runtime_identifier="ollama",
        model_identifier="llama-3.1-8b-instruct",
        hardware_profile="accelerated",
        quantization_identifier="Q4_K_M",
    )
    assert candidate.runtime_identifier == "ollama"
    assert candidate.model_identifier == "llama-3.1-8b-instruct"
    assert candidate.hardware_profile == "accelerated"
    assert candidate.quantization_identifier == "Q4_K_M"


def test_candidate_metadata_quantization_identifier_defaults_to_none() -> None:
    """Boundary: an unknown/not-applicable quantization is the one
    field this metadata allows to be nullable."""
    candidate = CandidateMetadata(
        runtime_identifier="llama.cpp", model_identifier="mistral-7b", hardware_profile="baseline"
    )
    assert candidate.quantization_identifier is None


@pytest.mark.parametrize(
    "field",
    ["runtime_identifier", "model_identifier", "hardware_profile"],
)
def test_candidate_metadata_rejects_empty_required_fields(field: str) -> None:
    fields: dict[str, object] = {
        "runtime_identifier": "ollama",
        "model_identifier": "llama-3.1-8b-instruct",
        "hardware_profile": "baseline",
    }
    fields[field] = ""
    with pytest.raises(ValueError, match=field):
        CandidateMetadata(**fields)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# AC-19 (r3): ResourceObservations — construction, optionality, boundaries


def test_resource_observations_defaults_to_both_none() -> None:
    observations = ResourceObservations()
    assert observations.peak_rss_mb is None
    assert observations.peak_vram_mb is None


def test_resource_observations_accepts_populated_values() -> None:
    observations = ResourceObservations(peak_rss_mb=8192.0, peak_vram_mb=6144.5)
    assert observations.peak_rss_mb == 8192.0
    assert observations.peak_vram_mb == 6144.5


def test_resource_observations_accepts_zero_boundary() -> None:
    observations = ResourceObservations(peak_rss_mb=0.0, peak_vram_mb=0.0)
    assert observations.peak_rss_mb == 0.0
    assert observations.peak_vram_mb == 0.0


def test_resource_observations_rejects_negative_peak_rss_mb() -> None:
    with pytest.raises(ValueError, match="peak_rss_mb"):
        ResourceObservations(peak_rss_mb=-1.0)


def test_resource_observations_rejects_negative_peak_vram_mb() -> None:
    with pytest.raises(ValueError, match="peak_vram_mb"):
        ResourceObservations(peak_vram_mb=-1.0)


# ---------------------------------------------------------------------------
# AC-20 (r3): candidate metadata persisted and round-tripped, including
# null/unknown quantization


def test_report_to_dict_candidate_section_matches_supplied_candidate() -> None:
    report, config = _sample_report_and_config()
    document = report_to_dict(
        report, config, run_id=_FIXED_RUN_ID, created_at=_FIXED_CREATED_AT, candidate=_CANDIDATE
    )
    assert document["candidate"] == {
        "runtime_identifier": "mock-runtime",
        "model_identifier": "mock-model",
        "quantization_identifier": "Q4_K_M",
        "hardware_profile": "baseline",
    }


def test_save_report_round_trips_candidate_with_null_quantization(tmp_path: Path) -> None:
    report, config = _sample_report_and_config()
    candidate = CandidateMetadata(
        runtime_identifier="llama.cpp", model_identifier="mistral-7b", hardware_profile="baseline"
    )
    target = tmp_path / "unquantized-run.json"
    written = save_report(
        report,
        config,
        target,
        candidate=candidate,
        run_id=_FIXED_RUN_ID,
        created_at=_FIXED_CREATED_AT,
    )
    assert written["candidate"]["quantization_identifier"] is None
    reloaded = load_report(target)
    assert reloaded["candidate"]["quantization_identifier"] is None
    assert reloaded == written


# ---------------------------------------------------------------------------
# AC-21 (r3): resource observations — absent vs. populated, round-tripped


def test_save_report_resource_observations_absent_by_default(tmp_path: Path) -> None:
    report, config = _sample_report_and_config()
    target = tmp_path / "no-observations.json"
    written = save_report(
        report,
        config,
        target,
        candidate=_CANDIDATE,
        run_id=_FIXED_RUN_ID,
        created_at=_FIXED_CREATED_AT,
    )
    assert written["resource_observations"] is None
    reloaded = load_report(target)
    assert reloaded["resource_observations"] is None


def test_save_report_resource_observations_populated_round_trips(tmp_path: Path) -> None:
    report, config = _sample_report_and_config()
    observations = ResourceObservations(peak_rss_mb=12000.5, peak_vram_mb=9000.25)
    target = tmp_path / "with-observations.json"
    written = save_report(
        report,
        config,
        target,
        candidate=_CANDIDATE,
        resource_observations=observations,
        run_id=_FIXED_RUN_ID,
        created_at=_FIXED_CREATED_AT,
    )
    assert written["resource_observations"] == {"peak_rss_mb": 12000.5, "peak_vram_mb": 9000.25}
    reloaded = load_report(target)
    assert reloaded == written


def test_save_report_resource_observations_partially_populated(tmp_path: Path) -> None:
    """Boundary: one field observed, the other legitimately not."""
    report, config = _sample_report_and_config()
    observations = ResourceObservations(peak_rss_mb=4096.0)
    target = tmp_path / "partial-observations.json"
    written = save_report(
        report,
        config,
        target,
        candidate=_CANDIDATE,
        resource_observations=observations,
        run_id=_FIXED_RUN_ID,
        created_at=_FIXED_CREATED_AT,
    )
    assert written["resource_observations"] == {"peak_rss_mb": 4096.0, "peak_vram_mb": None}


# ---------------------------------------------------------------------------
# AC-22 (r3): deterministic serialization is preserved with the new fields


def test_save_report_with_candidate_and_observations_is_byte_identical_for_identical_input(
    tmp_path: Path,
) -> None:
    report, config = _sample_report_and_config()
    observations = ResourceObservations(peak_rss_mb=1024.0, peak_vram_mb=2048.0)
    first_path = tmp_path / "first.json"
    second_path = tmp_path / "second.json"
    save_report(
        report,
        config,
        first_path,
        candidate=_CANDIDATE,
        resource_observations=observations,
        run_id=_FIXED_RUN_ID,
        created_at=_FIXED_CREATED_AT,
    )
    save_report(
        report,
        config,
        second_path,
        candidate=_CANDIDATE,
        resource_observations=observations,
        run_id=_FIXED_RUN_ID,
        created_at=_FIXED_CREATED_AT,
    )
    assert first_path.read_text(encoding="utf-8") == second_path.read_text(encoding="utf-8")


def test_schema_version_bumped_for_r3_document_shape() -> None:
    """Boundary: the r3 document shape (candidate/resource_observations
    added) is a distinct, distinguishable schema version from r2's."""
    assert BENCHMARK_RESULT_SCHEMA_VERSION == "2"
