"""Tests for the benchmark-only llama.cpp HTTP adapter (`AI-06` hands-on
evaluation support).

All HTTP interaction is stubbed via `httpx.MockTransport` (already part
of the installed `httpx` dependency) — no real network access anywhere
in this module.
"""

from __future__ import annotations

import json
from collections.abc import Callable

import httpx
import pytest

from trusttable_backend.ai_benchmark.adapters.llama_cpp_http import (
    PROVIDER_NAME,
    LlamaCppHttpProvider,
)
from trusttable_backend.ai_boundary.envelope import PromptEnvelope
from trusttable_backend.ai_boundary.prompt import build_safe_prompt
from trusttable_backend.ai_boundary.validation import (
    MODEL_OUTPUT_SCHEMA_VERSION,
    validate_model_output,
)
from trusttable_backend.ai_provider.contract import (
    AIOperation,
    AIProvider,
    ProviderConnectionError,
    ProviderInvalidResponseError,
    ProviderRequest,
    ProviderTimeoutError,
)
from trusttable_backend.ai_provider.factory import UnknownProviderError, create_provider
from trusttable_backend.domain.evidence import Evidence, EvidenceType
from trusttable_backend.domain.parsing import SamplingScope
from trusttable_backend.domain.value_objects import ColumnReference, Provenance


def make_column(key: str) -> ColumnReference:
    return ColumnReference(original_name=key, internal_key=key, ordinal=0)


def make_evidence(**overrides: object) -> Evidence:
    fields: dict[str, object] = {
        "evidence_id": "ev-1",
        "evidence_type": EvidenceType.METRIC,
        "calculation_version": "1",
        "structured_payload": {"mean": 1.5},
        "affected_columns": (make_column("quantity"),),
        "affected_row_references": (),
        "scope": SamplingScope.FULL,
        "display_safe_summary": "Mean value is 1.5",
    }
    fields.update(overrides)
    return Evidence(**fields)  # type: ignore[arg-type]


def make_request(*, retry_feedback: str | None = None) -> ProviderRequest:
    envelope = PromptEnvelope(
        task="Explain the following.",
        computed_evidence=(make_evidence(),),
        confirmed_context={},
        untrusted_dataset_samples=(),
        sample_sending_enabled=False,
    )
    return ProviderRequest(
        operation=AIOperation.FINDING_EXPLANATION,
        envelope=envelope,
        known_numeric_facts={},
        retry_feedback=retry_feedback,
    )


def well_formed_content() -> dict[str, object]:
    return {
        "schema_version": MODEL_OUTPUT_SCHEMA_VERSION,
        "narrative": "A well-formed narrative.",
        "provenance": Provenance.AI_INTERPRETATION.value,
    }


def chat_completion_response(status_code: int, message_content: str) -> httpx.Response:
    return httpx.Response(
        status_code,
        json={"choices": [{"message": {"content": message_content}}]},
    )


def make_provider(
    handler: Callable[[httpx.Request], httpx.Response], **overrides: object
) -> LlamaCppHttpProvider:
    client = httpx.Client(transport=httpx.MockTransport(handler))
    fields: dict[str, object] = {
        "base_url": "http://127.0.0.1:8080",
        "model_identifier": "test-model",
        "client": client,
    }
    fields.update(overrides)
    return LlamaCppHttpProvider(**fields)  # type: ignore[arg-type]


# --- Construction / boundary -------------------------------------------------


def test_base_url_must_not_be_empty() -> None:
    with pytest.raises(ValueError, match="base_url"):
        LlamaCppHttpProvider(base_url="", model_identifier="m")


def test_model_identifier_must_not_be_empty() -> None:
    with pytest.raises(ValueError, match="model_identifier"):
        LlamaCppHttpProvider(base_url="http://127.0.0.1:8080", model_identifier="")


def test_timeout_seconds_must_be_positive() -> None:
    with pytest.raises(ValueError, match="timeout_seconds"):
        LlamaCppHttpProvider(
            base_url="http://127.0.0.1:8080", model_identifier="m", timeout_seconds=0
        )


# --- AC-01/AC-02: Protocol conformance and identity --------------------------


def test_provider_satisfies_ai_provider_protocol() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200)

    provider = make_provider(handler)
    assert isinstance(provider, AIProvider)


def test_provider_name_is_distinct_benchmark_only_string() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200)

    provider = make_provider(handler)
    assert provider.provider_name == PROVIDER_NAME
    assert PROVIDER_NAME not in {"disabled", "mock", "ollama"}


def test_provider_name_not_recognized_by_product_factory() -> None:
    """No product-provider registration/configuration side effect: the
    adapter's own `provider_name` is not a value `create_provider`
    (`AI-02`) recognizes."""
    with pytest.raises(UnknownProviderError):
        create_provider(PROVIDER_NAME)


# --- AC-03/AC-04: health_check ------------------------------------------------


def test_health_check_reports_available_for_healthy_endpoint() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/health"
        return httpx.Response(200, json={"status": "ok"})

    provider = make_provider(handler)
    health = provider.health_check()

    assert health.available is True
    assert health.provider_name == PROVIDER_NAME
    assert health.model_identifier == "test-model"
    assert health.detail


def test_health_check_reports_unavailable_when_unreachable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    provider = make_provider(handler)
    health = provider.health_check()

    assert health.available is False
    assert health.detail


def test_health_check_reports_unavailable_for_server_error_status() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503)

    provider = make_provider(handler)
    health = provider.health_check()

    assert health.available is False


# --- AC-05: build_safe_prompt reuse -------------------------------------------


def test_complete_sends_build_safe_prompt_content() -> None:
    request = make_request()
    expected = build_safe_prompt(request.envelope)
    captured: dict[str, object] = {}

    def handler(http_request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(http_request.content)
        return chat_completion_response(200, json.dumps(well_formed_content()))

    provider = make_provider(handler)
    provider.complete(request)

    body = captured["body"]
    assert isinstance(body, dict)
    messages = body["messages"]
    assert messages[0]["content"].startswith(expected.system_instructions)
    sent_payload = json.loads(messages[1]["content"])
    assert sent_payload == expected.data_payload


def test_complete_includes_retry_feedback_in_user_content() -> None:
    request = make_request(retry_feedback="unknown_evidence_id")
    captured: dict[str, object] = {}

    def handler(http_request: httpx.Request) -> httpx.Response:
        captured["body"] = json.loads(http_request.content)
        return chat_completion_response(200, json.dumps(well_formed_content()))

    provider = make_provider(handler)
    provider.complete(request)

    body = captured["body"]
    assert isinstance(body, dict)
    user_content = body["messages"][1]["content"]
    assert "unknown_evidence_id" in user_content


# --- AC-06: structured response translation -----------------------------------


def test_complete_returns_parsed_structured_response() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return chat_completion_response(200, json.dumps(well_formed_content()))

    provider = make_provider(handler)
    response = provider.complete(make_request())

    assert response.raw_output == well_formed_content()
    assert response.provider_name == PROVIDER_NAME
    assert response.model_identifier == "test-model"
    assert response.duration_ms >= 0


# --- AC-07: round-trip through the real validation boundary ------------------


def test_well_formed_response_is_accepted_by_validate_model_output() -> None:
    request = make_request()

    def handler(http_request: httpx.Request) -> httpx.Response:
        return chat_completion_response(200, json.dumps(well_formed_content()))

    provider = make_provider(handler)
    response = provider.complete(request)

    outcome = validate_model_output(
        response.raw_output, request.envelope, known_numeric_facts=request.known_numeric_facts
    )
    assert outcome.accepted is True


def test_response_missing_required_key_is_rejected_by_validate_model_output() -> None:
    request = make_request()
    malformed = {"schema_version": MODEL_OUTPUT_SCHEMA_VERSION, "narrative": "no provenance here"}

    def handler(http_request: httpx.Request) -> httpx.Response:
        return chat_completion_response(200, json.dumps(malformed))

    provider = make_provider(handler)
    response = provider.complete(request)

    outcome = validate_model_output(
        response.raw_output, request.envelope, known_numeric_facts=request.known_numeric_facts
    )
    assert outcome.accepted is False
    assert outcome.rejection_reasons


# --- AC-08: transport failure --------------------------------------------------


def test_complete_raises_provider_connection_error_on_transport_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    provider = make_provider(handler)
    with pytest.raises(ProviderConnectionError):
        provider.complete(make_request())


# --- AC-09: non-2xx HTTP response ----------------------------------------------


def test_complete_raises_provider_invalid_response_error_on_non_2xx() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="internal server error")

    provider = make_provider(handler)
    with pytest.raises(ProviderInvalidResponseError):
        provider.complete(make_request())


# --- AC-10: malformed/non-JSON model content -----------------------------------


def test_complete_raises_provider_invalid_response_error_on_malformed_model_json() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return chat_completion_response(200, "this is not JSON")

    provider = make_provider(handler)
    with pytest.raises(ProviderInvalidResponseError):
        provider.complete(make_request())


def test_complete_raises_provider_invalid_response_error_on_unexpected_shape() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"unexpected": "shape"})

    provider = make_provider(handler)
    with pytest.raises(ProviderInvalidResponseError):
        provider.complete(make_request())


def test_complete_raises_provider_invalid_response_error_when_model_json_is_not_an_object() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return chat_completion_response(200, json.dumps(["not", "an", "object"]))

    provider = make_provider(handler)
    with pytest.raises(ProviderInvalidResponseError):
        provider.complete(make_request())


# --- AC-11: timeout --------------------------------------------------------------


def test_complete_raises_provider_timeout_error_on_timeout() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.TimeoutException("timed out", request=request)

    provider = make_provider(handler)
    with pytest.raises(ProviderTimeoutError):
        provider.complete(make_request())
