"""The AI provider interface (`AI-01`), matching
`docs/architecture.md` §3/§7: a framework-independent contract package
defining `AIOperation`, the request/response/health-check shapes, a
provider-error hierarchy, and the `AIProvider` Protocol every future
provider (`AI-02` disabled/mock, `AI-03` Ollama) implements against.

No real provider, API endpoint, or UI exists yet — this package is pure
domain-layer logic exercised by stub/fake test providers.
"""

from __future__ import annotations

from .contract import (
    AIOperation,
    AIProvider,
    ProviderConnectionError,
    ProviderError,
    ProviderHealth,
    ProviderInvalidResponseError,
    ProviderRequest,
    ProviderResponse,
    ProviderTimeoutError,
)

__all__ = [
    "AIOperation",
    "AIProvider",
    "ProviderConnectionError",
    "ProviderError",
    "ProviderHealth",
    "ProviderInvalidResponseError",
    "ProviderRequest",
    "ProviderResponse",
    "ProviderTimeoutError",
]
