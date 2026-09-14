"""The provider factory (`AI-02`).

`create_provider` turns a plain `llm_provider` string into a concrete
`AIProvider`. It takes a plain `str`, not `config.Settings` —
`config.py` is a `pydantic_settings.BaseSettings`, and importing it here
would pull `pydantic` into `ai_provider`, breaking the framework-
independence `AI-01` already established and tested for (`WP-030`
Recorded assumption 6). A future FastAPI-layer caller already holds
`settings.llm_provider` as a plain string at the point it calls this
factory.

Framework-independent: no FastAPI/SQLAlchemy/pydantic import. Stdlib
only.
"""

from __future__ import annotations

from .contract import AIProvider
from .disabled import DisabledProvider
from .mock import MockProvider


class UnknownProviderError(ValueError):
    """Raised when `llm_provider` names a provider this factory does not
    (yet) construct — either `"ollama"` (`AI-03`, not implemented yet,
    pending the human-owned runtime decision gate, `D-007`'s review
    note, `D-030`-`D-033`) or any unrecognized value.
    """


def create_provider(llm_provider: str) -> AIProvider:
    """Construct the concrete `AIProvider` for `llm_provider`.

    `llm_provider` is expected to already be one of `config.py`'s
    `LlmProvider` literal values (`"disabled"`, `"mock"`, `"ollama"`),
    validated by `Settings` before this function is ever called; this
    function does not re-validate that shape, only dispatches on it.
    """
    if llm_provider == "disabled":
        return DisabledProvider()
    if llm_provider == "mock":
        return MockProvider()
    if llm_provider == "ollama":
        raise UnknownProviderError(
            "llm_provider='ollama' is not yet implemented (AI-03 is "
            "pending the human-owned runtime/model/quantization decision "
            "gate); no provider was constructed."
        )
    raise UnknownProviderError(f"Unrecognized llm_provider: {llm_provider!r}")


__all__ = ["UnknownProviderError", "create_provider"]
