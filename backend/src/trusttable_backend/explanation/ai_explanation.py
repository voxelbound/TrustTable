"""Validated AI finding analysis (`AI-05`, restructured by `AI-08`) — the
"finding explanations", "remediation" and "rule descriptions" model calls
`docs/product-requirements.md` §12 names, made as **one** structured call
per finding (`AIOperation.FINDING_EXPLANATION`, already defined by
`AI-01`, unchanged).

`AI-08` (`docs/decision-log.md` D-040, resolving `FUP-011`'s durable
direction) replaces the earlier single free-prose narrative with the
versioned `finding_analysis_v1` output contract
(`ai_boundary.finding_analysis`): an explanation, 1-3 business-impact
statements each labelled `evidence`/`confirmed_context`/`assumption`, 1-3
advisory remediation steps and one *proposed* validation rule. The request
carries the contract (so a constrained-decoding runtime can only emit
evidence ids, columns and context fields that were actually supplied) and
the response is validated role by role; `EVAL-AI-01`'s claim screen still
runs over every text field as defense in depth.

**Wired into a real, live HTTP route** (`GET .../findings/{finding_id}/
explanation`) — the route layer, not `analysis.service`, calls this module.
Nothing here is imported by `analysis.service`, no `AnalysisState` value
changes and `Analysis.security_exposure` is untouched.

Unlike `deterministic.py`/`guidance.py` (this package's deterministic-only
siblings, which deliberately import neither `ai_boundary` nor
`ai_provider`), this module's purpose is to call a real `AIProvider`
through `SEC-02`'s trust boundary — those imports are intentional.

`_known_numeric_facts_from_evidence` mirrors `ai_benchmark.fixtures.
_known_numeric_facts_from_evidence`'s already-proven fail-closed collision
logic, kept as this package's own small copy (the codebase's per-package
helper convention) rather than importing from `ai_benchmark`.

Retry-with-feedback and provider-error handling mirror
`context_inference.ai_context.run_context_inference`'s established pattern
(bounded retries, `ProviderError` isolated into a safe `provider_error`
string, never raised).

Framework-independent besides its two deliberate seams (`ai_boundary`,
`ai_provider`): no FastAPI/SQLAlchemy/pydantic import. Stdlib only
otherwise.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Final

from ..ai_boundary.envelope import PromptEnvelope, build_prompt_envelope
from ..ai_boundary.finding_analysis import (
    build_finding_analysis_contract,
    validate_finding_analysis_output,
)
from ..ai_boundary.validation import RejectionReason
from ..ai_provider.contract import AIOperation, AIProvider, ProviderError, ProviderRequest
from ..detectors.contract import FindingCandidate
from ..domain.context import ConfirmationState, ContextField, DatasetContext
from ..domain.evidence import Evidence
from ..domain.explanation import (
    BusinessImpactStatement,
    FindingExplanation,
    ImpactBasis,
    ProposedValidationRule,
    ValidationRuleType,
)
from ..domain.value_objects import ColumnReference, Provenance

AI_EXPLANATION_TASK: Final[str] = (
    "Analyze the deterministic finding and its supporting evidence supplied below "
    "for a business user: explain what it means, describe its possible business "
    "impact, recommend remediation steps and propose one validation rule. Ground "
    "every statement only in the supplied evidence and the supplied confirmed "
    "context. Anything else must be labelled an assumption."
)
"""Fixed, application-authored instruction text — never dataset-derived
(`docs/product-requirements.md` §12; mirrors `context_inference.
ai_context.AI_CONTEXT_TASK`'s precedent: a single bounded call, not an
open-ended question)."""

DEFAULT_MAX_RETRIES: Final[int] = 2
"""Matches `context_inference.ai_context.DEFAULT_MAX_RETRIES`'s and
`ai_benchmark.BenchmarkConfig.max_retries`'s own default, for
consistency across this codebase's independent bounded-retry call
sites."""


def build_finding_analysis_task(finding: FindingCandidate) -> str:
    """The per-finding task text: the fixed instruction plus the finding's
    detector id, category and severity. All three are closed,
    application-defined values (a registry id and two enums), never
    dataset-derived — which is why they may live in the trusted task text
    while the finding's observation (built from column names) may not."""
    return (
        f"{AI_EXPLANATION_TASK} The finding was raised by detector "
        f"'{finding.detector_id}' (category {finding.category.value}, "
        f"severity {finding.severity.value})."
    )


def _known_numeric_facts_from_evidence(evidence: tuple[Evidence, ...]) -> dict[str, float]:
    """Derive a flat `known_numeric_facts` allow-list from the numeric
    fields of each included `Evidence.structured_payload`, aggregated by
    original field name, with a fail-closed collision rule (a field name
    with conflicting values across evidence items is omitted entirely,
    never last-write-wins).
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


_CONFIRMED_STATES: Final[frozenset[ConfirmationState]] = frozenset(
    {ConfirmationState.CONFIRMED, ConfirmationState.CORRECTED}
)


def confirmed_context_for_finding_analysis(
    dataset_context: DatasetContext | None, *, finalized: bool
) -> dict[str, object] | None:
    """The context payload a finding-analysis request may carry, or `None`.

    `AI-08`: only fields the *user* confirmed or corrected are ever sent,
    and only once the analysis context has been finalized. Inferred and
    unknown fields are never sent — an inferred value must not reach the
    model, or the user, labelled as confirmed fact. Returns `None` when
    the context is not finalized or no field was confirmed/corrected, so a
    caller can treat "nothing to send" and "not finalized" identically.

    Each entry carries only the field's `value` and its `confirmation_state`
    (never its inference confidence or source): what a model may rely on is
    the user's own answer.
    """
    if not finalized or dataset_context is None:
        return None
    fields: dict[str, object] = {}
    for field in ContextField:
        field_value = getattr(dataset_context, field.value)
        if field_value.confirmation_state not in _CONFIRMED_STATES:
            continue
        value = field_value.value
        fields[field.value] = {
            "value": list(value) if isinstance(value, tuple) else value,
            "confirmation_state": field_value.confirmation_state.value,
        }
    return fields or None


PROVIDER_EVIDENCE_ALIAS_PREFIX: Final[str] = "evidence_"
"""Prefix of the neutral evidence ids a provider sees (`evidence_1`,
`evidence_2`, ...)."""


def provider_evidence_view(evidence: tuple[Evidence, ...]) -> tuple[Evidence, ...]:
    """`evidence` with each item's id replaced by a neutral positional alias.

    A canonical evidence id can embed dataset content: for example
    `InconsistentCapitalizationDetector` builds it from the *normalized cell
    value* (`...evidence.notes.<normalized value>`), so sending it would send
    the value. The provider therefore only ever sees `evidence_1`,
    `evidence_2`, ...; the alias-to-real mapping is applied afterwards when
    an accepted answer is turned into the domain object. Everything else
    about the evidence is unchanged here — the payload allow-list and the
    column metadata policy are applied by `ai_boundary.prompt`.
    """
    return tuple(
        replace(item, evidence_id=f"{PROVIDER_EVIDENCE_ALIAS_PREFIX}{position}")
        for position, item in enumerate(evidence, start=1)
    )


def build_finding_explanation_envelope(
    finding: FindingCandidate,
    evidence: tuple[Evidence, ...],
    *,
    confirmed_context: Mapping[str, object] | None = None,
) -> PromptEnvelope:
    """Build the `PromptEnvelope` for a finding-analysis call about
    `finding`.

    `evidence` (typically resolved via `analysis.service.
    get_finding_evidence`) is forwarded as `computed_evidence` **in its
    provider view** (`provider_evidence_view`: neutral evidence ids, and
    `ai_boundary.prompt` then forwards only computed facts from each
    payload). This package sends zero dataset samples — disclosed, not
    silently assumed (a finding's own evidence is already the grounding a
    business-facing analysis needs).

    `confirmed_context` is optional and caller-supplied. **`AI-08`:** the
    caller must pass only user-confirmed or corrected context fields
    (never inferred or unknown ones) and only once the analysis context
    has been finalized; this function forwards whatever it is given as
    `PromptEnvelope.confirmed_context`, which the output validator then
    treats as the only set of context fields a statement may cite.
    `PromptEnvelope.confirmed_context` remains untrusted regardless
    (`docs/architecture.md` §7).
    """
    return build_prompt_envelope(
        task=build_finding_analysis_task(finding),
        computed_evidence=provider_evidence_view(evidence),
        confirmed_context=confirmed_context,
    )


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
    reply: grounding stays exact against what was actually sent, not what
    the model claims to have used.
    """
    seen: dict[str, ColumnReference] = {}
    for item in evidence:
        for column in item.affected_columns:
            seen.setdefault(column.internal_key, column)
    return tuple(seen.values())


def _string_tuple(value: object) -> tuple[str, ...]:
    assert isinstance(value, list | tuple)  # guaranteed by validation acceptance
    return tuple(str(item) for item in value)


def _build_explanation(
    raw_output: Mapping[str, object],
    evidence: tuple[Evidence, ...],
    alias_to_real: Mapping[str, str],
    *,
    provider_name: str,
    model_identifier: str,
) -> FindingExplanation:
    """Turn an already-validated `finding_analysis_v1` output into the
    domain object. Only called after `validate_finding_analysis_output`
    accepted `raw_output`, so the shapes asserted here are guaranteed.
    `alias_to_real` maps the neutral evidence ids the provider saw back to
    the canonical ones the rest of the application uses."""
    grounded = _grounded_columns(evidence)
    column_by_key = {column.internal_key: column for column in grounded}

    explanation = raw_output["explanation"]
    assert isinstance(explanation, str)

    impact_entries = raw_output["business_impact"]
    assert isinstance(impact_entries, list | tuple)
    impact: list[BusinessImpactStatement] = []
    for entry in impact_entries:
        assert isinstance(entry, Mapping)
        assumption = entry["assumption"]
        assert isinstance(assumption, str)
        statement = entry["statement"]
        assert isinstance(statement, str)
        impact.append(
            BusinessImpactStatement(
                statement=statement,
                basis=ImpactBasis(str(entry["basis"])),
                evidence_ids=tuple(
                    alias_to_real[alias] for alias in _string_tuple(entry["evidence_ids"])
                ),
                context_fields=_string_tuple(entry["context_fields"]),
                assumption=assumption.strip() or None,
            )
        )

    rule = raw_output["validation_rule"]
    assert isinstance(rule, Mapping)
    description = rule["description"]
    assert isinstance(description, str)
    rule_columns = tuple(
        column_by_key[key] for key in _string_tuple(rule["columns"]) if key in column_by_key
    )

    return FindingExplanation(
        narrative=explanation,
        provenance=Provenance.AI_INTERPRETATION,
        referenced_evidence_ids=tuple(item.evidence_id for item in evidence),
        referenced_columns=grounded,
        provider_name=provider_name,
        model_identifier=model_identifier,
        business_impact=tuple(impact),
        remediation=_string_tuple(raw_output["remediation"]),
        validation_rule=ProposedValidationRule(
            rule_type=ValidationRuleType(str(rule["rule_type"])),
            columns=rule_columns,
            description=description,
        ),
    )


def run_finding_explanation(
    provider: AIProvider,
    envelope: PromptEnvelope,
    evidence: tuple[Evidence, ...],
    *,
    max_retries: int = DEFAULT_MAX_RETRIES,
) -> FindingExplanationResult:
    """Call `provider` once (plus bounded retries) for the structured
    finding analysis against `envelope`, validating the response role by
    role and retrying with feedback on rejection, up to `max_retries`
    additional attempts. Never raises — a `ProviderError` (connection
    failure, timeout, malformed response) is isolated into a safe
    `provider_error` string and the call stops immediately, mirroring
    `context_inference.ai_context.run_context_inference`.

    `evidence` is the canonical evidence; `envelope` must have been built
    from it by `build_finding_explanation_envelope`, so its
    `computed_evidence` is the same items in provider view (neutral ids).

    The request carries the per-request `OutputContract`
    (`build_finding_analysis_contract`): its schema enumerates exactly the
    provider-visible evidence ids, columns, confirmed-context fields and
    numeric-fact names. `known_numeric_facts` is derived from `evidence`
    and forwarded to the validator, so numeric claims are checked against
    what was actually sent.
    """
    if len(envelope.computed_evidence) != len(evidence):
        raise ValueError(
            "run_finding_explanation: envelope.computed_evidence must be the provider view "
            "of `evidence` (build it with build_finding_explanation_envelope)"
        )
    alias_to_real = {
        seen.evidence_id: real.evidence_id
        for seen, real in zip(envelope.computed_evidence, evidence, strict=True)
    }
    known_numeric_facts = _known_numeric_facts_from_evidence(evidence)
    contract = build_finding_analysis_contract(
        evidence=envelope.computed_evidence,
        context_fields=tuple(str(key) for key in envelope.confirmed_context),
        numeric_fact_names=tuple(known_numeric_facts),
    )
    request = ProviderRequest(
        operation=AIOperation.FINDING_EXPLANATION,
        envelope=envelope,
        known_numeric_facts=known_numeric_facts,
        output_contract=contract,
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
        outcome = validate_finding_analysis_output(
            response.raw_output, envelope, known_numeric_facts=known_numeric_facts
        )
        if outcome.accepted:
            explanation = _build_explanation(
                response.raw_output,
                evidence,
                alias_to_real,
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
    "PROVIDER_EVIDENCE_ALIAS_PREFIX",
    "FindingExplanationResult",
    "build_finding_analysis_task",
    "build_finding_explanation_envelope",
    "confirmed_context_for_finding_analysis",
    "provider_evidence_view",
    "run_finding_explanation",
]
