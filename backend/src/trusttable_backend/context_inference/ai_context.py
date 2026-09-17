"""Validated AI context inference (`CTX-02`) — the "Optional validated
AI context inference" analysis-pipeline step named in
`docs/architecture.md` §6, immediately after `CTX-01`'s deterministic
context hypotheses.

**Enabling slice, not yet wired into the live pipeline** — matching the
precedent already established by `AI-01`/`CTX-01` (built, not yet
called) and `AI-03` (built and registered, "no FastAPI route,
application service, or analysis-pipeline calls it yet"). Nothing in
this module is imported by `analysis.service`, no `AnalysisState` value
changes, and `Analysis.security_exposure` is untouched — no product-
visible behavior changes for any existing analysis. Wiring this into a
real analysis run (and, with it, real `security_exposure` reporting)
remains a separate, later, deliberate step.

Unlike `heuristics.py` (this package's own deterministic-only sibling,
which deliberately imports neither `ai_boundary` nor `ai_provider`),
this module's entire purpose is to call a real `AIProvider` through
`SEC-02`'s existing trust boundary — `ai_boundary`/`ai_provider` imports
here are intentional, not a violation of that sibling module's
structural guarantee.

Design, matching the generic model-output schema `ai_boundary.
validation` already fixes (`narrative`/`referenced_evidence_ids`/
`referenced_columns`/`numeric_claims`/`severity`/`provenance` — no
per-`ContextField` structured shape exists anywhere in this codebase):
an accepted AI response produces exactly one new `ContextHypothesis`
targeting `ContextField.PROBABLE_DOMAIN` (the single-value field this
kind of free-text "what is this dataset" narrative most naturally
fits), at a fixed, disclosed confidence
(`AI_CONTEXT_HYPOTHESIS_CONFIDENCE`) — the schema has no confidence
field for the model to supply one itself. `docs/domain-model.md` §8/§9's
already-fixed field lists are not changed by this package.

`CTX-01`'s already-consolidated `DatasetContext` is serialized into
`PromptEnvelope.confirmed_context` (a `Mapping[str, object]`) rather
than `computed_evidence` — `docs/architecture.md` §7 classifies
`confirmed_context` as untrusted regardless of confirmation state, and
`DatasetContext`'s own fields are not formal `Evidence` objects
(`CTX-01`'s own disclosed limitation). Optional dataset-derived samples
(`sample_sending_enabled`, off by default) are drawn from each column's
already-computed, already-bounded `representative_values` metric
(`PROF-03`) — no raw file re-read, no new data path.

Retry-with-feedback and provider-error handling mirror `ai_benchmark.
runner._run_one_task`'s already-proven pattern exactly (bounded
retries, `ProviderError` isolated into a safe `provider_error` string,
never raised).

Framework-independent besides its two deliberate seams
(`ai_boundary`, `ai_provider`): no FastAPI/SQLAlchemy/pydantic import.
Stdlib only otherwise.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Final

from ..ai_boundary.envelope import (
    DEFAULT_MAX_SAMPLE_COUNT,
    DEFAULT_MAX_SAMPLE_VALUE_LENGTH,
    PromptEnvelope,
    build_prompt_envelope,
)
from ..ai_boundary.validation import RejectionReason, validate_model_output
from ..ai_provider.contract import AIOperation, AIProvider, ProviderError, ProviderRequest
from ..domain.context import ContextField, ContextHypothesis, DatasetContext
from ..domain.evidence import Evidence
from ..domain.value_objects import ColumnReference, Provenance
from ..profiling.schemas import ColumnProfile

AI_CONTEXT_HYPOTHESIS_ID: Final[str] = "ctx-probable_domain-ai-1"

AI_CONTEXT_TASK: Final[str] = (
    "Given the deterministic dataset context supplied below, describe in "
    "one or two sentences what kind of dataset this most likely is, for "
    "a business user. Ground your answer only in the supplied context "
    "and evidence."
)
"""Fixed, application-authored instruction text — never dataset-derived
(`docs/product-requirements.md` §12, `docs/decision-log.md` D-026: a
single bounded call, not an open-ended question)."""

AI_CONTEXT_HYPOTHESIS_CONFIDENCE: Final[float] = 0.65
"""Fixed, disclosed confidence for an accepted AI-sourced
`probable_domain` hypothesis. The generic model-output schema
(`ai_boundary.validation`) has no field for the model to report its own
confidence, so this package assigns one fixed value to every accepted
response — deliberately higher than `heuristics._PROBABLE_DOMAIN_CONFIDENCE`
(`0.5`) so a successful, validated AI narrative wins consolidation over
`CTX-01`'s own narrow single-domain keyword heuristic, but not so high
it could not be reasonably superseded by a future, more specific
signal."""

DEFAULT_MAX_RETRIES: Final[int] = 2
"""Matches `ai_benchmark.BenchmarkConfig.max_retries`'s own default,
for consistency across this codebase's two independent bounded-retry
call sites."""


def _serialize_dataset_context(dataset_context: DatasetContext) -> dict[str, object]:
    """Serialize `dataset_context` into a JSON-safe mapping for
    `PromptEnvelope.confirmed_context`. Tuple values become lists;
    enum values become their string value."""
    fields: dict[str, object] = {}
    for field in ContextField:
        field_value = getattr(dataset_context, field.value)
        value = field_value.value
        fields[field.value] = {
            "value": list(value) if isinstance(value, tuple) else value,
            "confidence": field_value.confidence,
            "confirmation_state": field_value.confirmation_state.value,
        }
    return fields


def _representative_sample(column_profile: ColumnProfile) -> tuple[ColumnReference, str] | None:
    representative_values = column_profile.metrics.get("representative_values")
    if not isinstance(representative_values, tuple) or not representative_values:
        return None
    top_entry = representative_values[0]
    if not isinstance(top_entry, tuple) or len(top_entry) != 2:
        return None
    top_value = top_entry[0]
    if not isinstance(top_value, str):
        return None
    return (column_profile.column, top_value)


def build_context_inference_envelope(
    dataset_context: DatasetContext,
    *,
    evidence: tuple[Evidence, ...] = (),
    column_profiles: tuple[ColumnProfile, ...] = (),
    sample_sending_enabled: bool = False,
    max_sample_count: int = DEFAULT_MAX_SAMPLE_COUNT,
    max_sample_value_length: int = DEFAULT_MAX_SAMPLE_VALUE_LENGTH,
) -> PromptEnvelope:
    """Build the `PromptEnvelope` for a `CONTEXT_INFERENCE` call.

    `dataset_context` (`CTX-01`'s consolidated output) is serialized
    into `confirmed_context`. `evidence` (typically an `Analysis`'s
    already-captured detector `Evidence`, `WP-027`) is forwarded as
    `computed_evidence` unchanged. `raw_samples` are built from
    `column_profiles`' top `representative_values` entry per column —
    empty whenever `sample_sending_enabled` is `False`, matching
    `build_untrusted_samples`'s own structural guarantee.
    """
    raw_samples = [
        sample
        for sample in (_representative_sample(column_profile) for column_profile in column_profiles)
        if sample is not None
    ]
    return build_prompt_envelope(
        task=AI_CONTEXT_TASK,
        computed_evidence=evidence,
        confirmed_context=_serialize_dataset_context(dataset_context),
        raw_samples=raw_samples,
        sample_sending_enabled=sample_sending_enabled,
        max_sample_count=max_sample_count,
        max_sample_value_length=max_sample_value_length,
    )


@dataclass(frozen=True, slots=True)
class ContextInferenceResult:
    """The outcome of one `run_context_inference` call.

    `accepted=True` always carries a `hypothesis` and no rejection
    reasons/provider error; `accepted=False` never carries a
    `hypothesis`.
    """

    accepted: bool
    hypothesis: ContextHypothesis | None
    rejection_reasons: tuple[RejectionReason, ...]
    provider_error: str | None
    retries_used: int

    def __post_init__(self) -> None:
        if self.accepted and self.hypothesis is None:
            raise ValueError("ContextInferenceResult.hypothesis must be set when accepted")
        if not self.accepted and self.hypothesis is not None:
            raise ValueError("ContextInferenceResult.hypothesis must be None when not accepted")
        if self.retries_used < 0:
            raise ValueError("ContextInferenceResult.retries_used must not be negative")


def _build_hypothesis(narrative: str, referenced_columns: object) -> ContextHypothesis:
    rationale = f"AI-generated narrative, validated by SEC-02 (accepted): {narrative}"
    if isinstance(referenced_columns, list | tuple) and referenced_columns:
        rationale += f" (referenced columns: {', '.join(str(c) for c in referenced_columns)})"
    return ContextHypothesis(
        hypothesis_id=AI_CONTEXT_HYPOTHESIS_ID,
        context_field=ContextField.PROBABLE_DOMAIN,
        proposed_value=narrative,
        confidence=AI_CONTEXT_HYPOTHESIS_CONFIDENCE,
        provenance=Provenance.AI_INTERPRETATION,
        related_columns=(),
        evidence_ids=(),
        rationale=rationale,
    )


def run_context_inference(
    provider: AIProvider,
    envelope: PromptEnvelope,
    *,
    max_retries: int = DEFAULT_MAX_RETRIES,
) -> ContextInferenceResult:
    """Call `provider` for `AIOperation.CONTEXT_INFERENCE` against
    `envelope`, validating the response and retrying with feedback on
    rejection, up to `max_retries` additional attempts. Never raises —
    a `ProviderError` (connection failure, timeout, malformed response)
    is isolated into a safe `provider_error` string and the call stops
    immediately (a transport failure is not correctable by validation
    feedback, matching `ai_benchmark.runner`'s own precedent).
    """
    request = ProviderRequest(
        operation=AIOperation.CONTEXT_INFERENCE,
        envelope=envelope,
        known_numeric_facts={},
    )
    retries_used = 0
    while True:
        try:
            response = provider.complete(request)
        except ProviderError as exc:
            return ContextInferenceResult(
                accepted=False,
                hypothesis=None,
                rejection_reasons=(),
                provider_error=f"{type(exc).__name__}: {exc}",
                retries_used=retries_used,
            )
        outcome = validate_model_output(response.raw_output, envelope, known_numeric_facts={})
        if outcome.accepted:
            narrative = response.raw_output.get("narrative")
            assert isinstance(narrative, str)  # guaranteed by validate_model_output acceptance
            hypothesis = _build_hypothesis(narrative, response.raw_output.get("referenced_columns"))
            return ContextInferenceResult(
                accepted=True,
                hypothesis=hypothesis,
                rejection_reasons=(),
                provider_error=None,
                retries_used=retries_used,
            )
        if retries_used >= max_retries:
            return ContextInferenceResult(
                accepted=False,
                hypothesis=None,
                rejection_reasons=outcome.rejection_reasons,
                provider_error=None,
                retries_used=retries_used,
            )
        request = replace(request, retry_feedback=outcome.safe_summary)
        retries_used += 1


def combine_hypotheses(
    existing: tuple[ContextHypothesis, ...], result: ContextInferenceResult
) -> tuple[ContextHypothesis, ...]:
    """Append `result.hypothesis` to `existing` when accepted; return
    `existing` unchanged otherwise. The combined tuple is intended for
    `context_inference.heuristics.consolidate_dataset_context` — CTX-01's
    own consolidation logic is reused unmodified, not duplicated."""
    if result.accepted and result.hypothesis is not None:
        return (*existing, result.hypothesis)
    return existing


__all__ = [
    "AI_CONTEXT_HYPOTHESIS_CONFIDENCE",
    "AI_CONTEXT_HYPOTHESIS_ID",
    "AI_CONTEXT_TASK",
    "DEFAULT_MAX_RETRIES",
    "ContextInferenceResult",
    "build_context_inference_envelope",
    "combine_hypotheses",
    "run_context_inference",
]
