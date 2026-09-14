"""The AI provider interface and providers (`AI-01`/`AI-02`), matching
`docs/architecture.md` §3/§7: a framework-independent contract package
defining `AIOperation`, the request/response/health-check shapes, a
provider-error hierarchy, and the `AIProvider` Protocol every provider
implements against (`AI-01`); the two non-real concrete providers
`DisabledProvider`/`MockProvider` and the `create_provider` factory that
selects between them (`AI-02`).

No real provider, API endpoint, or UI exists yet — `AI-03` (the real
local-inference provider) remains open, pending the human-owned
runtime/model/quantization decision gate (`D-007`'s review note,
`D-030`-`D-033`); `API-02`/`UI-02` remain later, separate packages.
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
from .disabled import DISABLED_PROVIDER_NAME, DisabledProvider
from .factory import UnknownProviderError, create_provider
from .mock import MOCK_PROVIDER_NAME, MockProvider, ResponseFactory, default_mock_raw_output

__all__ = [
    "AIOperation",
    "AIProvider",
    "DISABLED_PROVIDER_NAME",
    "DisabledProvider",
    "MOCK_PROVIDER_NAME",
    "MockProvider",
    "ProviderConnectionError",
    "ProviderError",
    "ProviderHealth",
    "ProviderInvalidResponseError",
    "ProviderRequest",
    "ProviderResponse",
    "ProviderTimeoutError",
    "ResponseFactory",
    "UnknownProviderError",
    "create_provider",
    "default_mock_raw_output",
]
