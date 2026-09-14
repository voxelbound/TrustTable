"""Tests for the provider factory (`AI-02`).

Covers this package's acceptance criterion AC-07: positive, negative,
and boundary cases for `create_provider`.
"""

from __future__ import annotations

import pytest

from trusttable_backend.ai_provider.disabled import DisabledProvider
from trusttable_backend.ai_provider.factory import UnknownProviderError, create_provider
from trusttable_backend.ai_provider.mock import MockProvider


def test_create_provider_disabled_returns_disabled_provider() -> None:
    provider = create_provider("disabled")
    assert isinstance(provider, DisabledProvider)
    assert provider.provider_name == "disabled"


def test_create_provider_mock_returns_mock_provider() -> None:
    provider = create_provider("mock")
    assert isinstance(provider, MockProvider)
    assert provider.provider_name == "mock"


def test_create_provider_ollama_raises_unknown_provider_error_naming_ai_03() -> None:
    with pytest.raises(UnknownProviderError) as excinfo:
        create_provider("ollama")
    assert "AI-03" in str(excinfo.value)


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
