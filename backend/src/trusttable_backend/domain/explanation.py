"""`FindingExplanation` (`AI-05`, extended by `AI-08`) — a grounded
analysis of one finding, produced either deterministically (no AI, always
available — `docs/product-requirements.md` §5.7's "deterministic
explanations" graceful-AI-disabled-operation bullet) or by a validated AI
response (`docs/product-requirements.md` §12's "finding explanations",
"remediation" and "rule descriptions" model calls).

Not a hypothesis about dataset context (`ContextHypothesis`, `CTX-01`)
and not a `Finding` aggregate itself (`docs/domain-model.md` §12) — this
is the minimal new shape actually needed: a narrative plus its grounding
references and provenance.

`AI-08` (`docs/decision-log.md` D-040) extends the shape additively with
the three further sections the Finding Detail screen presents next to the
explanation, each with its own semantic role so it can be validated and
rendered separately:

- `business_impact` — statements each labelled with an `ImpactBasis`
  (`evidence`, `confirmed_context` or `assumption`), so a possible
  consequence is never presented as a fact;
- `remediation` — advisory steps only; nothing here mutates source data;
- `validation_rule` — a `ProposedValidationRule`, a proposal that is never
  active or authoritative (`status` is always `"proposed"`).

`provenance` is deliberately restricted to `{DETERMINISTIC_FALLBACK,
AI_INTERPRETATION}` — the only two ways a `FindingExplanation` is ever
produced. `CALCULATED` is reserved for `Evidence` itself (the
finding's own already-computed facts, not a narrative built over them);
`USER_CONFIRMED`/`USER_CORRECTED` describe user-edited context fields
(`docs/domain-model.md` §8), not explanations.

`provider_name`/`model_identifier` (`UI-02` slice 1, `WP-063`) are a
disclosed, additive, backward-compatible step toward
`docs/domain-model.md` §14's fuller `AIInterpretation` shape
(`docs/decision-log.md` D-037's reconciliation requirement) — both
`None` for a deterministic-fallback explanation (no provider was used)
and populated from the real `ProviderResponse` for an accepted
AI-interpretation explanation. `model_identifier` here is the provider's
own raw value; nothing user-facing may show it unsanitized
(`ai_provider.display`, `AI-08`).

Framework-independent: no FastAPI/SQLAlchemy/pydantic/ai_boundary/
ai_provider import. Stdlib only.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .value_objects import ColumnReference, Provenance

#: The only two provenance values a `FindingExplanation` may carry.
_ALLOWED_EXPLANATION_PROVENANCE = frozenset(
    {Provenance.DETERMINISTIC_FALLBACK, Provenance.AI_INTERPRETATION}
)


class ImpactBasis(StrEnum):
    """What a business-impact statement rests on. Closed set.

    - `EVIDENCE`: follows directly from the finding's computed evidence.
    - `CONFIRMED_CONTEXT`: relies on dataset context the user confirmed or
      corrected (never on an inferred value).
    - `ASSUMPTION`: only a possible consequence; the condition that must
      hold is stated with it. Never presented as a fact.
    """

    EVIDENCE = "evidence"
    CONFIRMED_CONTEXT = "confirmed_context"
    ASSUMPTION = "assumption"


class ValidationRuleType(StrEnum):
    """The supported rule types `docs/product-requirements.md` §13 lists,
    as a closed set (a proposal can only name one of these)."""

    NOT_NULL = "not_null"
    UNIQUE = "unique"
    ACCEPTED_VALUES = "accepted_values"
    NUMERIC_RANGE = "numeric_range"
    DATE_RANGE = "date_range"
    REGEX = "regex"
    MAX_MISSING_PERCENTAGE = "max_missing_percentage"
    APPROXIMATE_EQUALITY = "approximate_equality"
    EXPRESSION_COMPARISON = "expression_comparison"
    CONDITIONAL_RULE = "conditional_rule"
    MAX_DUPLICATE_PERCENTAGE = "max_duplicate_percentage"


@dataclass(frozen=True, slots=True)
class BusinessImpactStatement:
    """One possible business implication of a finding, with the basis it
    rests on.

    Invariants (what keeps a possibility from reading as a fact):

    - `EVIDENCE` statements cite at least one evidence id and carry no
      assumption or context field;
    - `CONFIRMED_CONTEXT` statements cite at least one context field and
      carry no assumption;
    - `ASSUMPTION` statements state their assumption and cite no context
      field. Evidence ids are optional there (what triggered the
      possibility).
    """

    statement: str
    basis: ImpactBasis
    evidence_ids: tuple[str, ...] = ()
    context_fields: tuple[str, ...] = ()
    assumption: str | None = None

    def __post_init__(self) -> None:
        if not self.statement:
            raise ValueError("BusinessImpactStatement.statement must not be empty")
        if self.assumption is not None and not self.assumption.strip():
            raise ValueError("BusinessImpactStatement.assumption must not be blank when set")
        if self.basis is ImpactBasis.EVIDENCE:
            if not self.evidence_ids:
                raise ValueError("An evidence-backed statement must cite evidence")
            if self.context_fields or self.assumption is not None:
                raise ValueError("An evidence-backed statement carries no context or assumption")
        elif self.basis is ImpactBasis.CONFIRMED_CONTEXT:
            if not self.context_fields:
                raise ValueError("A context-backed statement must cite confirmed context fields")
            if self.assumption is not None:
                raise ValueError("A context-backed statement carries no assumption")
        else:
            if self.assumption is None:
                raise ValueError("A conditional statement must state its assumption")
            if self.context_fields:
                raise ValueError("A conditional statement cites no confirmed context field")


@dataclass(frozen=True, slots=True)
class ProposedValidationRule:
    """A validation rule *proposal* — never active, never authoritative.

    Nothing in the application runs, enforces or exports this rule (the
    rule engine is `RULE-01`, a later item); it is advice about what a
    person might check. `status` is therefore a constant.
    """

    rule_type: ValidationRuleType
    columns: tuple[ColumnReference, ...]
    description: str

    def __post_init__(self) -> None:
        if not self.description:
            raise ValueError("ProposedValidationRule.description must not be empty")

    @property
    def status(self) -> str:
        return "proposed"


@dataclass(frozen=True, slots=True)
class FindingExplanation:
    """A grounded analysis of one finding.

    Fields:
        narrative: the explanation text itself — either a fixed
            template built from the finding's own fields
            (`provenance == DETERMINISTIC_FALLBACK`) or a validated AI
            response (`provenance == AI_INTERPRETATION`).
        provenance: how this explanation was produced. Restricted to
            `DETERMINISTIC_FALLBACK`/`AI_INTERPRETATION` (see module
            docstring).
        referenced_evidence_ids: the `Evidence.evidence_id`s this
            explanation is grounded in.
        referenced_columns: the columns this explanation is grounded in.
        business_impact / remediation / validation_rule: the three further
            advisory sections (module docstring). Empty/`None` only for
            callers that build a bare explanation; both real producers
            (`explanation.deterministic`, `explanation.ai_explanation`)
            always fill them.
    """

    narrative: str
    provenance: Provenance
    referenced_evidence_ids: tuple[str, ...]
    referenced_columns: tuple[ColumnReference, ...]
    provider_name: str | None = None
    model_identifier: str | None = None
    business_impact: tuple[BusinessImpactStatement, ...] = ()
    remediation: tuple[str, ...] = ()
    validation_rule: ProposedValidationRule | None = None

    def __post_init__(self) -> None:
        if not self.narrative:
            raise ValueError("FindingExplanation.narrative must not be empty")
        if self.provenance not in _ALLOWED_EXPLANATION_PROVENANCE:
            raise ValueError(
                "FindingExplanation.provenance must be one of "
                f"{sorted(member.value for member in _ALLOWED_EXPLANATION_PROVENANCE)}, "
                f"got {self.provenance.value!r}"
            )
        if any(not step for step in self.remediation):
            raise ValueError("FindingExplanation.remediation steps must not be empty")


__all__ = [
    "BusinessImpactStatement",
    "FindingExplanation",
    "ImpactBasis",
    "ProposedValidationRule",
    "ValidationRuleType",
]
