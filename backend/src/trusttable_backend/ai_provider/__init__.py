"""The AI provider interface and providers (`AI-01`/`AI-02`/`AI-03`),
matching `docs/architecture.md` §3/§7: a framework-independent contract
package defining `AIOperation`, the request/response/health-check
shapes, a provider-error hierarchy, and the `AIProvider` Protocol every
provider implements against (`AI-01`); the two non-real concrete
providers `DisabledProvider`/`MockProvider` (`AI-02`); the real
local-inference provider `LlamaCppProvider` for `llama.cpp`'s
`llama-server` (`AI-03`, `docs/decision-log.md` D-034/D-035); and the
`create_provider` factory that selects between all three.

No FastAPI route, application service, or analysis-pipeline calls any
provider yet — `Settings.llm_provider`'s default remains `"disabled"`;
`API-02`/`UI-02`/`CTX-01`/`CTX-02`/`CTX-03` remain later, separate
packages.
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
from .llama_cpp import LLAMA_CPP_PROVIDER_NAME, LlamaCppProvider
from .mock import MOCK_PROVIDER_NAME, MockProvider, ResponseFactory, default_mock_raw_output

__all__ = [
    "AIOperation",
    "AIProvider",
    "DISABLED_PROVIDER_NAME",
    "DisabledProvider",
    "LLAMA_CPP_PROVIDER_NAME",
    "LlamaCppProvider",
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
