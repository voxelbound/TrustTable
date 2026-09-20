"""Persistence and privacy tests for the qualification result document
(`REL-02`, `docs/decision-log.md` D-043).

The document is what a person compares weeks later, and it is a file that may
be shared. So besides shape, determinism and round-tripping, these tests prove
what it must never contain: model output, exception message text, dataset
values, the server URL, or an absolute host path.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest

from trusttable_backend.ai_benchmark.persistence import CandidateMetadata, ResourceObservations
from trusttable_backend.ai_benchmark.qualification import (
    Condition,
    QualificationConfig,
    QualificationReport,
    QualificationSuite,
    build_qualification_suite,
    run_qualification,
)
from trusttable_backend.ai_benchmark.qualification_cli import provider_from_settings
from trusttable_backend.ai_benchmark.qualification_persistence import (
    QUALIFICATION_HARNESS,
    QUALIFICATION_RESULT_SCHEMA_VERSION,
    load_qualification_report,
    qualification_report_to_dict,
    save_qualification_report,
)
from trusttable_backend.ai_provider.contract import (
    ProviderInvalidResponseError,
    ProviderRequest,
    ProviderResponse,
)
from trusttable_backend.config import Settings

from .test_qualification import (
    INVALID_OUTPUT,
    ManualClock,
    ScriptedProvider,
    accepted_response,
    rejected_response,
)
from .test_qualification_route_fidelity import StubServer, chat_response, make_factory

_FIXED_TIME = datetime(2026, 9, 20, 12, 0, 0, tzinfo=UTC)
_CANDIDATE = CandidateMetadata(
    runtime_identifier="llama.cpp",
    model_identifier="Qwen3.5-4B-Q4_K_M.gguf",
    hardware_profile="baseline",
    quantization_identifier="Q4_K_M",
)


@pytest.fixture(scope="module")
def suite() -> QualificationSuite:
    return build_qualification_suite()


@pytest.fixture
def report(suite: QualificationSuite) -> QualificationReport:
    clock = ManualClock()

    def mixed(request: ProviderRequest) -> ProviderResponse:
        clock.advance(1.5)
        if "duplicate" in request.envelope.task:
            raise ProviderInvalidResponseError("SENTINEL-EXCEPTION-TEXT")
        if "missing" in request.envelope.task:
            return rejected_response(request)
        return accepted_response(request)

    return run_qualification(
        ScriptedProvider(mixed),
        suite,
        config=QualificationConfig(configured_timeout_seconds=120.0, notes="unit test"),
        clock=clock,
    )


# ---------------------------------------------------------------------------
# Shape and content
# ---------------------------------------------------------------------------


def test_document_shape_and_header(report: QualificationReport) -> None:
    document = qualification_report_to_dict(
        report, run_id="run-1", created_at=_FIXED_TIME, candidate=_CANDIDATE
    )

    assert set(document) == {
        "schema_version",
        "harness",
        "run_id",
        "created_at",
        "case_set_version",
        "scope",
        "conditions",
        "provider_name",
        "model_identifier",
        "server_available_at_start",
        "candidate",
        "resource_observations",
        "config",
        "case_results",
        "aggregate",
        "aggregate_by_condition",
    }
    assert document["schema_version"] == QUALIFICATION_RESULT_SCHEMA_VERSION == "1"
    assert document["harness"] == QUALIFICATION_HARNESS == "finding_analysis_qualification"
    assert document["run_id"] == "run-1"
    assert document["created_at"] == _FIXED_TIME.isoformat()
    assert document["conditions"] == ["evidence_only", "confirmed_context"]
    assert document["config"] == {
        "max_retries": 2,
        "configured_timeout_seconds": 120.0,
        "notes": "unit test",
    }
    assert json.loads(json.dumps(document)) == document  # plain JSON-native types only


def test_case_results_and_aggregates_carry_the_reports_own_values(
    report: QualificationReport,
) -> None:
    document = qualification_report_to_dict(
        report, run_id="r", created_at=_FIXED_TIME, candidate=_CANDIDATE
    )

    assert len(document["case_results"]) == len(report.case_results)
    for entry, result in zip(document["case_results"], report.case_results, strict=True):
        assert entry["case_id"] == result.case_id
        assert entry["condition"] == result.condition.value
        assert entry["outcome"] == result.outcome.value
        assert entry["product_ai_call_status"] == result.product_ai_call_status
        assert entry["retries_used"] == result.retries_used
        assert entry["rejection_reasons"] == [r.value for r in result.rejection_reasons]
        assert entry["provider_error_kind"] == result.provider_error_kind
        assert entry["total_duration_ms"] == result.total_duration_ms
        assert entry["attempts"] == [
            {"duration_ms": a.duration_ms, "error_kind": a.error_kind} for a in result.attempts
        ]
        assert entry["confirmed_context_sent"] is result.confirmed_context_sent
    aggregate = document["aggregate"]
    assert aggregate["case_count"] == report.aggregate.case_count
    assert aggregate["fill_rate"] == report.aggregate.fill_rate
    assert aggregate["outcome_counts"] == dict(report.aggregate.outcome_counts)
    assert aggregate["case_latency_ms"]["p95"] == report.aggregate.case_latency.p95_ms
    assert set(document["aggregate_by_condition"]) == {"evidence_only", "confirmed_context"}


def test_candidate_identity_is_explicit_and_quantization_may_be_absent(
    report: QualificationReport,
) -> None:
    with_quant = qualification_report_to_dict(
        report, run_id="r", created_at=_FIXED_TIME, candidate=_CANDIDATE
    )
    assert with_quant["candidate"] == {
        "runtime_identifier": "llama.cpp",
        "model_identifier": "Qwen3.5-4B-Q4_K_M.gguf",
        "quantization_identifier": "Q4_K_M",
        "hardware_profile": "baseline",
    }
    without = qualification_report_to_dict(
        report,
        run_id="r",
        created_at=_FIXED_TIME,
        candidate=CandidateMetadata("llama.cpp", "m.gguf", "baseline"),
    )
    assert without["candidate"]["quantization_identifier"] is None


def test_resource_observations_are_null_unless_supplied_and_may_be_partial(
    report: QualificationReport,
) -> None:
    def doc(observations: ResourceObservations | None) -> dict[str, Any]:
        return qualification_report_to_dict(
            report,
            run_id="r",
            created_at=_FIXED_TIME,
            candidate=_CANDIDATE,
            resource_observations=observations,
        )

    assert doc(None)["resource_observations"] is None  # not observed, not zero
    assert doc(ResourceObservations(peak_rss_mb=5120.0, peak_vram_mb=0.0))[
        "resource_observations"
    ] == {"peak_rss_mb": 5120.0, "peak_vram_mb": 0.0}
    assert doc(ResourceObservations(peak_rss_mb=5120.0))["resource_observations"] == {
        "peak_rss_mb": 5120.0,
        "peak_vram_mb": None,
    }


# ---------------------------------------------------------------------------
# Files
# ---------------------------------------------------------------------------


def test_save_and_load_round_trip_and_are_deterministic(
    report: QualificationReport, tmp_path: Path
) -> None:
    first = tmp_path / "a.json"
    second = tmp_path / "b.json"
    written = save_qualification_report(
        report, first, candidate=_CANDIDATE, run_id="fixed", created_at=_FIXED_TIME
    )
    save_qualification_report(
        report, second, candidate=_CANDIDATE, run_id="fixed", created_at=_FIXED_TIME
    )

    assert load_qualification_report(first) == written
    assert first.read_bytes() == second.read_bytes()  # sorted keys, byte-identical
    text = first.read_text(encoding="utf-8")
    assert text.endswith("\n")
    assert json.loads(text)["run_id"] == "fixed"


def test_default_run_id_and_time_are_populated_and_distinct_per_call(
    report: QualificationReport, tmp_path: Path
) -> None:
    one = save_qualification_report(report, tmp_path / "1.json", candidate=_CANDIDATE)
    two = save_qualification_report(report, tmp_path / "2.json", candidate=_CANDIDATE)
    assert one["run_id"] and two["run_id"] and one["run_id"] != two["run_id"]
    assert datetime.fromisoformat(one["created_at"]).tzinfo is not None


def test_load_failure_modes(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        load_qualification_report(tmp_path / "missing.json")
    array = tmp_path / "array.json"
    array.write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(ValueError, match="JSON object"):
        load_qualification_report(array)


def test_saving_into_a_missing_directory_fails_and_creates_nothing(
    report: QualificationReport, tmp_path: Path
) -> None:
    target = tmp_path / "no-such-dir" / "result.json"
    with pytest.raises(OSError):
        save_qualification_report(report, target, candidate=_CANDIDATE)
    assert not (tmp_path / "no-such-dir").exists()


# ---------------------------------------------------------------------------
# Privacy: what the document must never contain
# ---------------------------------------------------------------------------

_HOSTILE_IDENTIFIERS = [
    r"C:\Users\someone\models\model.gguf",
    r"\\fileserver\share\model.gguf",
    "/home/someone/models/model.gguf",
    "~/models/model.gguf",
    "file:///opt/models/model.gguf",
    "https://user:secret@models.example.com/models/model.gguf",
]


@pytest.mark.parametrize("identifier", _HOSTILE_IDENTIFIERS)
def test_a_hostile_model_identifier_is_reduced_to_a_file_name_everywhere(
    suite: QualificationSuite, identifier: str, tmp_path: Path
) -> None:
    provider = ScriptedProvider(accepted_response, model_identifier=identifier)
    report = run_qualification(
        provider, suite, config=QualificationConfig(conditions=(Condition.EVIDENCE_ONLY,))
    )
    candidate = CandidateMetadata("llama.cpp", identifier, "baseline")
    target = tmp_path / "result.json"
    document = save_qualification_report(report, target, candidate=candidate)

    assert document["model_identifier"] == "model.gguf"
    assert document["candidate"]["model_identifier"] == "model.gguf"
    text = target.read_text(encoding="utf-8")
    for fragment in ("someone", "fileserver", "/opt/", "secret", "models.example.com", "\\\\"):
        assert fragment not in text, fragment


def test_no_model_output_exception_text_url_or_dataset_value_is_persisted(
    suite: QualificationSuite, tmp_path: Path
) -> None:
    """Drive the real provider over a stub whose answers carry sentinels: model
    text in a rejected answer, text in a failing response, and the injected
    demo prompt-injection phrase. None may reach the document."""
    model_sentinel = "SENTINEL-MODEL-OUTPUT-7Q"
    error_sentinel = "SENTINEL-ERROR-BODY-9Z"

    def respond(payload: dict[str, Any], body: dict[str, Any]) -> httpx.Response:
        if "duplicate" in body["messages"][0]["content"] + json.dumps(payload):
            return httpx.Response(500, text=error_sentinel)
        return chat_response(json.dumps({**INVALID_OUTPUT, "explanation": model_sentinel}))

    settings = Settings(
        llm_provider="llama_cpp",
        llm_base_url="http://user:secret@llama.test:8081",
        llm_model=r"C:\models\Qwen3.5-4B-Q4_K_M.gguf",
        llm_timeout_seconds=90,
    )
    provider = provider_from_settings(settings, factory=make_factory(StubServer(respond), []))
    report = run_qualification(provider, suite)
    target = tmp_path / "result.json"
    save_qualification_report(
        report,
        target,
        candidate=CandidateMetadata("llama.cpp", settings.llm_model, "baseline"),
    )

    text = target.read_text(encoding="utf-8")
    lowered = text.lower()
    for forbidden in (
        model_sentinel,
        error_sentinel,
        "secret",
        "llama.test",
        "c:\\",
        "/home/",
        "ignore all previous instructions",  # the demo dataset's injected phrase
        "boom",
    ):
        assert forbidden.lower() not in lowered, forbidden
    # What it does carry is class names and reason codes.
    assert "ProviderInvalidResponseError" in text
    assert "fell_back_rejected" in text
