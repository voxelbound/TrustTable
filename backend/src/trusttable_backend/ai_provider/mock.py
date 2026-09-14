"""The mock AI provider (`AI-02`) — "support adversarial mock output"
(`docs/implementation-backlog.md#AI-02`).

`MockProvider` is the concrete `AIProvider` a future caller constructs
(via `factory.create_provider`) when `Settings.llm_provider == "mock"`.
It never contacts a real model; `complete()` returns:

1. a caller-supplied dynamic `response_factory(request) -> raw_output`,
   if given (highest precedence) — the seam that makes "adversarial
   mock output" possible: a caller can inspect the request's untrusted
   dataset samples and craft a response that attempts to follow
   embedded instructions (`docs/testing-strategy.md` §3's "mock model
   may attempt to follow the injection"), which `ai_boundary.validation.
   validate_model_output` is then proven to reject;
2. a caller-supplied static `raw_output`, if given;
3. otherwise, `default_mock_raw_output(request)` — a minimal,
   schema-valid response guaranteed to be **accepted** by
   `validate_model_output` regardless of the request's contents.

Framework-independent: no FastAPI/SQLAlchemy/pydantic import. Stdlib
only, plus reuse of `ai_provider.contract` and `ai_boundary.validation`'s
own stdlib-only types.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

from ..ai_boundary.validation import MODEL_OUTPUT_SCHEMA_VERSION
from ..domain.value_objects import Provenance
from .contract import ProviderHealth, ProviderRequest, ProviderResponse

#: `AIProvider.provider_name` for this provider, and the `Settings.
#: llm_provider` value (`config.py`, `FND-02`) it corresponds to.
MOCK_PROVIDER_NAME = "mock"

#: A caller-supplied function that turns one `ProviderRequest` into a
#: raw model-output mapping. Receives exactly the `ProviderRequest`
#: `complete()` was called with — never anything beyond what a real
#: provider would see — so an adversarial factory can only "attempt to
#: follow" what is actually present in `request.envelope`.
ResponseFactory = Callable[[ProviderRequest], Mapping[str, object]]


def default_mock_raw_output(request: ProviderRequest) -> dict[str, object]:
    """A minimal, always schema-valid raw output for `request`.

    Deliberately omits every optional key (`referenced_evidence_ids`,
    `referenced_columns`, `numeric_claims`, `severity`) rather than
    referencing `request.envelope.computed_evidence` — this keeps the
    default valid for *any* request, including one with no evidence at
    all, without needing to inspect its contents.
    """
    return {
        "schema_version": MODEL_OUTPUT_SCHEMA_VERSION,
        "narrative": f"Mock response for operation '{request.operation.value}'.",
        "provenance": Provenance.AI_INTERPRETATION.value,
    }


class MockProvider:
    """`AIProvider` for `llm_provider == "mock"` — always available,
    configurable output (`AI-02`).

    Satisfies the `AIProvider` Protocol structurally (`AI-01`,
    `contract.py`) — no explicit inheritance required.
    """

    def __init__(
        self,
        *,
        raw_output: Mapping[str, object] | None = None,
        response_factory: ResponseFactory | None = None,
        model_identifier: str = "mock-v1",
        duration_ms: float = 0.0,
    ) -> None:
        self._raw_output = raw_output
        self._response_factory = response_factory
        self._model_identifier = model_identifier
        self._duration_ms = duration_ms

    @property
    def provider_name(self) -> str:
        return MOCK_PROVIDER_NAME

    def health_check(self) -> ProviderHealth:
        return ProviderHealth(
            available=True,
            provider_name=self.provider_name,
            model_identifier=self._model_identifier,
            detail="Mock provider: deterministic/configurable output for testing, no real model.",
        )

    def complete(self, request: ProviderRequest) -> ProviderResponse:
        if self._response_factory is not None:
            raw_output = self._response_factory(request)
        elif self._raw_output is not None:
            raw_output = self._raw_output
        else:
            raw_output = default_mock_raw_output(request)
        return ProviderResponse(
            raw_output=raw_output,
            provider_name=self.provider_name,
            model_identifier=self._model_identifier,
            duration_ms=self._duration_ms,
        )


__all__ = [
    "MOCK_PROVIDER_NAME",
    "MockProvider",
    "ResponseFactory",
    "default_mock_raw_output",
]
