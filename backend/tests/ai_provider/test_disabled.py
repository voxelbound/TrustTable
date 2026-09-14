"""Tests for the disabled AI provider (`AI-02`).

Covers this package's acceptance criterion AC-01: positive, negative,
and boundary cases for `DisabledProvider`.
"""

from __future__ import annotations

import pytest

from trusttable_backend.ai_boundary.envelope import PromptEnvelope
from trusttable_backend.ai_provider.contract import (
    AIOperation,
    AIProvider,
    ProviderConnectionError,
    ProviderRequest,
)
from trusttable_backend.ai_provider.disabled import DISABLED_PROVIDER_NAME, DisabledProvider


def make_envelope() -> PromptEnvelope:
    return PromptEnvelope(
        task="Explain supplied deterministic findings.",
        computed_evidence=(),
        confirmed_context={},
        untrusted_dataset_samples=(),
    )


def make_request(**overrides: object) -> ProviderRequest:
    fields: dict[str, object] = {
        "operation": AIOperation.FINDING_EXPLANATION,
        "envelope": make_envelope(),
        "known_numeric_facts": {},
        "retry_feedback": None,
    }
    fields.update(overrides)
    return ProviderRequest(**fields)  # type: ignore[arg-type]


def test_disabled_provider_name() -> None:
    provider = DisabledProvider()
    assert provider.provider_name == "disabled"
    assert provider.provider_name == DISABLED_PROVIDER_NAME


def test_disabled_provider_satisfies_ai_provider_protocol() -> None:
    provider: AIProvider = DisabledProvider()
    assert isinstance(provider, AIProvider)


def test_disabled_provider_health_check_reports_unavailable() -> None:
    provider = DisabledProvider()
    health = provider.health_check()
    assert health.available is False
    assert health.provider_name == "disabled"
    assert health.model_identifier == ""
    assert health.detail != ""


def test_disabled_provider_complete_raises_provider_connection_error() -> None:
    provider = DisabledProvider()
    with pytest.raises(ProviderConnectionError):
        provider.complete(make_request())


def test_disabled_provider_complete_error_message_explains_disabled_state() -> None:
    provider = DisabledProvider()
    with pytest.raises(ProviderConnectionError) as excinfo:
        provider.complete(make_request())
    assert "disabled" in str(excinfo.value).lower()


def test_disabled_provider_complete_raises_for_every_operation() -> None:
    """Boundary: the disabled provider refuses regardless of which
    `AIOperation` is requested — it is not operation-specific."""
    provider = DisabledProvider()
    for operation in AIOperation:
        with pytest.raises(ProviderConnectionError):
            provider.complete(make_request(operation=operation))
