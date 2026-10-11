"""`GET /ai/readiness` and `POST /ai/connection-test` (`UX-09`, D-066 item 10).

Readiness must report only what was verified; the connection test must take no input,
contact only the configured local runtime, be bounded, make no completion call, and
never return an address, path or exception text.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from trusttable_backend import ai_readiness
from trusttable_backend.ai_readiness import (
    ConnectionTestGate,
    compute_readiness,
    run_connection_test,
)
from trusttable_backend.ai_status import compute_ai_status
from trusttable_backend.config import Settings, get_settings
from trusttable_backend.main import create_app
from trusttable_backend.product_settings import resolve_ai_assistance

_LEAKS = (
    "127.0.0.1",
    "localhost",
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
_MODEL_PATH = "/home/secret-user/models/Qwen3.5-4B-Q4_K_M.gguf"


def _settings(**overrides: object) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[arg-type]


def _states(settings: Settings, stored: bool | None, *, answers: bool = True) -> dict[str, str]:
    resolution = resolve_ai_assistance(settings, stored)

    def factory(name: str, **kwargs: object) -> object:
        class _P:
            def health_check(self) -> object:
                class _H:
                    available = answers

                return _H()

        return _P()

    status = compute_ai_status(
        resolution.settings,
        provider_factory=factory,  # type: ignore[arg-type]
        assistance_requested=resolution.enabled and not resolution.runtime_configured,
        unavailable_reason=resolution.unavailable_reason,
    )
    readiness = compute_readiness(resolution, status)
    return {check.key: check.state for check in readiness.checks}


# --- readiness -----------------------------------------------------------------


def test_assistance_off_stops_the_checklist_at_the_first_step() -> None:
    states = _states(_settings(), None)

    assert states == {
        "assistance_on": "todo",
        "runtime_configured": "not_checked",
        "runtime_on_this_machine": "not_checked",
        "runtime_answers": "not_checked",
        "model_named": "not_checked",
    }


def test_stored_on_without_a_runtime_asks_for_a_runtime_not_for_assistance() -> None:
    states = _states(_settings(llm_model=""), True)

    assert states["assistance_on"] == "done"
    assert states["runtime_configured"] == "todo"
    assert states["runtime_answers"] == "not_checked"


def test_stored_on_with_a_runtime_that_is_not_on_this_machine_is_not_probed() -> None:
    states = _states(
        _settings(llm_model="m.gguf", llm_base_url="http://models.example.invalid:9"), True
    )

    assert states["runtime_configured"] == "done"
    assert states["runtime_on_this_machine"] == "todo"
    assert states["runtime_answers"] == "not_checked"


def test_a_local_runtime_that_answers_is_ready() -> None:
    settings = _settings(llm_model=_MODEL_PATH, llm_base_url="http://localhost:8081")
    resolution = resolve_ai_assistance(settings, True)

    def factory(name: str, **kwargs: object) -> object:
        class _P:
            def health_check(self) -> object:
                class _H:
                    available = True

                return _H()

        return _P()

    status = compute_ai_status(resolution.settings, provider_factory=factory)  # type: ignore[arg-type]
    readiness = compute_readiness(resolution, status)

    assert readiness.ready is True
    assert [check.state for check in readiness.checks] == ["done"] * 5
    assert readiness.model_label == "Qwen3.5 4B"
    for leak in _LEAKS:
        assert leak not in str(readiness)


def test_a_local_runtime_that_does_not_answer_is_not_ready_and_says_what_to_do() -> None:
    states = _states(
        _settings(llm_model="m.gguf", llm_base_url="http://localhost:8081"), True, answers=False
    )

    assert states["runtime_answers"] == "todo"
    assert states["runtime_on_this_machine"] == "done"


def test_a_runtime_whose_location_cannot_be_confirmed_needs_attention_not_a_pass() -> None:
    states = _states(
        _settings(
            llm_provider="llama_cpp",
            llm_model="m.gguf",
            llm_base_url="http://models.example.invalid:9",
        ),
        None,
    )

    assert states["runtime_on_this_machine"] == "attention"


def test_a_deployment_managed_off_says_the_installation_manages_it() -> None:
    resolution = resolve_ai_assistance(_settings(llm_provider="disabled"), True)
    status = compute_ai_status(resolution.settings)
    readiness = compute_readiness(resolution, status)

    assert readiness.checks[0].state == "todo"
    assert "your installation manages" in readiness.checks[0].detail


# --- the connection test -------------------------------------------------------


class _Counting:
    def __init__(self, answers: bool = True) -> None:
        self.calls = 0
        self.answers = answers

    def __call__(self, settings: Settings, *, provider_factory: object = None) -> bool:
        self.calls += 1
        return self.answers


def _local_on() -> object:
    return resolve_ai_assistance(
        _settings(llm_model="m.gguf", llm_base_url="http://localhost:8081"), True
    )


def test_a_reachable_runtime_is_reported_with_the_honest_scope_of_the_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    probe = _Counting(True)
    monkeypatch.setattr(ai_readiness, "probe_runtime", probe)

    result = run_connection_test(_local_on(), gate=ConnectionTestGate())  # type: ignore[arg-type]

    assert (result.outcome, result.tested) == ("reachable", True)
    assert "does not check the model" in result.message
    assert probe.calls == 1


def test_an_unreachable_runtime_is_reported_without_detail(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ai_readiness, "probe_runtime", _Counting(False))

    result = run_connection_test(_local_on(), gate=ConnectionTestGate())  # type: ignore[arg-type]

    assert (result.outcome, result.tested) == ("not_reachable", True)
    for leak in _LEAKS:
        assert leak not in result.message


@pytest.mark.parametrize(
    ("settings", "stored", "outcome"),
    [
        (_settings(), None, "assistance_off"),
        (_settings(llm_model=""), True, "no_runtime"),
        (
            _settings(llm_model="m.gguf", llm_base_url="http://models.example.invalid:9"),
            True,
            "not_local",
        ),
        (
            _settings(
                llm_provider="llama_cpp",
                llm_model="m.gguf",
                llm_base_url="http://models.example.invalid:9",
            ),
            None,
            "not_local",
        ),
    ],
)
def test_a_refused_test_never_probes_and_says_why(
    monkeypatch: pytest.MonkeyPatch, settings: Settings, stored: bool | None, outcome: str
) -> None:
    probe = _Counting(True)
    monkeypatch.setattr(ai_readiness, "probe_runtime", probe)

    result = run_connection_test(resolve_ai_assistance(settings, stored), gate=ConnectionTestGate())

    assert (result.outcome, result.tested) == (outcome, False)
    assert probe.calls == 0


def test_the_gate_allows_one_in_flight_and_a_minimum_interval() -> None:
    now = [100.0]
    gate = ConnectionTestGate(min_interval_seconds=5, clock=lambda: now[0])

    assert gate.begin() == ("ok", None)
    assert gate.begin() == ("busy", None)
    gate.end()
    assert gate.begin() == ("too_soon", 5)
    now[0] += 2.5
    assert gate.begin() == ("too_soon", 3)
    now[0] += 3
    assert gate.begin() == ("ok", None)


def test_a_probe_that_raises_still_releases_the_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(settings: Settings, *, provider_factory: object = None) -> bool:
        raise RuntimeError("connect to 10.9.8.7:1234 refused at /srv/secret/path")

    monkeypatch.setattr(ai_readiness, "probe_runtime", boom)
    gate = ConnectionTestGate(min_interval_seconds=0)

    with pytest.raises(RuntimeError):
        run_connection_test(_local_on(), gate=gate)  # type: ignore[arg-type]

    assert gate.begin() == ("ok", None)


def test_a_second_test_inside_the_interval_is_refused_without_a_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    probe = _Counting(True)
    monkeypatch.setattr(ai_readiness, "probe_runtime", probe)
    gate = ConnectionTestGate()

    first = run_connection_test(_local_on(), gate=gate)  # type: ignore[arg-type]
    second = run_connection_test(_local_on(), gate=gate)  # type: ignore[arg-type]

    assert first.outcome == "reachable"
    assert (second.outcome, second.tested) == ("too_soon", False)
    assert second.retry_after_seconds is not None and second.retry_after_seconds >= 1
    assert probe.calls == 1


# --- the routes ----------------------------------------------------------------


def test_the_readiness_route_reports_assistance_off_by_default(client: TestClient) -> None:
    response = client.get("/api/v1/ai/readiness")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    assert body["ready"] is False
    assert set(body) == {"ready", "model_label", "runtime_label", "checks"}
    assert [check["key"] for check in body["checks"]] == [
        "assistance_on",
        "runtime_configured",
        "runtime_on_this_machine",
        "runtime_answers",
        "model_named",
    ]
    assert body["checks"][0]["state"] == "todo"


def test_the_readiness_route_for_an_unreachable_runtime_leaks_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "llama_cpp")
    monkeypatch.setenv("LLM_MODEL", _MODEL_PATH)
    monkeypatch.setenv("LLM_BASE_URL", "http://127.0.0.1:1")
    monkeypatch.setenv("LLM_TIMEOUT_SECONDS", "1")
    get_settings.cache_clear()

    with TestClient(create_app()) as client:
        response = client.get("/api/v1/ai/readiness")

    assert response.status_code == 200
    states = {check["key"]: check["state"] for check in response.json()["checks"]}
    assert states["runtime_answers"] == "todo"
    assert response.json()["model_label"] == "Qwen3.5 4B"
    for leak in _LEAKS:
        assert leak not in response.text


def test_the_connection_test_with_assistance_off_probes_nothing(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    probe = _Counting(True)
    monkeypatch.setattr(ai_readiness, "probe_runtime", probe)

    response = client.post("/api/v1/ai/connection-test")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "outcome": "assistance_off",
        "tested": False,
        "message": "AI assistance is off, so nothing was tested.",
        "retry_after_seconds": None,
    }
    assert probe.calls == 0


def test_forged_input_cannot_choose_a_target_or_start_a_probe(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    probe = _Counting(True)
    monkeypatch.setattr(ai_readiness, "probe_runtime", probe)

    response = client.post(
        "/api/v1/ai/connection-test?base_url=http://10.9.8.7:9&url=http://10.9.8.7:9",
        json={"base_url": "http://10.9.8.7:9", "model": "x", "path": "/etc/passwd"},
        headers={"X-LLM-Base-URL": "http://10.9.8.7:9", "Host": "10.9.8.7:9"},
    )

    assert response.status_code == 200
    assert response.json()["outcome"] == "assistance_off"
    assert probe.calls == 0
    for echoed in ("10.9.8.7", "/etc/passwd"):
        assert echoed not in response.text


def test_the_connection_test_with_a_configured_local_runtime_is_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    probe = _Counting(True)
    monkeypatch.setattr(ai_readiness, "probe_runtime", probe)
    monkeypatch.setenv("LLM_PROVIDER", "llama_cpp")
    monkeypatch.setenv("LLM_MODEL", _MODEL_PATH)
    monkeypatch.setenv("LLM_BASE_URL", "http://localhost:8081")
    get_settings.cache_clear()

    with TestClient(create_app()) as client:
        first = client.post("/api/v1/ai/connection-test")
        second = client.post("/api/v1/ai/connection-test")

    assert first.json()["outcome"] == "reachable" and first.json()["tested"] is True
    assert second.json()["outcome"] == "too_soon" and second.json()["tested"] is False
    assert probe.calls == 1
    for response in (first, second):
        for leak in _LEAKS:
            assert leak not in json.dumps(response.json())


def test_the_new_routes_make_no_completion_call(monkeypatch: pytest.MonkeyPatch) -> None:
    from trusttable_backend.ai_provider.contract import ProviderHealth
    from trusttable_backend.ai_provider.llama_cpp import LlamaCppProvider

    completions: list[object] = []

    def health(self: LlamaCppProvider) -> ProviderHealth:
        return ProviderHealth(
            available=True, provider_name="llama_cpp", model_identifier="x", detail=""
        )

    def complete(self: LlamaCppProvider, request: object) -> object:
        completions.append(request)
        raise AssertionError("no completion may be requested")

    monkeypatch.setattr(LlamaCppProvider, "health_check", health)
    monkeypatch.setattr(LlamaCppProvider, "complete", complete)
    monkeypatch.setenv("LLM_PROVIDER", "llama_cpp")
    monkeypatch.setenv("LLM_MODEL", "m.gguf")
    monkeypatch.setenv("LLM_BASE_URL", "http://localhost:8081")
    get_settings.cache_clear()

    with TestClient(create_app()) as client:
        readiness = client.get("/api/v1/ai/readiness")
        test = client.post("/api/v1/ai/connection-test")

    assert readiness.json()["ready"] is True
    assert test.json()["outcome"] == "reachable"
    assert completions == []
