"""The provider factory (`AI-02`/`AI-03`).

`create_provider` turns a plain `llm_provider` string into a concrete
`AIProvider`. It takes plain arguments, not `config.Settings` —
`config.py` is a `pydantic_settings.BaseSettings`, and importing it here
would pull `pydantic` into `ai_provider`, breaking the framework-
independence `AI-01` already established and tested for (`WP-030`
Recorded assumption 6). A future FastAPI-layer caller already holds
`settings.llm_provider`/`llm_base_url`/`llm_model`/`llm_timeout_seconds`/
`llm_temperature` as plain values at the point it calls this factory.

`base_url`/`model_identifier`/`timeout_seconds`/`temperature`/
`max_tokens` are only used when `llm_provider == "llama_cpp"` (`AI-03`)
— they are accepted as optional keyword arguments so `disabled`/`mock`
callers are unaffected. Constructing `"llama_cpp"` without `base_url`/
`model_identifier` raises `ValueError` (from `LlamaCppProvider.
__init__` itself) rather than silently falling back to a placeholder.

Framework-independent: no FastAPI/SQLAlchemy/pydantic import. Stdlib
only, plus `LlamaCppProvider`'s own already-declared `httpx` dependency.
"""

from __future__ import annotations

from .contract import AIProvider
from .disabled import DisabledProvider
from .llama_cpp import LlamaCppProvider
from .mock import MockProvider


class UnknownProviderError(ValueError):
    """Raised when `llm_provider` names a provider this factory does not
    construct — any value other than `"disabled"`, `"mock"`, or
    `"llama_cpp"` (`docs/decision-log.md` D-035).
    """


def create_provider(
    llm_provider: str,
    *,
    base_url: str | None = None,
    model_identifier: str | None = None,
    timeout_seconds: float = 120.0,
    temperature: float = 0.0,
    max_tokens: int = 512,
) -> AIProvider:
    """Construct the concrete `AIProvider` for `llm_provider`.

    `llm_provider` is expected to already be one of `config.py`'s
    `LlmProvider` literal values (`"disabled"`, `"mock"`, `"llama_cpp"`),
    validated by `Settings` before this function is ever called; this
    function does not re-validate that shape, only dispatches on it.
    """
    if llm_provider == "disabled":
        return DisabledProvider()
    if llm_provider == "mock":
        return MockProvider()
    if llm_provider == "llama_cpp":
        if not base_url or not model_identifier:
            raise UnknownProviderError(
                "llm_provider='llama_cpp' requires base_url and model_identifier "
                "(e.g. from Settings.llm_base_url/llm_model); neither may be empty."
            )
        return LlamaCppProvider(
            base_url=base_url,
            model_identifier=model_identifier,
            timeout_seconds=timeout_seconds,
            temperature=temperature,
            max_tokens=max_tokens,
        )
    raise UnknownProviderError(f"Unrecognized llm_provider: {llm_provider!r}")


__all__ = ["UnknownProviderError", "create_provider"]
