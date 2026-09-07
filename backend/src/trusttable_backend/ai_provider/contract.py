"""The AI provider interface (`AI-01`), matching
`docs/implementation-backlog.md#AI-01` and `docs/product-requirements.md`
§12: a closed `AIOperation` enumeration for the six model-call operations,
request/response/health-check shapes built directly on `SEC-02`'s
existing `ai_boundary` contract, a provider-error hierarchy, and the
`AIProvider` Protocol every future provider (`AI-02` disabled/mock,
`AI-03` Ollama) implements against.

No real provider exists yet — this package only defines the seam future
provider packages plug into, the same relationship `DET-01`'s `Detector`
Protocol has to `DET-02`'s real detectors.

Framework-independent: no FastAPI/SQLAlchemy/httpx/requests import.
Stdlib only, plus reuse of `ai_boundary`'s own stdlib-only types.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable

from ..ai_boundary.envelope import PromptEnvelope


class AIOperation(StrEnum):
    """The six model-call operations `docs/product-requirements.md` §12
    lists ("Model calls may cover: 1. context inference 2. guided
    questions 3. finding explanations 4. remediation 5. rule
    descriptions 6. report summary"). Health check is a separate
    `AIProvider.health_check()` capability, not a value here — see the
    work package's Recorded assumption 2.
    """

    CONTEXT_INFERENCE = "context_inference"
    GUIDED_QUESTIONS = "guided_questions"
    FINDING_EXPLANATION = "finding_explanation"
    REMEDIATION = "remediation"
    RULE_DESCRIPTION = "rule_description"
    REPORT_SUMMARY = "report_summary"


@dataclass(frozen=True, slots=True)
class ProviderHealth:
    """The result of `AIProvider.health_check()` — a liveness/
    availability probe, structurally distinct from `ProviderResponse`
    (which carries a narrative payload meant for `validate_model_output`).
    """

    available: bool
    provider_name: str
    model_identifier: str
    detail: str

    def __post_init__(self) -> None:
        if not self.provider_name:
            raise ValueError("ProviderHealth.provider_name must not be empty")


@dataclass(frozen=True, slots=True)
class ProviderRequest:
    """One request to `AIProvider.complete()`.

    `envelope` is exactly `SEC-02`'s `PromptEnvelope` — untrusted content
    can only reach a future provider implementation through this seam.
    `known_numeric_facts` is forwarded unchanged to a caller's later
    `validate_model_output` call; it is not used by this package directly.
    `retry_feedback`, when set, carries validation feedback from a prior
    rejected attempt (`docs/product-requirements.md` §12's "may be
    retried with validation feedback") — the retry *loop* itself is a
    future orchestration package's responsibility, not this interface.
    """

    operation: AIOperation
    envelope: PromptEnvelope
    known_numeric_facts: Mapping[str, float]
    retry_feedback: str | None = None


@dataclass(frozen=True, slots=True)
class ProviderResponse:
    """One response from `AIProvider.complete()`.

    `raw_output` is exactly the `Mapping[str, object]` shape
    `ai_boundary.validation.validate_model_output` already accepts —
    reused directly rather than duplicated (see the work package's
    Recorded assumption 1).
    """

    raw_output: Mapping[str, object]
    provider_name: str
    model_identifier: str
    duration_ms: float

    def __post_init__(self) -> None:
        if not self.provider_name:
            raise ValueError("ProviderResponse.provider_name must not be empty")
        if self.duration_ms < 0:
            raise ValueError("ProviderResponse.duration_ms must not be negative")


class ProviderError(Exception):
    """Common base of every real-provider failure mode this interface
    distinguishes. Not exhaustive by design — a stub's own
    `NotImplementedError` is ordinary Python, not part of this closed
    hierarchy (a stub is test-only scaffolding, not a real provider
    failure mode).
    """


class ProviderTimeoutError(ProviderError):
    """The provider did not respond within the configured timeout
    (`Settings.llm_timeout_seconds`, `FND-02`)."""


class ProviderConnectionError(ProviderError):
    """The provider could not be reached at all (e.g. connection refused,
    DNS failure, unreachable host)."""


class ProviderInvalidResponseError(ProviderError):
    """The provider responded, but the response could not be parsed into
    `ProviderResponse.raw_output` at all (a structurally malformed
    response *is* still validated by `validate_model_output` once parsed
    into a `Mapping` — this exception is for responses that cannot even
    reach that point, e.g. non-JSON output from an HTTP-based provider).
    """


@runtime_checkable
class AIProvider(Protocol):
    """The structural contract every future provider (`AI-02` disabled/
    mock, `AI-03` Ollama) implements. A single generic `complete()`
    method tagged by `AIOperation`, mirroring `DET-01`'s own
    `Detector.supports`/`run` precedent (one Protocol surface used by
    every concrete implementation regardless of category) rather than
    seven distinct per-operation methods — see the work package's
    Recorded assumption 3.
    """

    @property
    def provider_name(self) -> str: ...

    def health_check(self) -> ProviderHealth: ...

    def complete(self, request: ProviderRequest) -> ProviderResponse: ...


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
