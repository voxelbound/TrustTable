"""Persisted, non-blocking AI enrichment of a finding (`UX-05b`, D-066 item 7).

The decisive proofs of the package's intent:

- the explanation route never calls a model (it answers at once with the
  deterministic content and overlays only a *current* saved result);
- start and status are short requests: the model call runs on a worker, so a
  slow model blocks neither the request nor the deterministic content;
- a saved result is bound to the finding, the confirmed-context version, the
  model identity and the prompt/contract version, and is *stale* (never shown
  as current) when any of them changes;
- nothing stays "preparing" after a restart, and a burst cannot exhaust the
  model;
- the saved output ends with its analysis.
"""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

import pytest
from fastapi.testclient import TestClient

import trusttable_backend.api.v1.analyses as analyses_module
from trusttable_backend.ai_provider.contract import (
    AIOperation,
    ProviderConnectionError,
    ProviderRequest,
    ProviderResponse,
)
from trusttable_backend.config import get_settings
from trusttable_backend.domain.finding_enrichment import EnrichmentReason, EnrichmentStatus
from trusttable_backend.enrichment.reconcile import reconcile_interrupted_enrichments
from trusttable_backend.main import create_app

from ..enrichment_support import (
    enrichment_url,
    explanation_url,
    request_enrichment,
    wait_for_enrichment,
)

_TERMINAL = {"completed", "failed", "cancelled"}
_STATUS_KEYS = {"finding_id", "state", "reason", "poll_interval_ms"}


class _CountingProvider:
    """An `AIProvider` double that counts calls, optionally holding each one
    until a test releases it, so "the call is still running" is a state a test
    controls rather than a race it hopes for."""

    def __init__(self, *, gate: threading.Event | None = None) -> None:
        self.calls = 0
        self.entered = threading.Event()
        self._gate = gate
        self._lock = threading.Lock()

    @property
    def provider_name(self) -> str:
        return "counting"

    def health_check(self) -> Any:
        raise NotImplementedError

    def complete(self, request: ProviderRequest) -> ProviderResponse:
        contract = request.output_contract
        if request.operation is not AIOperation.FINDING_EXPLANATION:
            # Context inference shares this provider; it is not what is counted.
            return ProviderResponse(
                raw_output={
                    "schema_version": "1",
                    "narrative": "A sales dataset.",
                    "provenance": "ai_interpretation",
                },
                provider_name=self.provider_name,
                model_identifier="counting-v1",
                duration_ms=1.0,
            )
        with self._lock:
            self.calls += 1
        self.entered.set()
        if self._gate is not None:
            assert self._gate.wait(timeout=20), "the test never released the model call"
        assert contract is not None and contract.mock_output_factory is not None
        return ProviderResponse(
            raw_output=contract.mock_output_factory(request.envelope),
            provider_name=self.provider_name,
            model_identifier="counting-v1",
            duration_ms=1.0,
        )


class _RejectingProvider:
    @property
    def provider_name(self) -> str:
        return "rejecting"

    def health_check(self) -> Any:
        raise NotImplementedError

    def complete(self, request: ProviderRequest) -> ProviderResponse:
        return ProviderResponse(
            raw_output={"schema_version": "1", "provenance": "ai_interpretation"},
            provider_name=self.provider_name,
            model_identifier="rejecting-v1",
            duration_ms=1.0,
        )


class _ErroringProvider:
    @property
    def provider_name(self) -> str:
        return "erroring"

    def health_check(self) -> Any:
        raise NotImplementedError

    def complete(self, request: ProviderRequest) -> ProviderResponse:
        raise ProviderConnectionError("simulated connection failure with SECRET-MARKER")


def _completed_demo(client: TestClient) -> str:
    response = client.post("/api/v1/demo/sales")
    assert response.status_code == 202
    analysis_id = str(response.json()["analysis"]["analysis_id"])
    deadline = time.monotonic() + 15.0
    while time.monotonic() < deadline:
        state = client.get(f"/api/v1/analyses/{analysis_id}/status").json()["state"]
        if state in _TERMINAL:
            assert state == "completed"
            return analysis_id
        time.sleep(0.01)
    raise AssertionError("the analysis did not finish")


def _configure(monkeypatch: pytest.MonkeyPatch, provider: Any, *, model: str = "model-a") -> None:
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("LLM_MODEL", model)
    get_settings.cache_clear()
    monkeypatch.setattr(analyses_module, "create_provider", lambda *a, **kw: provider)


def _status(client: TestClient, analysis_id: str, finding_id: str = "0") -> dict[str, Any]:
    response = client.get(enrichment_url(analysis_id, finding_id))
    assert response.status_code == 200
    body: dict[str, Any] = response.json()
    return body


def _explanation(client: TestClient, analysis_id: str, finding_id: str = "0") -> dict[str, Any]:
    response = client.get(explanation_url(analysis_id, finding_id))
    assert response.status_code == 200
    body: dict[str, Any] = response.json()
    return body


def _finalize_with_a_confirmed_field(client: TestClient, analysis_id: str) -> None:
    client.get(f"/api/v1/analyses/{analysis_id}/context")
    edited = client.put(
        f"/api/v1/analyses/{analysis_id}/context",
        json={"edits": {"row_grain": "One row per order"}, "expected_version": 1},
    )
    assert edited.status_code == 200
    finalized = client.post(
        f"/api/v1/analyses/{analysis_id}/finalize",
        json={"expected_version": edited.json()["context_version"]},
    )
    assert finalized.status_code == 202


# --- No model configured ----------------------------------------------------


def test_without_a_model_the_enrichment_is_unavailable_and_nothing_is_stored(
    client: TestClient,
) -> None:
    analysis_id = _completed_demo(client)

    started = client.post(enrichment_url(analysis_id, "0"))

    assert started.status_code == 202
    assert started.json() == {
        "finding_id": "0",
        "state": "unavailable",
        "reason": None,
        "poll_interval_ms": None,
    }
    assert _status(client, analysis_id)["state"] == "unavailable"
    assert client.app.state.enrichment_store.get(analysis_id, "0") is None  # type: ignore[attr-defined]
    assert _explanation(client, analysis_id)["ai_call_status"] == "not_configured"


# --- The explanation route never calls a model ------------------------------


def test_the_explanation_route_never_calls_the_model(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    analysis_id = _completed_demo(client)
    provider = _CountingProvider()
    _configure(monkeypatch, provider)

    body = _explanation(client, analysis_id)

    assert provider.calls == 0
    assert body["provenance"] == "deterministic_fallback"
    assert body["ai_call_status"] == "not_attempted"
    assert body["evidence_sent_to_model"] is False
    assert body["confirmed_context_sent_to_model"] is False
    assert body["narrative"] and body["business_impact"] and body["remediation"]
    assert _status(client, analysis_id)["state"] == "not_requested"
    assert provider.calls == 0


# --- Start, save, idempotence -----------------------------------------------


def test_a_requested_enrichment_is_saved_and_overlaid_on_the_explanation(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    analysis_id = _completed_demo(client)
    provider = _CountingProvider()
    _configure(monkeypatch, provider)
    deterministic = _explanation(client, analysis_id)

    final = request_enrichment(client, analysis_id, "0")

    assert final == {
        "finding_id": "0",
        "state": "ready",
        "reason": None,
        "poll_interval_ms": None,
    }
    assert provider.calls == 1
    body = _explanation(client, analysis_id)
    assert body["provenance"] == "ai_interpretation"
    assert body["ai_call_status"] == "attempted_accepted"
    assert body["evidence_sent_to_model"] is True
    assert body["narrative"] != deterministic["narrative"] or body["remediation"]
    # Reading it again, or asking again, never calls the model again.
    assert _explanation(client, analysis_id)["provenance"] == "ai_interpretation"
    again = client.post(enrichment_url(analysis_id, "0"))
    assert again.status_code == 202
    assert again.json()["state"] == "ready"
    assert provider.calls == 1


def test_a_saved_result_survives_a_restart(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    analysis_id = _completed_demo(client)
    provider = _CountingProvider()
    _configure(monkeypatch, provider)
    request_enrichment(client, analysis_id, "0")
    assert provider.calls == 1

    with TestClient(create_app()) as restarted:
        assert _status(restarted, analysis_id)["state"] == "ready"
        assert _explanation(restarted, analysis_id)["provenance"] == "ai_interpretation"
    assert provider.calls == 1


def test_the_enrichment_counters_record_each_attempt_once(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    analysis_id = _completed_demo(client)
    _configure(monkeypatch, _CountingProvider())

    request_enrichment(client, analysis_id, "0")
    client.post(enrichment_url(analysis_id, "0"))

    record = client.app.state.analysis_store.get(analysis_id).ai_enrichment  # type: ignore[attr-defined]
    assert (record.accepted_count, record.rejected_count, record.provider_error_count) == (1, 0, 0)


# --- Non-blocking -----------------------------------------------------------


def test_a_slow_model_blocks_neither_the_request_nor_the_deterministic_content(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    analysis_id = _completed_demo(client)
    gate = threading.Event()
    provider = _CountingProvider(gate=gate)
    _configure(monkeypatch, provider)

    try:
        started = client.post(enrichment_url(analysis_id, "0"))
        assert started.status_code == 202
        assert started.json()["state"] == "preparing"
        assert started.json()["poll_interval_ms"] == 1000
        assert provider.entered.wait(timeout=10), "the model call never started"

        # The model call is still running; both reads answer immediately.
        assert _status(client, analysis_id)["state"] == "preparing"
        body = _explanation(client, analysis_id)
        assert body["provenance"] == "deterministic_fallback"
        assert body["ai_call_status"] == "not_attempted"
        assert body["narrative"] and body["remediation"]
        # Asking again while it runs is idempotent: still one call.
        assert client.post(enrichment_url(analysis_id, "0")).json()["state"] == "preparing"
    finally:
        gate.set()
    assert wait_for_enrichment(client, analysis_id, "0")["state"] == "ready"
    assert provider.calls == 1


# --- Staleness --------------------------------------------------------------


def test_a_changed_confirmed_context_makes_the_saved_result_stale(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    analysis_id = _completed_demo(client)
    provider = _CountingProvider()
    _configure(monkeypatch, provider)
    request_enrichment(client, analysis_id, "0")
    assert _explanation(client, analysis_id)["provenance"] == "ai_interpretation"

    _finalize_with_a_confirmed_field(client, analysis_id)

    assert _status(client, analysis_id)["state"] == "stale"
    body = _explanation(client, analysis_id)
    assert body["provenance"] == "deterministic_fallback"  # never shown as current
    assert body["ai_call_status"] == "not_attempted"
    assert provider.calls == 1
    # Asking again enriches under the new binding, exactly once more.
    assert request_enrichment(client, analysis_id, "0")["state"] == "ready"
    assert provider.calls == 2
    assert _explanation(client, analysis_id)["confirmed_context_sent_to_model"] is True


def test_a_changed_model_makes_the_saved_result_stale(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    analysis_id = _completed_demo(client)
    provider = _CountingProvider()
    _configure(monkeypatch, provider, model="model-a")
    request_enrichment(client, analysis_id, "0")
    assert _status(client, analysis_id)["state"] == "ready"

    _configure(monkeypatch, provider, model="model-b")

    assert _status(client, analysis_id)["state"] == "stale"
    assert _explanation(client, analysis_id)["provenance"] == "deterministic_fallback"
    assert request_enrichment(client, analysis_id, "0")["state"] == "ready"
    assert provider.calls == 2


def test_a_changed_prompt_contract_version_makes_the_saved_result_stale(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    analysis_id = _completed_demo(client)
    _configure(monkeypatch, _CountingProvider())
    request_enrichment(client, analysis_id, "0")
    assert _status(client, analysis_id)["state"] == "ready"

    monkeypatch.setattr(
        "trusttable_backend.enrichment.binding.PROMPT_TEMPLATE_VERSION", "next-prompt-version"
    )

    assert _status(client, analysis_id)["state"] == "stale"
    assert _explanation(client, analysis_id)["provenance"] == "deterministic_fallback"


def test_disabling_the_model_after_a_result_reports_unavailable_not_the_saved_result(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    analysis_id = _completed_demo(client)
    _configure(monkeypatch, _CountingProvider())
    request_enrichment(client, analysis_id, "0")

    monkeypatch.setenv("LLM_PROVIDER", "disabled")
    get_settings.cache_clear()

    assert _status(client, analysis_id)["state"] == "unavailable"
    body = _explanation(client, analysis_id)
    assert body["provenance"] == "deterministic_fallback"
    assert body["ai_call_status"] == "not_configured"


def test_a_worker_started_under_an_old_binding_makes_no_model_call(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    analysis_id = _completed_demo(client)
    provider = _CountingProvider()
    _configure(monkeypatch, provider)
    enrichment_store = client.app.state.enrichment_store  # type: ignore[attr-defined]
    enrichment_store.begin(
        analysis_id,
        "0",
        binding_digest="an-older-binding",
        evidence_sent_to_model=True,
        confirmed_context_sent_to_model=False,
        max_preparing=8,
    )

    analyses_module._execute_finding_enrichment(
        client.app.state.analysis_store,  # type: ignore[attr-defined]
        enrichment_store,
        analysis_id,
        "0",
        "an-older-binding",
    )

    assert provider.calls == 0
    saved = enrichment_store.get(analysis_id, "0")
    assert saved.status is EnrichmentStatus.FAILED
    assert saved.reason is EnrichmentReason.SUPERSEDED
    assert saved.explanation is None


# --- Failure keeps the deterministic content --------------------------------


def test_a_rejected_result_is_failed_and_the_deterministic_content_stays(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    analysis_id = _completed_demo(client)
    _configure(monkeypatch, _RejectingProvider())

    final = request_enrichment(client, analysis_id, "0")

    assert final["state"] == "failed"
    assert final["reason"] == "rejected"
    body = _explanation(client, analysis_id)
    assert body["provenance"] == "deterministic_fallback"
    assert body["ai_call_status"] == "attempted_rejected"
    assert body["evidence_sent_to_model"] is True
    assert body["narrative"] and body["business_impact"] and body["remediation"]
    assert client.app.state.enrichment_store.get(analysis_id, "0").explanation is None  # type: ignore[attr-defined]


def test_a_provider_error_is_failed_without_leaking_it_and_can_be_retried(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    analysis_id = _completed_demo(client)
    _configure(monkeypatch, _ErroringProvider())
    caplog.set_level(logging.DEBUG)

    final = request_enrichment(client, analysis_id, "0")

    assert final["state"] == "failed"
    assert final["reason"] == "provider_error"
    assert "SECRET-MARKER" not in caplog.text
    for text in (
        client.get(enrichment_url(analysis_id, "0")).text,
        client.get(explanation_url(analysis_id, "0")).text,
    ):
        assert "SECRET-MARKER" not in text
        assert "simulated connection failure" not in text
    assert _explanation(client, analysis_id)["ai_call_status"] == "attempted_provider_error"

    # An explicit request starts it again, and a working model then succeeds.
    provider = _CountingProvider()
    _configure(monkeypatch, provider)
    assert request_enrichment(client, analysis_id, "0")["state"] == "ready"
    assert provider.calls == 1


def test_a_failed_enrichment_is_not_restarted_by_reading_it(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    analysis_id = _completed_demo(client)
    _configure(monkeypatch, _RejectingProvider())
    request_enrichment(client, analysis_id, "0")

    for _ in range(3):
        assert _status(client, analysis_id)["state"] == "failed"
        _explanation(client, analysis_id)

    record = client.app.state.analysis_store.get(analysis_id).ai_enrichment  # type: ignore[attr-defined]
    assert record.rejected_count == 1


def test_a_corrupted_saved_result_is_never_served(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlalchemy import update

    from trusttable_backend.persistence.models import FindingEnrichmentRecord

    analysis_id = _completed_demo(client)
    _configure(monkeypatch, _CountingProvider())
    request_enrichment(client, analysis_id, "0")
    engine = client.app.state.analysis_engine  # type: ignore[attr-defined]
    with engine.begin() as connection:
        connection.execute(
            update(FindingEnrichmentRecord).values(result_json={"__t": "dataclass", "m": "os"})
        )

    assert _status(client, analysis_id)["state"] == "failed"
    assert _status(client, analysis_id)["reason"] == "unreadable"
    assert _explanation(client, analysis_id)["provenance"] == "deterministic_fallback"


# --- Bounded start ----------------------------------------------------------


def test_a_burst_past_the_bound_is_refused_as_busy_not_queued(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    analysis_id = _completed_demo(client)
    gate = threading.Event()
    provider = _CountingProvider(gate=gate)
    _configure(monkeypatch, provider)
    client.app.state.enrichment_pool.max_preparing = 1  # type: ignore[attr-defined]

    try:
        assert client.post(enrichment_url(analysis_id, "0")).json()["state"] == "preparing"
        refused = client.post(enrichment_url(analysis_id, "1"))

        assert refused.status_code == 429
        assert refused.json()["error"]["code"] == "AI_ENRICHMENT_BUSY"
        assert _status(client, analysis_id, "1")["state"] == "not_requested"
        # The one already running is unaffected and still idempotent.
        assert client.post(enrichment_url(analysis_id, "0")).json()["state"] == "preparing"
    finally:
        gate.set()
    assert wait_for_enrichment(client, analysis_id, "0")["state"] == "ready"
    # The slot is free again.
    assert request_enrichment(client, analysis_id, "1")["state"] == "ready"


# --- Restart ----------------------------------------------------------------


def test_a_restart_never_leaves_an_enrichment_preparing(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    analysis_id = _completed_demo(client)
    _configure(monkeypatch, _CountingProvider())
    store = client.app.state.enrichment_store  # type: ignore[attr-defined]
    # A row a previous process left `preparing` (its worker died with it).
    store.begin(
        analysis_id,
        "0",
        binding_digest=analyses_module._enrichment_binding(
            client.app.state.analysis_store.get(analysis_id),  # type: ignore[attr-defined]
            "0",
            get_settings(),
        ),
        evidence_sent_to_model=True,
        confirmed_context_sent_to_model=False,
        max_preparing=8,
    )
    assert _status(client, analysis_id)["state"] == "preparing"

    with TestClient(create_app()) as restarted:
        status = _status(restarted, analysis_id)
        assert status["state"] == "failed"
        assert status["reason"] == "interrupted"
        assert restarted.app.state.enrichment_store.count_preparing() == 0  # type: ignore[attr-defined]
        record = restarted.app.state.analysis_store.get(analysis_id).ai_enrichment  # type: ignore[attr-defined]
        # The attempt it may have made is counted: evidence may have been sent.
        assert record.provider_error_count == 1
        assert request_enrichment(restarted, analysis_id, "0")["state"] == "ready"


def test_reconciliation_fails_every_preparing_row_and_nothing_else(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    analysis_id = _completed_demo(client)
    _configure(monkeypatch, _CountingProvider())
    request_enrichment(client, analysis_id, "0")
    store = client.app.state.enrichment_store  # type: ignore[attr-defined]
    analysis_store = client.app.state.analysis_store  # type: ignore[attr-defined]
    store.begin(
        analysis_id,
        "1",
        binding_digest="b",
        evidence_sent_to_model=True,
        confirmed_context_sent_to_model=False,
        max_preparing=8,
    )

    failed = reconcile_interrupted_enrichments(store, analysis_store, get_settings())

    assert failed == 1
    assert store.get(analysis_id, "0").status is EnrichmentStatus.READY
    assert store.get(analysis_id, "1").status is EnrichmentStatus.FAILED
    assert reconcile_interrupted_enrichments(store, analysis_store, get_settings()) == 0


# --- Retention --------------------------------------------------------------


def test_the_saved_output_is_deleted_with_its_analysis(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    analysis_id = _completed_demo(client)
    _configure(monkeypatch, _CountingProvider())
    request_enrichment(client, analysis_id, "0")
    request_enrichment(client, analysis_id, "1")
    store = client.app.state.enrichment_store  # type: ignore[attr-defined]
    assert store.get(analysis_id, "0") is not None

    deleted = client.delete(f"/api/v1/analyses/{analysis_id}")

    assert deleted.status_code == 204
    assert store.get(analysis_id, "0") is None
    assert store.get(analysis_id, "1") is None
    assert client.get(enrichment_url(analysis_id, "0")).status_code == 404


def test_deleting_one_analysis_keeps_another_analysis_enrichment(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = _completed_demo(client)
    second = _completed_demo(client)
    _configure(monkeypatch, _CountingProvider())
    request_enrichment(client, first, "0")
    request_enrichment(client, second, "0")

    client.delete(f"/api/v1/analyses/{first}")

    assert _status(client, second)["state"] == "ready"


def test_an_enrichment_finishing_after_its_analysis_was_deleted_stores_nothing(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    analysis_id = _completed_demo(client)
    gate = threading.Event()
    provider = _CountingProvider(gate=gate)
    _configure(monkeypatch, provider)
    store = client.app.state.enrichment_store  # type: ignore[attr-defined]
    try:
        client.post(enrichment_url(analysis_id, "0"))
        assert provider.entered.wait(timeout=10)
        assert client.delete(f"/api/v1/analyses/{analysis_id}").status_code == 204
    finally:
        gate.set()
    client.app.state.enrichment_pool.shutdown(wait=True)  # type: ignore[attr-defined]

    assert store.get(analysis_id, "0") is None
    assert store.count_preparing() == 0


# --- Contract ---------------------------------------------------------------


def test_the_status_carries_only_the_documented_fields(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    analysis_id = _completed_demo(client)
    _configure(monkeypatch, _CountingProvider(), model=r"C:\Models\private\model-a.gguf")

    request_enrichment(client, analysis_id, "0")
    text = client.get(enrichment_url(analysis_id, "0")).text

    assert set(_status(client, analysis_id)) == _STATUS_KEYS
    assert "private" not in text
    assert ".gguf" not in text


def test_unknown_analysis_and_unknown_finding_are_structured_404s(client: TestClient) -> None:
    analysis_id = _completed_demo(client)

    for method in (client.get, client.post):
        missing_analysis = method(enrichment_url("does-not-exist", "0"))
        assert missing_analysis.status_code == 404
        assert missing_analysis.json()["error"]["code"] == "ANALYSIS_NOT_FOUND"
        missing_finding = method(enrichment_url(analysis_id, "99999"))
        assert missing_finding.status_code == 404
        assert missing_finding.json()["error"]["code"] == "FINDING_NOT_FOUND"
