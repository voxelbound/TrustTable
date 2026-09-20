"""The structured-output contract a caller asks a provider to honor
(`AI-08`, `docs/decision-log.md` D-040).

Lives in `ai_boundary` (not `ai_provider`) because what a model's output
must look like is a trust-boundary concern: the same contract that tells a
provider what to produce is what the caller's validator then enforces.
`ai_provider.contract` re-exports it so provider code has one import point.

Framework-independent: stdlib only.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from .envelope import PromptEnvelope


@dataclass(frozen=True, slots=True)
class OutputContract:
    """A versioned, structurally constrained output contract for one
    request — the alternative to the legacy generic narrative shape.

    Fields:
        name: a stable contract identifier (for example
            `"finding_analysis_v1"`), used as the JSON-schema name a
            constrained-decoding runtime is given.
        json_schema: the JSON Schema (plain mappings/lists/scalars)
            describing exactly the output object. A provider that
            supports grammar-constrained decoding sends it to the
            runtime; a provider that does not still relies on
            `instructions`. The caller's own validator remains the sole
            acceptance authority in every case.
        instructions: the fixed, application-authored text describing the
            output format, appended after `build_safe_prompt`'s own
            unmodified `system_instructions`. Never dataset-derived.
        max_output_tokens: an optional output-token bound for this
            contract (a richer output needs more than a provider's
            default).
        mock_output_factory: builds a schema-valid, grounded default
            output for `MockProvider` from the request's own envelope, so
            the mock provider stays usable for any contract without
            importing the module that defines it.
    """

    name: str
    json_schema: Mapping[str, object]
    instructions: str
    max_output_tokens: int | None = None
    mock_output_factory: Callable[[PromptEnvelope], Mapping[str, object]] | None = None

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("OutputContract.name must not be empty")
        if not self.instructions:
            raise ValueError("OutputContract.instructions must not be empty")
        if self.max_output_tokens is not None and self.max_output_tokens <= 0:
            raise ValueError("OutputContract.max_output_tokens must be positive")


__all__ = ["OutputContract"]
