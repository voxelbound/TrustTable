"""`FindingExplanation` (`AI-05`) — a short, grounded narrative for one
finding, produced either deterministically (no AI, always available —
`docs/product-requirements.md` §5.7's "deterministic explanations"
graceful-AI-disabled-operation bullet) or by a validated AI response
(`docs/product-requirements.md` §12's "finding explanations" model
call).

Not a hypothesis about dataset context (`ContextHypothesis`, `CTX-01`)
and not a `Finding` aggregate itself (`docs/domain-model.md` §12) — this
is the minimal new shape actually needed: a narrative plus its grounding
references and provenance. No prior `docs/domain-model.md` entry names
this concept; this package adds it rather than overloading an existing,
differently-scoped type.

`provenance` is deliberately restricted to `{DETERMINISTIC_FALLBACK,
AI_INTERPRETATION}` — the only two ways a `FindingExplanation` is ever
produced. `CALCULATED` is reserved for `Evidence` itself (the
finding's own already-computed facts, not a narrative built over them);
`USER_CONFIRMED`/`USER_CORRECTED` describe user-edited context fields
(`docs/domain-model.md` §8), not explanations.

Framework-independent: no FastAPI/SQLAlchemy/pydantic/ai_boundary/
ai_provider import. Stdlib only.
"""

from __future__ import annotations

from dataclasses import dataclass

from .value_objects import ColumnReference, Provenance

#: The only two provenance values a `FindingExplanation` may carry.
_ALLOWED_EXPLANATION_PROVENANCE = frozenset(
    {Provenance.DETERMINISTIC_FALLBACK, Provenance.AI_INTERPRETATION}
)


@dataclass(frozen=True, slots=True)
class FindingExplanation:
    """A short, grounded narrative explaining one finding.

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
    """

    narrative: str
    provenance: Provenance
    referenced_evidence_ids: tuple[str, ...]
    referenced_columns: tuple[ColumnReference, ...]

    def __post_init__(self) -> None:
        if not self.narrative:
            raise ValueError("FindingExplanation.narrative must not be empty")
        if self.provenance not in _ALLOWED_EXPLANATION_PROVENANCE:
            raise ValueError(
                "FindingExplanation.provenance must be one of "
                f"{sorted(member.value for member in _ALLOWED_EXPLANATION_PROVENANCE)}, "
                f"got {self.provenance.value!r}"
            )


__all__ = ["FindingExplanation"]
