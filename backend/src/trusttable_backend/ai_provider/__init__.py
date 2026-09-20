"""The AI provider interface and providers (`AI-01`/`AI-02`/`AI-03`),
matching `docs/architecture.md` §3/§7: a framework-independent contract
package defining `AIOperation`, the request/response/health-check
shapes, a provider-error hierarchy, and the `AIProvider` Protocol every
provider implements against (`AI-01`); the two non-real concrete
providers `DisabledProvider`/`MockProvider` (`AI-02`); the real
local-inference provider `LlamaCppProvider` for `llama.cpp`'s
`llama-server` (`AI-03`, `docs/decision-log.md` D-034/D-035); and the
`create_provider` factory that selects between all three.

The API route layer calls a provider through `create_provider`
(`UI-02`, `AI-08`); no application service or analysis-pipeline stage does.
`Settings.llm_provider`'s default remains `"disabled"`. `display.py`
(`AI-08`) turns a provider name and raw model identifier into the
path-free labels normal user-facing surfaces may show.
"""

from __future__ import annotations

from .contract import (
    AIOperation,
    AIProvider,
    OutputContract,
    ProviderConnectionError,
    ProviderError,
    ProviderHealth,
    ProviderInvalidResponseError,
    ProviderRequest,
    ProviderResponse,
    ProviderTimeoutError,
)
from .disabled import DISABLED_PROVIDER_NAME, DisabledProvider
from .display import (
    AiProvenanceDisplay,
    ModelDescription,
    describe_model,
    describe_provenance,
    sanitize_model_identifier,
)
from .factory import UnknownProviderError, create_provider
from .llama_cpp import LLAMA_CPP_PROVIDER_NAME, LlamaCppProvider
from .mock import MOCK_PROVIDER_NAME, MockProvider, ResponseFactory, default_mock_raw_output

__all__ = [
    "AIOperation",
    "AIProvider",
    "AiProvenanceDisplay",
    "DISABLED_PROVIDER_NAME",
    "DisabledProvider",
    "LLAMA_CPP_PROVIDER_NAME",
    "LlamaCppProvider",
    "MOCK_PROVIDER_NAME",
    "MockProvider",
    "ModelDescription",
    "OutputContract",
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
    "describe_model",
    "describe_provenance",
    "sanitize_model_identifier",
]
