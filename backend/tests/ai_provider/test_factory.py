"""Tests for the provider factory (`AI-02`/`AI-03`).

Covers this package's acceptance criterion AC-07: positive, negative,
and boundary cases for `create_provider`.
"""

from __future__ import annotations

import pytest

from trusttable_backend.ai_provider.disabled import DisabledProvider
from trusttable_backend.ai_provider.factory import UnknownProviderError, create_provider
from trusttable_backend.ai_provider.llama_cpp import LlamaCppProvider
from trusttable_backend.ai_provider.mock import MockProvider


def test_create_provider_disabled_returns_disabled_provider() -> None:
    provider = create_provider("disabled")
    assert isinstance(provider, DisabledProvider)
    assert provider.provider_name == "disabled"


def test_create_provider_mock_returns_mock_provider() -> None:
    provider = create_provider("mock")
    assert isinstance(provider, MockProvider)
    assert provider.provider_name == "mock"


def test_create_provider_llama_cpp_returns_llama_cpp_provider() -> None:
    provider = create_provider(
        "llama_cpp", base_url="http://127.0.0.1:8080", model_identifier="test-model"
    )
    assert isinstance(provider, LlamaCppProvider)
    assert provider.provider_name == "llama_cpp"


def test_create_provider_llama_cpp_without_base_url_raises_unknown_provider_error() -> None:
    with pytest.raises(UnknownProviderError):
        create_provider("llama_cpp", model_identifier="test-model")


def test_create_provider_llama_cpp_without_model_identifier_raises_unknown_provider_error() -> None:
    with pytest.raises(UnknownProviderError):
        create_provider("llama_cpp", base_url="http://127.0.0.1:8080")


def test_create_provider_unrecognized_string_raises_unknown_provider_error() -> None:
    with pytest.raises(UnknownProviderError):
        create_provider("not-a-real-provider")


def test_create_provider_empty_string_raises_unknown_provider_error() -> None:
    """Boundary: an empty string is not silently treated as "disabled"."""
    with pytest.raises(UnknownProviderError):
        create_provider("")


def test_create_provider_returns_a_fresh_instance_each_call() -> None:
    """Boundary: two calls do not share mutable state (each provider is
    freshly constructed, not a cached singleton)."""
    first = create_provider("mock")
    second = create_provider("mock")
    assert first is not second
