"""Validated AI finding explanations (`AI-05`) — the "finding
explanations" model call `docs/product-requirements.md` §12 names
(`AIOperation.FINDING_EXPLANATION`, already defined by `AI-01`).

**Enabling slice, not yet wired into the live pipeline** — matching the
precedent already established by `CTX-02` (built, not yet called) and
every prior `AI-0x` package. Nothing in this module is imported by
`analysis.service`, no `AnalysisState` value changes, and
`Analysis.security_exposure` is untouched — no product-visible behavior
changes for any existing analysis.

Unlike `deterministic.py` (this package's own deterministic-only
sibling, which deliberately imports neither `ai_boundary` nor
`ai_provider`), this module's entire purpose is to call a real
`AIProvider` through `SEC-02`'s existing trust boundary —
`ai_boundary`/`ai_provider` imports here are intentional.

`AI-05`'s own backlog rejection list ("Reject: unknown evidence, unknown
columns, incorrect numbers, removal of findings, replacement of risk
score") needs no new enforcement code here: `ai_boundary.validation.
validate_model_output` already enforces every one of those rules
structurally for any `AIOperation`, and its validated schema has no
field capable of expressing finding removal or score replacement at
all. This module reuses that boundary unmodified.

`_known_numeric_facts_from_evidence` mirrors `ai_benchmark.fixtures.
_known_numeric_facts_from_evidence`'s already-proven fail-closed
collision logic exactly, kept as its own small owned copy (this
codebase's established per-package-helper convention — see e.g. `AI-03`'s
`llama_cpp.py` vs. the benchmark-only `llama_cpp_http.py` adapter,
deliberately separate) rather than importing from `ai_benchmark`, an
unrelated package this package does not otherwise depend on.

Retry-with-feedback and provider-error handling mirror
`context_inference.ai_context.run_context_inference`'s already-proven
pattern exactly (bounded retries, `ProviderError` isolated into a safe
`provider_error` string, never raised).

Framework-independent besides its two deliberate seams (`ai_boundary`,
`ai_provider`): no FastAPI/SQLAlchemy/pydantic import. Stdlib only
otherwise.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Final

from ..ai_boundary.envelope import PromptEnvelope, build_prompt_envelope
from ..ai_boundary.validation import RejectionReason, validate_model_output
from ..ai_provider.contract import AIOperation, AIProvider, ProviderError, ProviderRequest
from ..detectors.contract import FindingCandidate
from ..domain.evidence import Evidence
from ..domain.explanation import FindingExplanation
from ..domain.value_objects import ColumnReference, Provenance

AI_EXPLANATION_TASK: Final[str] = (
    "Given the deterministic finding and its supporting evidence supplied "
    "below, explain in one or two sentences what this finding means for a "
    "business user and why it matters. Ground your answer only in the "
    "supplied finding and evidence."
)
"""Fixed, application-authored instruction text — never dataset-derived
(`docs/product-requirements.md` §12, mirrors `context_inference.
ai_context.AI_CONTEXT_TASK`'s own precedent: a single bounded call, not
an open-ended question)."""

DEFAULT_MAX_RETRIES: Final[int] = 2
"""Matches `context_inference.ai_context.DEFAULT_MAX_RETRIES`'s and
`ai_benchmark.BenchmarkConfig.max_retries`'s own default, for
consistency across this codebase's independent bounded-retry call
sites."""


def _known_numeric_facts_from_evidence(evidence: tuple[Evidence, ...]) -> dict[str, float]:
    """Derive a flat `known_numeric_facts` allow-list from the numeric
    fields of each included `Evidence.structured_payload`, aggregated by
    original field name. See module docstring: mirrors `ai_benchmark.
    fixtures._known_numeric_facts_from_evidence` exactly, including its
    fail-closed collision rule (a field name with conflicting values
    across evidence items is omitted entirely, never last-write-wins).
    """
    values: dict[str, float] = {}
    ambiguous: set[str] = set()
    for item in evidence:
        for key, raw_value in item.structured_payload.items():
            if isinstance(raw_value, bool) or not isinstance(raw_value, int | float):
                continue
            if key in ambiguous:
                continue
            numeric_value = float(raw_value)
            if key not in values:
                values[key] = numeric_value
            elif values[key] != numeric_value:
                ambiguous.add(key)
                del values[key]
    return values


def build_finding_explanation_envelope(
    finding: FindingCandidate,
    evidence: tuple[Evidence, ...],
) -> PromptEnvelope:
    """Build the `PromptEnvelope` for a `FINDING_EXPLANATION` call about
    `finding`.

    `evidence` (typically resolved via `analysis.service.
    get_finding_evidence`, `WP-027`) is forwarded as `computed_evidence`
    unchanged. This package sends zero dataset samples — disclosed, not
    silently assumed (a finding's own evidence is already the grounding
    a business-facing explanation needs).
    """
    return build_prompt_envelope(task=AI_EXPLANATION_TASK, computed_evidence=evidence)


@dataclass(frozen=True, slots=True)
class FindingExplanationResult:
    """The outcome of one `run_finding_explanation` call.

    `accepted=True` always carries an `explanation` and no rejection
    reasons/provider error; `accepted=False` never carries an
    `explanation`.
    """

    accepted: bool
    explanation: FindingExplanation | None
    rejection_reasons: tuple[RejectionReason, ...]
    provider_error: str | None
    retries_used: int

    def __post_init__(self) -> None:
        if self.accepted and self.explanation is None:
            raise ValueError("FindingExplanationResult.explanation must be set when accepted")
        if not self.accepted and self.explanation is not None:
            raise ValueError("FindingExplanationResult.explanation must be None when not accepted")
        if self.retries_used < 0:
            raise ValueError("FindingExplanationResult.retries_used must not be negative")


def _grounded_columns(evidence: tuple[Evidence, ...]) -> tuple[ColumnReference, ...]:
    """The full set of columns `evidence` is actually grounded in,
    deduplicated in first-seen order.

    Deliberately not derived from the model's own `referenced_columns`
    reply: that field is validated only as a set of already-known
    column-key *strings* (`ai_boundary.validation`), not full
    `ColumnReference` objects, so it cannot be safely round-tripped into
    `FindingExplanation.referenced_columns`'s typed shape. Mirrors
    `context_inference.ai_context._build_hypothesis`'s own precedent of
    leaving the structured column field independent of the model's raw
    reply — grounding stays exact against what was actually sent, not
    what the model claims to have used.
    """
    seen: dict[str, ColumnReference] = {}
    for item in evidence:
        for column in item.affected_columns:
            seen.setdefault(column.internal_key, column)
    return tuple(seen.values())


def _build_explanation(
    narrative: str,
    evidence: tuple[Evidence, ...],
    *,
    provider_name: str,
    model_identifier: str,
) -> FindingExplanation:
    return FindingExplanation(
        narrative=narrative,
        provenance=Provenance.AI_INTERPRETATION,
        referenced_evidence_ids=tuple(item.evidence_id for item in evidence),
        referenced_columns=_grounded_columns(evidence),
        provider_name=provider_name,
        model_identifier=model_identifier,
    )


def run_finding_explanation(
    provider: AIProvider,
    envelope: PromptEnvelope,
    evidence: tuple[Evidence, ...],
    *,
    max_retries: int = DEFAULT_MAX_RETRIES,
) -> FindingExplanationResult:
    """Call `provider` for `AIOperation.FINDING_EXPLANATION` against
    `envelope`, validating the response and retrying with feedback on
    rejection, up to `max_retries` additional attempts. Never raises —
    a `ProviderError` (connection failure, timeout, malformed response)
    is isolated into a safe `provider_error` string and the call stops
    immediately, mirroring `context_inference.ai_context.
    run_context_inference`'s own established pattern exactly.

    `known_numeric_facts` is derived from `evidence` via
    `_known_numeric_facts_from_evidence` and forwarded to
    `validate_model_output`, so a model's numeric claims about the
    finding are checked against what was actually sent.
    """
    known_numeric_facts = _known_numeric_facts_from_evidence(evidence)
    request = ProviderRequest(
        operation=AIOperation.FINDING_EXPLANATION,
        envelope=envelope,
        known_numeric_facts=known_numeric_facts,
    )
    retries_used = 0
    while True:
        try:
            response = provider.complete(request)
        except ProviderError as exc:
            return FindingExplanationResult(
                accepted=False,
                explanation=None,
                rejection_reasons=(),
                provider_error=f"{type(exc).__name__}: {exc}",
                retries_used=retries_used,
            )
        outcome = validate_model_output(
            response.raw_output, envelope, known_numeric_facts=known_numeric_facts
        )
        if outcome.accepted:
            narrative = response.raw_output.get("narrative")
            assert isinstance(narrative, str)  # guaranteed by validate_model_output acceptance
            explanation = _build_explanation(
                narrative,
                evidence,
                provider_name=response.provider_name,
                model_identifier=response.model_identifier,
            )
            return FindingExplanationResult(
                accepted=True,
                explanation=explanation,
                rejection_reasons=(),
                provider_error=None,
                retries_used=retries_used,
            )
        if retries_used >= max_retries:
            return FindingExplanationResult(
                accepted=False,
                explanation=None,
                rejection_reasons=outcome.rejection_reasons,
                provider_error=None,
                retries_used=retries_used,
            )
        request = replace(request, retry_feedback=outcome.safe_summary)
        retries_used += 1


__all__ = [
    "AI_EXPLANATION_TASK",
    "DEFAULT_MAX_RETRIES",
    "FindingExplanationResult",
    "build_finding_explanation_envelope",
    "run_finding_explanation",
]
