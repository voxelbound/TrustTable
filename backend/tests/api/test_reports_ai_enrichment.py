"""End-to-end proof that every real AI call site records itself and that a
report's AI-processing section reflects exactly that record (`EXP-01`
slice 4). The real routes, store and report code run; only the provider
`run_*` seams are replaced so each outcome can be forced."""

from __future__ import annotations

import time
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any

import pytest
from fastapi.testclient import TestClient

from trusttable_backend.api.v1 import analyses as analyses_module
from trusttable_backend.config import get_settings
from trusttable_backend.context_inference.ai_context import ContextInferenceResult
from trusttable_backend.explanation.deterministic import build_deterministic_explanation

_TERMINAL = {"completed", "failed", "cancelled"}
_ZERO = "No AI enrichment call is recorded as attempted."
_NOT_RECORDED = "Per-request AI enrichment is not recorded for this analysis."


@dataclass
class _Result:
    accepted: bool
    explanation: object = None
    canonical_value: str | None = None
    provider_error: str | None = None


@pytest.fixture
def ai_settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[Any]:
    def configure(provider: str, base_url: str | None = None) -> None:
        monkeypatch.setenv("LLM_PROVIDER", provider)
        monkeypatch.setenv("LLM_MODEL", "test-model")
        if base_url is not None:
            monkeypatch.setenv("LLM_BASE_URL", base_url)
        get_settings.cache_clear()

    yield configure
    get_settings.cache_clear()


def _completed(client: TestClient) -> str:
    analysis_id: str = client.post("/api/v1/demo/sales").json()["analysis"]["analysis_id"]
    deadline = time.monotonic() + 15.0
    while time.monotonic() < deadline:
        state = client.get(f"/api/v1/analyses/{analysis_id}/status").json()["state"]
        if state in _TERMINAL:
            assert state == "completed"
            return analysis_id
        time.sleep(0.01)
    raise AssertionError("analysis did not finish")


def _record(client: TestClient, analysis_id: str) -> Any:
    return client.app.state.analysis_store.get(analysis_id).ai_enrichment  # type: ignore[attr-defined]


def _counts(client: TestClient, analysis_id: str) -> tuple[int, int, int]:
    record = _record(client, analysis_id)
    return (record.accepted_count, record.rejected_count, record.provider_error_count)


def _explain(client: TestClient, analysis_id: str, finding: str = "0") -> dict[str, Any]:
    response = client.get(f"/api/v1/analyses/{analysis_id}/findings/{finding}/explanation")
    assert response.status_code == 200
    body: dict[str, Any] = response.json()
    return body


def _report_text(client: TestClient, analysis_id: str) -> str:
    created = client.post(f"/api/v1/analyses/{analysis_id}/reports")
    assert created.status_code == 201
    report_id = created.json()["report_id"]
    text: str = client.get(f"/api/v1/analyses/{analysis_id}/reports/{report_id}/download").text
    return text


def test_with_ai_disabled_nothing_is_recorded_and_the_report_says_no_call(
    client: TestClient,
) -> None:
    analysis_id = _completed(client)
    body = _explain(client, analysis_id)
    client.get(f"/api/v1/analyses/{analysis_id}/context")

    assert body["ai_call_status"] == "not_configured"
    assert _counts(client, analysis_id) == (0, 0, 0)
    text = _report_text(client, analysis_id)
    assert _ZERO in text
    assert "Calls attempted" not in text


def test_each_explanation_outcome_is_recorded_once(
    client: TestClient, ai_settings: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    ai_settings("mock")
    analysis_id = _completed(client)
    finding = client.app.state.analysis_store.get(analysis_id).findings[0]  # type: ignore[attr-defined]
    results = iter(
        [
            _Result(accepted=True, explanation=build_deterministic_explanation(finding)),
            _Result(accepted=False),
            _Result(accepted=False, provider_error="timeout"),
        ]
    )
    monkeypatch.setattr(analyses_module, "run_finding_explanation", lambda *a, **k: next(results))

    statuses = [_explain(client, analysis_id)["ai_call_status"] for _ in range(3)]

    assert statuses == ["attempted_accepted", "attempted_rejected", "attempted_provider_error"]
    assert _counts(client, analysis_id) == (1, 1, 1)
    record = _record(client, analysis_id)
    assert record.evidence_sent_to_model
    assert not record.confirmed_context_sent_to_model
    assert record.model_location.value == "local"


def test_an_exception_from_the_provider_is_a_provider_error_that_may_have_sent(
    client: TestClient, ai_settings: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    ai_settings("mock")
    analysis_id = _completed(client)

    def boom(*_: object, **__: object) -> object:
        raise RuntimeError("provider blew up")

    monkeypatch.setattr(analyses_module, "run_finding_explanation", boom)

    body = _explain(client, analysis_id)

    assert body["ai_call_status"] == "attempted_provider_error"
    assert _counts(client, analysis_id) == (0, 0, 1)
    assert _record(client, analysis_id).evidence_sent_to_model


def test_a_provider_that_cannot_be_built_records_an_error_and_nothing_sent(
    client: TestClient, ai_settings: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    ai_settings("mock")
    analysis_id = _completed(client)

    def cannot_build(*_: object, **__: object) -> object:
        raise ValueError("misconfigured")

    monkeypatch.setattr(analyses_module, "create_provider", cannot_build)

    body = _explain(client, analysis_id)

    assert body["ai_call_status"] == "attempted_provider_error"
    assert _counts(client, analysis_id) == (0, 0, 1)
    record = _record(client, analysis_id)
    assert not record.evidence_sent_to_model
    assert not record.confirmed_context_sent_to_model
    text = _report_text(client, analysis_id)
    assert "Bounded finding evidence was not sent to a model." in text


def test_confirmed_context_counts_as_sent_only_after_it_is_finalized(
    client: TestClient, ai_settings: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    ai_settings("mock")
    analysis_id = _completed(client)
    monkeypatch.setattr(
        analyses_module, "run_finding_explanation", lambda *a, **k: _Result(accepted=False)
    )
    client.get(f"/api/v1/analyses/{analysis_id}/context")
    _explain(client, analysis_id)
    assert not _record(client, analysis_id).confirmed_context_sent_to_model

    edited = client.put(
        f"/api/v1/analyses/{analysis_id}/context",
        json={"edits": {"row_grain": "One row per order"}, "expected_version": 1},
    )
    assert edited.status_code == 200
    version = edited.json()["context_version"]
    finalized = client.post(
        f"/api/v1/analyses/{analysis_id}/finalize", json={"expected_version": version}
    )
    assert finalized.status_code == 202
    _explain(client, analysis_id)

    assert _record(client, analysis_id).confirmed_context_sent_to_model
    assert "Confirmed context was sent to a model." in _report_text(client, analysis_id)


def test_context_inference_is_recorded_once_and_never_as_confirmed_context(
    client: TestClient, ai_settings: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    ai_settings("mock")
    analysis_id = _completed(client)
    monkeypatch.setattr(
        analyses_module,
        "run_context_inference",
        lambda *a, **k: ContextInferenceResult(
            accepted=False,
            hypothesis=None,
            rejection_reasons=(),
            provider_error=None,
            retries_used=0,
        ),
    )

    assert client.get(f"/api/v1/analyses/{analysis_id}/context").status_code == 200
    assert _counts(client, analysis_id) == (0, 1, 0)
    assert client.get(f"/api/v1/analyses/{analysis_id}/context").status_code == 200
    assert _counts(client, analysis_id) == (0, 1, 0)
    record = _record(client, analysis_id)
    assert record.evidence_sent_to_model
    assert not record.confirmed_context_sent_to_model


def test_a_context_provider_error_and_an_exception_are_both_provider_errors(
    client: TestClient, ai_settings: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    ai_settings("mock")
    first = _completed(client)
    second = _completed(client)
    monkeypatch.setattr(
        analyses_module,
        "run_context_inference",
        lambda *a, **k: ContextInferenceResult(
            accepted=False,
            hypothesis=None,
            rejection_reasons=(),
            provider_error="timeout",
            retries_used=0,
        ),
    )
    client.get(f"/api/v1/analyses/{first}/context")

    def boom(*_: object, **__: object) -> object:
        raise RuntimeError("x")

    monkeypatch.setattr(analyses_module, "run_context_inference", boom)
    client.get(f"/api/v1/analyses/{second}/context")

    assert _counts(client, first) == (0, 0, 1)
    assert _counts(client, second) == (0, 0, 1)


def test_every_response_that_reports_an_attempt_is_recorded_across_all_three_routes(
    client: TestClient, ai_settings: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    ai_settings("mock")
    analysis_id = _completed(client)
    monkeypatch.setattr(
        analyses_module, "run_finding_explanation", lambda *a, **k: _Result(accepted=False)
    )
    monkeypatch.setattr(
        analyses_module, "run_rule_generation", lambda *a, **k: _Result(accepted=False)
    )
    monkeypatch.setattr(
        analyses_module,
        "run_context_inference",
        lambda *a, **k: ContextInferenceResult(
            accepted=False,
            hypothesis=None,
            rejection_reasons=(),
            provider_error=None,
            retries_used=0,
        ),
    )
    findings = client.get(f"/api/v1/analyses/{analysis_id}/findings").json()["items"]
    attempts = 0
    rule_attempts = 0

    client.get(f"/api/v1/analyses/{analysis_id}/context")
    attempts += 1
    for item in findings:
        finding_id = item["finding_id"]
        assert _explain(client, analysis_id, finding_id)["ai_call_status"] != "not_configured"
        attempts += 1
        proposal = client.get(f"/api/v1/analyses/{analysis_id}/findings/{finding_id}/rule-proposal")
        assert proposal.status_code == 200
        if proposal.json()["ai_call_status"] != "not_configured":
            attempts += 1
            rule_attempts += 1

    assert rule_attempts > 0, "no finding exercised the AI rule-generation call site"
    assert sum(_counts(client, analysis_id)) == attempts


def test_an_older_analysis_without_a_record_reports_not_recorded_and_stays_so(
    client: TestClient, ai_settings: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    ai_settings("mock")
    analysis_id = _completed(client)
    store = client.app.state.analysis_store  # type: ignore[attr-defined]
    store.update_ai_enrichment(analysis_id, lambda _: None)
    monkeypatch.setattr(
        analyses_module, "run_finding_explanation", lambda *a, **k: _Result(accepted=False)
    )

    _explain(client, analysis_id)

    assert _record(client, analysis_id) is None
    text = _report_text(client, analysis_id)
    assert _NOT_RECORDED in text
    assert "makes no statement about whether it was used" in text
    assert _ZERO not in text


def test_a_report_states_counts_flags_location_and_protections(
    client: TestClient, ai_settings: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    ai_settings("mock")
    analysis_id = _completed(client)
    monkeypatch.setattr(
        analyses_module, "run_finding_explanation", lambda *a, **k: _Result(accepted=False)
    )
    _explain(client, analysis_id)
    _explain(client, analysis_id)

    text = _report_text(client, analysis_id)

    for expected in (
        "Calls attempted: 2.",
        "Output accepted: 0.",
        "Output rejected by validation: 2.",
        "Provider errors: 0.",
        "Bounded finding evidence was sent to a model.",
        "Confirmed context was not sent to a model.",
        "Model location: local.",
        "untrusted-data prompt envelope",
        "Model output is validated before use",
    ):
        assert expected in text
    assert _NOT_RECORDED not in text


def test_a_non_local_endpoint_is_reported_as_unknown_never_local(
    client: TestClient, ai_settings: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    ai_settings("llama_cpp", "http://203.0.113.9:8081")
    analysis_id = _completed(client)
    monkeypatch.setattr(
        analyses_module, "run_finding_explanation", lambda *a, **k: _Result(accepted=False)
    )
    _explain(client, analysis_id)

    text = _report_text(client, analysis_id)

    assert "Model location: unknown." in text
    assert "203.0.113.9" not in text
    assert "test-model" not in text


def test_a_created_report_is_not_changed_by_later_calls(
    client: TestClient, ai_settings: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    ai_settings("mock")
    analysis_id = _completed(client)
    created = client.post(f"/api/v1/analyses/{analysis_id}/reports").json()
    url = f"/api/v1/analyses/{analysis_id}/reports/{created['report_id']}/download"
    before = client.get(url).content
    monkeypatch.setattr(
        analyses_module, "run_finding_explanation", lambda *a, **k: _Result(accepted=False)
    )

    _explain(client, analysis_id)

    assert client.get(url).content == before
    assert _ZERO.encode() in before
