"""The disabled AI provider (`AI-02`).

`docs/decision-log.md` D-006 "Complete AI-disabled mode": TrustTable
remains fully functional without a model. `DisabledProvider` is the
concrete `AIProvider` a future caller constructs (via `factory.
create_provider`) when `Settings.llm_provider == "disabled"`.

Its `health_check()` always reports unavailable, which is the signal a
well-behaved caller checks before ever calling `complete()` — matching
`docs/architecture.md` §7's "route handlers do not call Ollama
directly" seam, applied here to the disabled case too. If `complete()`
is called anyway, it raises `ProviderConnectionError`: a disabled
provider is, by definition, unreachable, the same failure mode a real
caller already has to handle for a genuinely-unreachable provider.

Framework-independent: no FastAPI/SQLAlchemy/pydantic import. Stdlib
only, plus reuse of `ai_provider.contract`'s own stdlib-only types.
"""

from __future__ import annotations

from .contract import ProviderConnectionError, ProviderHealth, ProviderRequest, ProviderResponse

#: `AIProvider.provider_name` for this provider, and the `Settings.
#: llm_provider` value (`config.py`, `FND-02`) it corresponds to.
DISABLED_PROVIDER_NAME = "disabled"


class DisabledProvider:
    """`AIProvider` for `llm_provider == "disabled"` (`D-006`).

    Satisfies the `AIProvider` Protocol structurally (`AI-01`,
    `contract.py`) — no explicit inheritance required.
    """

    @property
    def provider_name(self) -> str:
        return DISABLED_PROVIDER_NAME

    def health_check(self) -> ProviderHealth:
        return ProviderHealth(
            available=False,
            provider_name=self.provider_name,
            model_identifier="",
            detail="AI is disabled (llm_provider=disabled); no model is configured.",
        )

    def complete(self, request: ProviderRequest) -> ProviderResponse:
        raise ProviderConnectionError(
            "The disabled provider cannot complete any request. A caller "
            "must check health_check().available (or the configured "
            "llm_provider) before calling complete()."
        )


__all__ = ["DISABLED_PROVIDER_NAME", "DisabledProvider"]
