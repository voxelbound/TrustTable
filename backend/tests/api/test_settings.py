"""The Settings API and the AI consumers that follow it (`UX-08a`, D-066 item 5).

The decisive proofs of the package's intent:

- the effective value is an explicit deployment override, then the stored value,
  then off; an override (environment or `.env`) is read-only and a stored value
  never exceeds it;
- the allowlist is closed: unknown keys, wrong types and stale versions change
  nothing;
- AI status, the explanation overlay, enrichment and rule proposal follow the
  effective value on the next request, and a stored "on" with nothing to run is
  reported as on-but-unavailable, never as an error;
- a runtime address or model path appears only in the Advanced response.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

import trusttable_backend.api.v1.analyses as analyses_module
from trusttable_backend.ai_provider.contract import (
    AIOperation,
    ProviderRequest,
    ProviderResponse,
)
from trusttable_backend.config import Settings, get_settings

from ..enrichment_support import enrichment_url, explanation_url, request_enrichment

_SETTINGS = "/api/v1/settings"
_SECRET_URL = "http://svc-user:hunter2-secret@localhost:8081/v1/private-path?token=abc123"
_REMOTE_URL = "http://svc-user:hunter2-secret@10.9.8.7:8081/v1/private-path?token=abc123"
_MODEL_PATH = "/home/secret-user/models/Qwen3.5-4B-Q4_K_M.gguf"
_LEAKS = ("hunter2", "svc-user", "abc123", "private-path", "10.9.8.7", "secret-user", "/home")


class _CountingProvider:
    def __init__(self) -> None:
        self.calls = 0
        self._lock = threading.Lock()

    @property
    def provider_name(self) -> str:
        return "counting"

    def health_check(self) -> Any:
        raise NotImplementedError

    def complete(self, request: ProviderRequest) -> ProviderResponse:
        contract = request.output_contract
        if request.operation is AIOperation.FINDING_EXPLANATION:
            with self._lock:
                self.calls += 1
        assert contract is not None and contract.mock_output_factory is not None
        return ProviderResponse(
            raw_output=contract.mock_output_factory(request.envelope),
            provider_name=self.provider_name,
            model_identifier="counting-v1",
            duration_ms=1.0,
        )


def _put(client: TestClient, value: object, version: int, key: str = "ai_assistance") -> Any:
    return client.put(f"{_SETTINGS}/{key}", json={"value": value, "expected_version": version})


def _item(client: TestClient) -> dict[str, Any]:
    response = client.get(_SETTINGS)
    assert response.status_code == 200, response.text
    items = response.json()["settings"]
    assert [item["key"] for item in items] == ["ai_assistance"]
    item: dict[str, Any] = items[0]
    return item


def _completed_demo(client: TestClient) -> str:
    response = client.post("/api/v1/demo/sales")
    assert response.status_code == 202
    analysis_id = str(response.json()["analysis"]["analysis_id"])
    deadline = time.monotonic() + 15.0
    while time.monotonic() < deadline:
        state = client.get(f"/api/v1/analyses/{analysis_id}/status").json()["state"]
        if state == "completed":
            return analysis_id
        assert state not in {"failed", "cancelled"}
        time.sleep(0.01)
    raise AssertionError("the analysis did not finish")


def _configure_runtime(monkeypatch: pytest.MonkeyPatch, provider: Any | None = None) -> None:
    """A model is configured by the installation; LLM_PROVIDER is NOT (no override)."""
    monkeypatch.setenv("LLM_MODEL", "model-a")
    get_settings.cache_clear()
    if provider is not None:
        monkeypatch.setattr(analyses_module, "create_provider", lambda *a, **kw: provider)


# --- reading -----------------------------------------------------------------


def test_the_default_is_off_from_the_default_source_and_writable(client: TestClient) -> None:
    response = client.get(_SETTINGS)

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "settings": [
            {
                "key": "ai_assistance",
                "value": False,
                "source": "default",
                "managed_by_installation": False,
                "version": 0,
                "note": None,
            }
        ]
    }


# --- writing, versioning and reset -------------------------------------------


def test_a_stored_value_is_returned_with_its_source_and_a_new_version(
    client: TestClient,
) -> None:
    written = _put(client, True, 0)

    assert written.status_code == 200
    assert written.headers["cache-control"] == "no-store"
    body = written.json()
    assert (body["value"], body["source"], body["version"]) == (True, "stored", 1)
    assert body["managed_by_installation"] is False
    assert _item(client)["value"] is True
    assert _put(client, False, 1).json()["version"] == 2
    assert _item(client)["value"] is False


def test_a_stale_version_is_refused_and_changes_nothing(client: TestClient) -> None:
    assert _put(client, True, 0).status_code == 200

    stale = _put(client, False, 0)

    assert stale.status_code == 409
    error = stale.json()["error"]
    assert error["code"] == "SETTING_VERSION_CONFLICT"
    assert error["details"] == {"key": "ai_assistance", "current_version": 1}
    item = _item(client)
    assert (item["value"], item["version"]) == (True, 1)


def test_reset_removes_the_stored_value_and_the_default_applies(client: TestClient) -> None:
    _put(client, True, 0)

    reset = client.delete(f"{_SETTINGS}/ai_assistance", params={"expected_version": 1})

    assert reset.status_code == 200
    body = reset.json()
    assert (body["value"], body["source"], body["version"]) == (False, "default", 2)
    assert client.app.state.settings_store.get("ai_assistance").value is None  # type: ignore[attr-defined]


def test_reset_needs_the_current_version(client: TestClient) -> None:
    _put(client, True, 0)

    stale = client.delete(f"{_SETTINGS}/ai_assistance", params={"expected_version": 0})
    missing = client.delete(f"{_SETTINGS}/ai_assistance")

    assert stale.status_code == 409 and stale.json()["error"]["code"] == "SETTING_VERSION_CONFLICT"
    assert missing.status_code == 422
    assert _item(client)["value"] is True


# --- the allowlist is closed -------------------------------------------------


@pytest.mark.parametrize(
    "key", ["llm_provider", "max_file_size_mb", "database_url", "ai_profile", "nope"]
)
def test_an_unknown_key_is_not_found_and_is_not_echoed(client: TestClient, key: str) -> None:
    for response in (
        _put(client, True, 0, key=key),
        client.delete(f"{_SETTINGS}/{key}", params={"expected_version": 0}),
    ):
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "SETTING_NOT_FOUND"
        assert key not in response.text
    assert _item(client)["version"] == 0


@pytest.mark.parametrize("value", [1, 0, "true", "yes", None, [], {}, 1.5])
def test_a_value_that_is_not_a_boolean_is_rejected(client: TestClient, value: object) -> None:
    response = _put(client, value, 0)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_REQUEST"
    assert _item(client)["version"] == 0


@pytest.mark.parametrize(
    "body",
    [
        {"value": True},
        {"expected_version": 0},
        {"value": True, "expected_version": "0"},
        {"value": True, "expected_version": -1},
        {"value": True, "expected_version": 0, "source": "deployment"},
        {"value": True, "expected_version": 0, "llm_base_url": "http://x"},
    ],
)
def test_a_body_with_missing_wrong_or_extra_fields_is_rejected(
    client: TestClient, body: dict[str, object]
) -> None:
    assert client.put(f"{_SETTINGS}/ai_assistance", json=body).status_code == 422
    assert _item(client)["version"] == 0


def test_a_write_that_is_not_json_is_rejected(client: TestClient) -> None:
    response = client.put(
        f"{_SETTINGS}/ai_assistance",
        content='{"value": true, "expected_version": 0}',
        headers={"content-type": "text/plain"},
    )

    assert response.status_code == 422
    assert _item(client)["version"] == 0


def test_a_cross_origin_page_cannot_be_granted_a_write(client: TestClient) -> None:
    preflight = client.options(
        f"{_SETTINGS}/ai_assistance",
        headers={
            "Origin": "https://evil.example.invalid",
            "Access-Control-Request-Method": "PUT",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    written = client.put(
        f"{_SETTINGS}/ai_assistance",
        json={"value": True, "expected_version": 0},
        headers={"Origin": "https://evil.example.invalid"},
    )

    assert not any(name.lower().startswith("access-control-") for name in preflight.headers)
    assert not any(name.lower().startswith("access-control-") for name in written.headers)


def test_the_settings_surface_offers_no_other_write(client: TestClient) -> None:
    assert client.post(_SETTINGS, json={"key": "x", "value": 1}).status_code == 405
    assert client.patch(f"{_SETTINGS}/ai_assistance", json={}).status_code == 405
    assert client.get(f"{_SETTINGS}/ai_assistance").status_code in {404, 405}


# --- an explicit deployment override -----------------------------------------


@pytest.mark.parametrize("provider", ["disabled", "mock", "llama_cpp"])
def test_an_environment_override_is_read_only_with_a_plain_reason(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, provider: str
) -> None:
    monkeypatch.setenv("LLM_PROVIDER", provider)
    get_settings.cache_clear()

    item = _item(client)

    assert item["source"] == "deployment" and item["managed_by_installation"] is True
    assert item["value"] is (provider != "disabled")
    assert "set by your installation" in item["note"] and "cannot be changed here" in item["note"]
    written = _put(client, provider == "disabled", 0)
    assert written.status_code == 409
    assert written.json()["error"]["code"] == "SETTING_MANAGED_BY_INSTALLATION"
    reset = client.delete(f"{_SETTINGS}/ai_assistance", params={"expected_version": 0})
    assert reset.status_code == 409
    assert client.app.state.settings_store.get("ai_assistance").version == 0  # type: ignore[attr-defined]


def test_an_env_file_override_is_read_only_too(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    env_file = tmp_path / "installation.env"
    env_file.write_text("LLM_PROVIDER=disabled\n", encoding="utf-8")
    monkeypatch.setitem(Settings.model_config, "env_file", str(env_file))
    get_settings.cache_clear()

    item = _item(client)

    assert (item["source"], item["managed_by_installation"], item["value"]) == (
        "deployment",
        True,
        False,
    )
    assert _put(client, True, 0).status_code == 409


def test_a_stored_on_never_exceeds_an_override_added_later(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _put(client, True, 0)
    monkeypatch.setenv("LLM_PROVIDER", "disabled")
    get_settings.cache_clear()

    item = _item(client)

    assert (item["value"], item["source"]) == (False, "deployment")
    status = client.get("/api/v1/ai/status").json()
    assert (status["assistance"], status["state"]) == ("off", "disabled")


def test_other_llm_variables_do_not_make_the_setting_read_only(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name, value in {
        "LLM_MODEL": "model-a",
        "LLM_BASE_URL": "http://localhost:8081",
        "LLM_TIMEOUT_SECONDS": "30",
    }.items():
        monkeypatch.setenv(name, value)
    get_settings.cache_clear()

    assert _item(client)["managed_by_installation"] is False
    assert _put(client, True, 0).status_code == 200


# --- AI consumers follow the effective value ---------------------------------


def test_a_stored_on_with_no_runtime_is_on_but_unavailable_and_never_an_error(
    client: TestClient,
) -> None:
    analysis_id = _completed_demo(client)
    written = _put(client, True, 0).json()
    assert written["value"] is True
    assert "no local AI runtime" in written["note"]

    status = client.get("/api/v1/ai/status")
    started = client.post(enrichment_url(analysis_id, "0"))
    explanation = client.get(explanation_url(analysis_id, "0"))
    proposal = client.get(f"/api/v1/analyses/{analysis_id}/findings/0/rule-proposal")

    body = status.json()
    assert (body["assistance"], body["state"], body["location"]) == ("on", "unavailable", "none")
    assert "no local AI runtime is set up" in body["summary"]
    assert started.status_code == 202 and started.json()["state"] == "unavailable"
    assert explanation.status_code == 200
    assert explanation.json()["ai_call_status"] == "not_configured"
    assert proposal.status_code == 200
    assert proposal.json()["ai_call_status"] == "not_configured"
    assert client.app.state.enrichment_store.get(analysis_id, "0") is None  # type: ignore[attr-defined]


@pytest.mark.parametrize(
    "base_url", [_REMOTE_URL, "http://models.example.invalid:8081", "https://10.0.0.5"]
)
def test_a_stored_on_never_activates_an_address_that_is_not_this_machine(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, base_url: str
) -> None:
    provider = _CountingProvider()
    monkeypatch.setenv("LLM_BASE_URL", base_url)
    _configure_runtime(monkeypatch, provider)
    analysis_id = _completed_demo(client)

    written = _put(client, True, 0).json()
    status = client.get("/api/v1/ai/status")
    started = client.post(enrichment_url(analysis_id, "0"))
    explanation = client.get(explanation_url(analysis_id, "0"))
    context = client.get(f"/api/v1/analyses/{analysis_id}/context")
    proposal = client.get(f"/api/v1/analyses/{analysis_id}/findings/0/rule-proposal")
    advanced = client.get(f"{_SETTINGS}/advanced").json()

    assert written["value"] is True and written["source"] == "stored"
    assert "not on this machine" in written["note"] and "LLM_PROVIDER" in written["note"]
    body = status.json()
    assert (body["assistance"], body["state"], body["location"]) == ("on", "unavailable", "none")
    assert "not on this machine" in body["summary"]
    assert started.json()["state"] == "unavailable"
    assert explanation.json()["ai_call_status"] == "not_configured"
    assert proposal.json()["ai_call_status"] == "not_configured"
    assert context.status_code == 200
    assert provider.calls == 0
    assert client.app.state.enrichment_store.get(analysis_id, "0") is None  # type: ignore[attr-defined]
    assert (advanced["ai_provider"], advanced["runtime_address"]) == ("disabled", None)
    for response in (status, client.get(_SETTINGS)):
        for leak in _LEAKS:
            assert leak not in response.text


@pytest.mark.parametrize(
    "base_url",
    ["http://localhost:8081", "http://127.0.0.1:8081", "http://host.docker.internal:8081"],
)
def test_a_stored_on_activates_an_address_that_is_this_machine(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, base_url: str
) -> None:
    monkeypatch.setenv("LLM_BASE_URL", base_url)
    _configure_runtime(monkeypatch, _CountingProvider())

    written = _put(client, True, 0).json()

    assert written["note"] is None
    assert client.get(f"{_SETTINGS}/advanced").json()["ai_provider"] == "llama_cpp"


def test_an_explicit_override_may_still_use_a_non_local_address(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Sending to another address stays an explicit operator decision (LLM_PROVIDER).
    provider = _CountingProvider()
    monkeypatch.setenv("LLM_BASE_URL", "http://models.example.invalid:8081")
    monkeypatch.setenv("LLM_PROVIDER", "llama_cpp")
    _configure_runtime(monkeypatch, provider)
    analysis_id = _completed_demo(client)

    assert request_enrichment(client, analysis_id, "0")["state"] == "ready"
    assert provider.calls == 1


def test_a_stored_on_with_a_configured_model_enables_ai_without_a_restart(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = _CountingProvider()
    _configure_runtime(monkeypatch, provider)
    analysis_id = _completed_demo(client)
    assert client.post(enrichment_url(analysis_id, "0")).json()["state"] == "unavailable"
    assert provider.calls == 0

    assert _put(client, True, 0).json()["note"] is None
    final = request_enrichment(client, analysis_id, "0")

    assert final["state"] == "ready"
    assert provider.calls == 1
    overlaid = client.get(explanation_url(analysis_id, "0")).json()
    assert overlaid["ai_call_status"] == "attempted_accepted"


def test_turning_it_off_stops_enrichment_and_hides_a_saved_result(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = _CountingProvider()
    _configure_runtime(monkeypatch, provider)
    analysis_id = _completed_demo(client)
    _put(client, True, 0)
    assert request_enrichment(client, analysis_id, "0")["state"] == "ready"

    off = _put(client, False, 1)

    assert off.json()["value"] is False
    status = client.get("/api/v1/ai/status").json()
    assert (status["assistance"], status["state"]) == ("off", "disabled")
    assert client.get(enrichment_url(analysis_id, "0")).json()["state"] == "unavailable"
    assert client.post(enrichment_url(analysis_id, "0")).json()["state"] == "unavailable"
    after = client.get(explanation_url(analysis_id, "0")).json()
    assert after["ai_call_status"] == "not_configured"
    assert provider.calls == 1


def test_a_worker_that_starts_after_ai_was_turned_off_makes_no_model_call(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = _CountingProvider()
    _configure_runtime(monkeypatch, provider)
    analysis_id = _completed_demo(client)
    _put(client, True, 0)
    gate = threading.Event()
    real_execute = analyses_module._execute_finding_enrichment  # noqa: SLF001

    def held(*args: Any, **kwargs: Any) -> None:
        assert gate.wait(timeout=20)
        real_execute(*args, **kwargs)

    monkeypatch.setattr(analyses_module, "_execute_finding_enrichment", held)

    started = client.post(enrichment_url(analysis_id, "0"))
    assert started.status_code == 202 and started.json()["state"] == "preparing"
    _put(client, False, 1)
    gate.set()
    deadline = time.monotonic() + 20
    while client.app.state.enrichment_store.count_preparing():  # type: ignore[attr-defined]
        assert time.monotonic() < deadline
        time.sleep(0.01)

    assert provider.calls == 0


def test_an_override_keeps_every_consumer_on_the_deployment_value(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = _CountingProvider()
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    monkeypatch.setenv("LLM_MODEL", "model-a")
    get_settings.cache_clear()
    monkeypatch.setattr(analyses_module, "create_provider", lambda *a, **kw: provider)
    analysis_id = _completed_demo(client)

    assert request_enrichment(client, analysis_id, "0")["state"] == "ready"
    assert provider.calls == 1
    assert client.get("/api/v1/ai/status").json()["assistance"] == "on"


# --- no address or path outside the Advanced response ------------------------


def test_no_response_but_the_advanced_one_carries_an_address_or_model_path(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LLM_MODEL", _MODEL_PATH)
    monkeypatch.setenv("LLM_BASE_URL", _SECRET_URL)
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "1")
    get_settings.cache_clear()
    analysis_id = _completed_demo(client)
    _put(client, True, 0)

    responses = [
        client.get(_SETTINGS),
        _put(client, True, 1),
        _put(client, "bad", 2),
        _put(client, True, 0),
        client.delete(f"{_SETTINGS}/nope", params={"expected_version": 0}),
        client.get("/api/v1/ai/status"),
        client.get(f"/api/v1/analyses/{analysis_id}"),
        client.get(f"/api/v1/analyses/{analysis_id}/findings"),
        client.get(f"/api/v1/analyses/{analysis_id}/findings/0"),
        client.get(explanation_url(analysis_id, "0")),
        client.post(enrichment_url(analysis_id, "0")),
        client.get(enrichment_url(analysis_id, "0")),
        client.get("/api/v1/health/ready"),
        client.get("/api/v1/version"),
    ]

    for response in responses:
        for leak in _LEAKS:
            assert leak not in response.text, (response.request.url, leak)


def test_the_advanced_response_reduces_the_address_to_scheme_host_and_port(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LLM_MODEL", "model-a")
    monkeypatch.setenv("LLM_BASE_URL", _SECRET_URL)
    get_settings.cache_clear()
    _put(client, True, 0)

    response = client.get(f"{_SETTINGS}/advanced")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["runtime_address"] == "http://localhost:8081"
    assert body["model_identifier"] == "model-a"
    assert (body["ai_provider"], body["ai_assistance_source"]) == ("llama_cpp", "stored")
    for leak in ("hunter2", "svc-user", "abc123", "private-path"):
        assert leak not in response.text


def test_the_advanced_response_shows_nothing_to_reach_when_ai_is_off(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("LLM_BASE_URL", "http://10.9.8.7:8081")
    get_settings.cache_clear()

    body = client.get(f"{_SETTINGS}/advanced").json()

    assert (body["ai_provider"], body["runtime_address"], body["model_identifier"]) == (
        "disabled",
        None,
        None,
    )
    assert body["sample_values_sent"] is False


def test_an_unreadable_store_fails_closed_to_off(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure_runtime(monkeypatch)
    _put(client, True, 0)

    def broken(*args: object, **kwargs: object) -> None:
        raise RuntimeError("database is locked at /secret/path")

    monkeypatch.setattr(client.app.state.settings_store, "get", broken)  # type: ignore[attr-defined]

    status = client.get("/api/v1/ai/status")
    item = client.get(_SETTINGS)

    assert status.status_code == 200 and status.json()["assistance"] == "off"
    assert item.status_code == 200 and item.json()["settings"][0]["value"] is False
    assert "secret" not in status.text + item.text
