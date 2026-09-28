"""AI-assisted rule generation (`RULE-02` slice 2, `WP-081`) — the
provider-calling seam for the one detector category slice 1
(`rules/generation.py`, `WP-080`) deliberately left unmapped for a
reason AI can actually resolve: `consistency.inconsistent_capitalization`,
whose own evidence already deterministically enumerates every valid
candidate value (`distinct_casings`), so the only remaining judgment —
which is canonical — is a genuine choice.

`build_rule_generation_envelope`/`run_rule_generation` below send that
finding's own evidence (never a fresh calculation, never a dataset
sample) and ask the model to choose exactly one candidate from a
closed, per-request-enumerated set (`ai_boundary.rule_generation`) — it
cannot invent a value.

**Wired into a real, live HTTP route** (`GET .../findings/{finding_id}/
rule-proposal`) — the route layer, not `analysis.service`, calls this
module, mirroring `explanation.ai_explanation`'s own established
`docs/decision-log.md` D-037/D-038 boundary exactly: nothing here is
imported by `analysis.service`, no `AnalysisState` value changes, and
`Analysis.security_exposure` is untouched.

Unlike `rules/generation.py` (this package's deterministic-only
sibling, which deliberately imports neither `ai_boundary` nor
`ai_provider`), this module's purpose is to call a real `AIProvider`
through `SEC-02`'s trust boundary — those imports are intentional.

Framework-independent besides its two deliberate seams (`ai_boundary`,
`ai_provider`): no FastAPI/SQLAlchemy/pydantic import. Stdlib
otherwise.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from ..ai_boundary.envelope import PromptEnvelope, build_prompt_envelope
from ..ai_boundary.rule_generation import (
    RuleGenerationRejectionReason,
    build_rule_generation_contract,
    validate_rule_generation_output,
)
from ..ai_provider.contract import AIOperation, AIProvider, ProviderError, ProviderRequest
from ..detectors.contract import FindingCandidate
from ..domain.evidence import Evidence

#: `docs/product-requirements.md` §12 names "rule descriptions" as one
#: of the six model-call operations this call reuses — choosing a
#: canonical value for a proposed rule's own parameter is that
#: operation, not a new one.
_OPERATION: Final[AIOperation] = AIOperation.RULE_DESCRIPTION

RULE_GENERATION_TASK: Final[str] = (
    "The supplied evidence for one data-quality finding lists every distinct "
    "casing actually observed in the data for what should be one value. "
    "Choose exactly one of them as the correct, canonical spelling and "
    "capitalization every other row should match. Copy your chosen value "
    "exactly as it appears in the evidence's own distinct_casings list — do "
    "not alter its spelling, spacing or capitalization in any way, and do "
    "not choose a value that is not in that list."
)
"""Fixed, application-authored instruction text — never dataset-derived,
matching `explanation.ai_explanation.AI_EXPLANATION_TASK`'s own
precedent."""


def build_rule_generation_envelope(
    finding: FindingCandidate, evidence: tuple[Evidence, ...]
) -> PromptEnvelope:
    """Build the `PromptEnvelope` for an AI-assisted canonical-value
    request about `finding`.

    Sends zero dataset samples (`sample_sending_enabled` stays `False`,
    the structural default) — this finding's own evidence, which
    already carries `distinct_casings`, is the only grounding this
    contract needs, matching `explanation.ai_explanation.
    build_finding_explanation_envelope`'s own zero-raw-sample precedent.
    `evidence` is forwarded as `computed_evidence`, stored in its
    provider view (`ai_boundary.envelope.provider_evidence_view`):
    `InconsistentCapitalizationDetector`'s own evidence id embeds the
    normalized cell value, so a provider must only ever see the neutral
    positional alias, never the canonical id.
    """
    return build_prompt_envelope(task=RULE_GENERATION_TASK, computed_evidence=evidence)


@dataclass(frozen=True, slots=True)
class RuleGenerationResult:
    """The outcome of one `run_rule_generation` call.

    `accepted=True` always carries a `canonical_value` and no rejection
    reasons/provider error; `accepted=False` never carries one.
    """

    accepted: bool
    canonical_value: str | None
    rejection_reasons: tuple[RuleGenerationRejectionReason, ...]
    provider_error: str | None

    def __post_init__(self) -> None:
        if self.accepted and self.canonical_value is None:
            raise ValueError("RuleGenerationResult.canonical_value must be set when accepted")
        if not self.accepted and self.canonical_value is not None:
            raise ValueError("RuleGenerationResult.canonical_value must be None when not accepted")


def run_rule_generation(
    provider: AIProvider, envelope: PromptEnvelope, candidates: tuple[str, ...]
) -> RuleGenerationResult:
    """Call `provider` once for the structured canonical-value choice
    against `envelope`, validating the response against exactly
    `candidates`.

    Deliberately never retries (unlike `explanation.ai_explanation.
    run_finding_explanation`'s bounded retry-with-feedback loop): the
    schema already constrains the answer to a closed enum built from
    the finding's own evidence, so a rejected first attempt is not a
    transient formatting slip a retry could plausibly fix — it is
    treated the same as any other honest "no safe proposal" outcome.
    Never raises: a `ProviderError` (connection failure, timeout,
    malformed response) is isolated into a safe `provider_error`
    string, mirroring `run_finding_explanation`'s own precedent.

    Raises `ValueError` (via `build_rule_generation_contract`) when
    `candidates` has fewer than 2 entries — the caller's own
    `rules.generation.extract_ai_assist_candidates` must already
    enforce this before calling here.
    """
    contract = build_rule_generation_contract(candidates)
    request = ProviderRequest(
        operation=_OPERATION,
        envelope=envelope,
        known_numeric_facts={},
        output_contract=contract,
    )
    try:
        response = provider.complete(request)
    except ProviderError as exc:
        return RuleGenerationResult(
            accepted=False,
            canonical_value=None,
            rejection_reasons=(),
            provider_error=f"{type(exc).__name__}: {exc}",
        )
    outcome = validate_rule_generation_output(response.raw_output, candidates)
    return RuleGenerationResult(
        accepted=outcome.accepted,
        canonical_value=outcome.canonical_value,
        rejection_reasons=outcome.rejection_reasons,
        provider_error=None,
    )


__all__ = [
    "RULE_GENERATION_TASK",
    "RuleGenerationResult",
    "build_rule_generation_envelope",
    "run_rule_generation",
]
