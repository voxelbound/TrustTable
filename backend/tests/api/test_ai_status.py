"""`GET /ai/status` (`UX-02`, D-068, `docs/api-specification.md` §4).

The status must be honest (derived from the real configuration and one bounded
probe), must never make a completion call, and must never leak a base URL, host,
port, filesystem path or exception text.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from fastapi.testclient import TestClient

from trusttable_backend.ai_provider.contract import (
    ProviderHealth,
    ProviderRequest,
    ProviderResponse,
)
from trusttable_backend.ai_provider.factory import UnknownProviderError
from trusttable_backend.ai_status import MAX_PROBE_SECONDS, compute_ai_status
from trusttable_backend.config import Settings, get_settings
from trusttable_backend.main import create_app

_MODEL_PATH = "/home/secret-user/models/Qwen3.5-4B-Q4_K_M.gguf"
_LEAKS = (
    "127.0.0.1",
    "secret-user",
    "/home",
    "models/",
    "example.invalid",
    "refused",
    "Connection",
    "httpx",
    "Traceback",
    ":8081",
    ":9",
)


def _settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[arg-type]


class _Probe:
    """A provider double that only answers health checks."""

    def __init__(self, *, available: bool = True, raises: Exception | None = None) -> None:
        self.available = available
        self.raises = raises
        self.health_calls = 0

    @property
    def provider_name(self) -> str:
        return "double"

    def health_check(self) -> ProviderHealth:
        self.health_calls += 1
        if self.raises is not None:
            raise self.raises
        return ProviderHealth(
            available=self.available,
            provider_name="double",
            model_identifier="x",
            detail="http://10.9.8.7:1234 failed: boom",
        )

    def complete(self, request: ProviderRequest) -> ProviderResponse:  # pragma: no cover
        raise AssertionError("the status route must never request a completion")


def _factory(probe: _Probe, seen: dict[str, object] | None = None) -> Callable[..., _Probe]:
    def build(name: str, **kwargs: object) -> _Probe:
        if seen is not None:
            seen.update(kwargs)
            seen["name"] = name
        return probe

    return build


# --- the pure computation ----------------------------------------------------


def test_disabled_means_off_with_nothing_sent_anywhere() -> None:
    status = compute_ai_status(_settings(llm_provider="disabled", llm_send_sample_values=True))

    assert (status.assistance, status.state, status.location) == ("off", "disabled", "none")
    assert status.runtime_label is None and status.model_label is None
    assert status.sample_values_sent is False
    assert "no dataset content is sent to any model" in status.summary


def test_a_ready_local_runtime_is_reported_with_a_readable_model_label() -> None:
    probe = _Probe(available=True)
    status = compute_ai_status(
        _settings(
            llm_provider="llama_cpp",
            llm_model=_MODEL_PATH,
            llm_base_url="http://localhost:8081",
        ),
        provider_factory=_factory(probe),
    )

    assert (status.assistance, status.state, status.location) == ("on", "ready", "local")
    assert status.provider_label == "Local AI"
    assert status.runtime_label == "llama.cpp"
    assert status.model_label == "Qwen3.5 4B"
    assert "ready, on this machine" in status.summary
    for leak in _LEAKS:
        assert leak not in str(status)


def test_a_runtime_whose_location_cannot_be_confirmed_is_not_called_local() -> None:
    status = compute_ai_status(
        _settings(
            llm_provider="llama_cpp",
            llm_model="m.gguf",
            llm_base_url="http://models.example.invalid:9",
        ),
        provider_factory=_factory(_Probe(available=True)),
    )

    assert status.location == "unknown"
    assert "cannot confirm" in status.summary
    assert "example.invalid" not in str(status)


def test_an_unreachable_runtime_is_unavailable_and_says_everything_else_still_works() -> None:
    status = compute_ai_status(
        _settings(llm_provider="llama_cpp", llm_model="m.gguf"),
        provider_factory=_factory(_Probe(available=False)),
    )

    assert status.state == "unavailable"
    assert status.assistance == "on"
    assert "not reachable" in status.summary
    assert "built-in checks alone" in status.summary
    assert "10.9.8.7" not in str(status)  # the provider's own detail is never returned


@pytest.mark.parametrize(
    "error",
    [
        RuntimeError("connect to 10.9.8.7:1234 refused at /srv/secret/path"),
        TimeoutError("timed out talking to http://10.9.8.7:1234"),
        UnknownProviderError("llama_cpp requires base_url and model_identifier"),
        OSError("socket error"),
    ],
)
def test_any_probe_failure_is_unavailable_and_never_leaks_its_text(error: Exception) -> None:
    status = compute_ai_status(
        _settings(llm_provider="llama_cpp", llm_model="m.gguf"),
        provider_factory=_factory(_Probe(raises=error)),
    )

    assert status.state == "unavailable"
    assert not any(text in str(status) for text in ("10.9.8.7", "/srv", "socket", "timed out"))


def test_the_probe_timeout_is_capped_at_three_seconds() -> None:
    seen: dict[str, object] = {}
    compute_ai_status(
        _settings(llm_provider="llama_cpp", llm_model="m.gguf", llm_timeout_seconds=120),
        provider_factory=_factory(_Probe(), seen),
    )
    assert seen["timeout_seconds"] == MAX_PROBE_SECONDS == 3.0

    shorter: dict[str, object] = {}
    compute_ai_status(
        _settings(llm_provider="llama_cpp", llm_model="m.gguf", llm_timeout_seconds=2),
        provider_factory=_factory(_Probe(), shorter),
    )
    assert shorter["timeout_seconds"] == 2.0


def test_only_one_liveness_probe_is_made_and_no_completion_is_requested() -> None:
    probe = _Probe()

    compute_ai_status(
        _settings(llm_provider="llama_cpp", llm_model="m.gguf"),
        provider_factory=_factory(probe),
    )

    assert probe.health_calls == 1  # `_Probe.complete` raises if it were ever called


@pytest.mark.parametrize("sample_values", [True, False])
def test_the_sample_value_setting_is_reported_only_while_assistance_is_on(
    sample_values: bool,
) -> None:
    status = compute_ai_status(
        _settings(
            llm_provider="llama_cpp", llm_model="m.gguf", llm_send_sample_values=sample_values
        ),
        provider_factory=_factory(_Probe()),
    )

    assert status.sample_values_sent is sample_values
    assert ("may also be included" in status.summary) is sample_values
    assert ("are not included" in status.summary) is (not sample_values)


def test_the_mock_provider_is_labelled_as_a_test_ai() -> None:
    status = compute_ai_status(_settings(llm_provider="mock"))

    assert status.provider_label == "Test AI"
    assert status.location == "local"
    assert status.state == "ready"


def test_a_missing_model_name_for_llama_cpp_is_unavailable_not_an_error() -> None:
    status = compute_ai_status(_settings(llm_provider="llama_cpp", llm_model=""))

    assert status.state == "unavailable"


# --- the route ---------------------------------------------------------------


def test_the_route_reports_disabled_by_default(client: TestClient) -> None:
    response = client.get("/api/v1/ai/status")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["assistance"] == "off" and body["state"] == "disabled"
    assert set(body) == {
        "assistance",
        "state",
        "location",
        "provider_label",
        "runtime_label",
        "model_label",
        "sample_values_sent",
        "summary",
    }


def test_the_route_for_an_unreachable_runtime_leaks_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "llama_cpp")
    monkeypatch.setenv("LLM_MODEL", _MODEL_PATH)
    monkeypatch.setenv("LLM_BASE_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "1")
    get_settings.cache_clear()

    with TestClient(create_app()) as client:
        response = client.get("/api/v1/ai/status")

    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "unavailable"
    assert body["location"] == "local"
    assert body["model_label"] == "Qwen3.5 4B"
    for leak in _LEAKS:
        assert leak not in response.text
