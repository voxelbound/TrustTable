"""Dataset context contracts (`CTX-01`), matching `docs/domain-model.md`
§8 (`DatasetContext`) and §9 (`ContextHypothesis`).

Two distinct, related concepts, kept as separate types exactly as the
domain model does:

- `ContextHypothesis`: one candidate interpretation for a single
  `ContextField`, produced by deterministic heuristics
  (`context_inference.heuristics`, this package) or, in a later package
  (`CTX-02`), by validated AI inference. Multiple hypotheses may exist
  for the same field; `superseded` marks one as no longer current
  without deleting it (an audit-preserving pattern already established
  by this codebase's other append-only-evidence types).
- `DatasetContext`: the consolidated, currently-effective value of
  every `ContextField`, one `ContextFieldValue` per field (§8: "each
  field contains: value, confidence, inference source, confirmation
  state, evidence references").

`ContextHypothesis.related_columns` (a new field, not literally named
in §9) substitutes for `evidence_ids` when a hypothesis is derived
directly from `profiling.schemas.DatasetProfile`/`ColumnProfile` facts:
formal `Evidence` objects (`docs/domain-model.md` §13) are currently
produced only by detectors (`DET-01`), not by profiling facts, a
disclosed limitation this package carries forward from
`risk.scoring`'s own `_MONETARY_NAME_MARKERS` precedent. `evidence_ids`
is kept on `ContextHypothesis` for a future hypothesis that *is*
anchored to real detector evidence; every hypothesis this package's
heuristics module produces leaves it empty.

Framework-independent: no FastAPI/SQLAlchemy/pydantic/ai_boundary/
ai_provider import. Stdlib only (`dataclasses`, `enum`).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .value_objects import ColumnReference, Provenance


class ContextField(StrEnum):
    """Closed set of `DatasetContext` fields (`docs/domain-model.md` §8's
    exact field list)."""

    PROBABLE_DOMAIN = "probable_domain"
    ROW_GRAIN = "row_grain"
    PRIMARY_ENTITY = "primary_entity"
    CANDIDATE_KEYS = "candidate_keys"
    BUSINESS_DATES = "business_dates"
    MEASURE_ROLES = "measure_roles"
    DIMENSIONS = "dimensions"
    CURRENCY_BEHAVIOR = "currency_behavior"
    EXPECTED_BUSINESS_RULES = "expected_business_rules"


class ConfirmationState(StrEnum):
    """Closed set of confirmation states (`docs/domain-model.md` §8
    "Confirmation states", exact wording).

    This package (`CTX-01`) only ever produces `INFERRED` or `UNKNOWN`
    values. `CONFIRMED`/`CORRECTED` require a real user-facing
    confirmation flow, a later package (`docs/domain-model.md` §8's own
    invariant: "user-confirmed or corrected values override AI
    inference").
    """

    INFERRED = "inferred"
    CONFIRMED = "confirmed"
    CORRECTED = "corrected"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ContextHypothesis:
    """A candidate interpretation for one `ContextField`
    (`docs/domain-model.md` §9).

    Fields:
        hypothesis_id: stable, unique identifier for this hypothesis.
        context_field: which `DatasetContext` field this hypothesis
            proposes a value for.
        proposed_value: the candidate value. A single column's original
            name for column-role fields (`candidate_keys`,
            `business_dates`, `measure_roles`, `dimensions`); a short
            descriptive string for the remaining, single-value fields.
        confidence: `[0.0, 1.0]`, reflecting heuristic/model strength —
            not a probability guarantee.
        provenance: reuses `domain.value_objects.Provenance`'s existing
            five-value closed set (`CALCULATED` for this package's own
            deterministic heuristics).
        related_columns: the source column(s) this hypothesis was
            derived from. See module docstring for why this substitutes
            for `evidence_ids` here.
        evidence_ids: references into a future `Evidence` collection;
            empty for every hypothesis this package's heuristics
            produce (disclosed above).
        rationale: a short, human-readable explanation of the signal
            that produced this hypothesis.
        superseded: `True` once a later hypothesis has replaced this one
            for the same `context_field`; the hypothesis itself is
            never deleted (audit trail).
    """

    hypothesis_id: str
    context_field: ContextField
    proposed_value: str
    confidence: float
    provenance: Provenance
    related_columns: tuple[ColumnReference, ...]
    evidence_ids: tuple[str, ...]
    rationale: str
    superseded: bool = False

    def __post_init__(self) -> None:
        if not self.hypothesis_id:
            raise ValueError("ContextHypothesis.hypothesis_id must not be empty")
        if not self.proposed_value:
            raise ValueError("ContextHypothesis.proposed_value must not be empty")
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError("ContextHypothesis.confidence must be between 0.0 and 1.0")
        if not self.rationale:
            raise ValueError("ContextHypothesis.rationale must not be empty")


@dataclass(frozen=True, slots=True)
class ContextFieldValue:
    """The consolidated, currently-effective value of one `ContextField`
    (`docs/domain-model.md` §8: "Each field contains: value, confidence,
    inference source, confirmation state, evidence references").

    `value` is intentionally open-typed (`object`), matching this
    codebase's existing precedent for shape-depends-on-context fields
    (`domain.evidence.Evidence.structured_payload`,
    `profiling.schemas.ColumnProfile.metrics`): a `tuple[str, ...]` of
    column original names for the four column-role fields, or a plain
    `str` for the remaining five single-value fields.
    """

    value: object
    confidence: float
    inference_source: Provenance
    confirmation_state: ConfirmationState
    evidence_ids: tuple[str, ...]

    def __post_init__(self) -> None:
        if not (0.0 <= self.confidence <= 1.0):
            raise ValueError("ContextFieldValue.confidence must be between 0.0 and 1.0")


@dataclass(frozen=True, slots=True)
class DatasetContext:
    """Consolidated dataset context (`docs/domain-model.md` §8), one
    `ContextFieldValue` per `ContextField`.

    `schema_version` follows this codebase's existing
    `DatasetProfile.schema_version` precedent, so a future consumer
    (`docs/domain-model.md` §8's "context-dependent detectors record the
    context version used" invariant) has something stable to record.
    """

    schema_version: str
    probable_domain: ContextFieldValue
    row_grain: ContextFieldValue
    primary_entity: ContextFieldValue
    candidate_keys: ContextFieldValue
    business_dates: ContextFieldValue
    measure_roles: ContextFieldValue
    dimensions: ContextFieldValue
    currency_behavior: ContextFieldValue
    expected_business_rules: ContextFieldValue

    def __post_init__(self) -> None:
        if not self.schema_version:
            raise ValueError("DatasetContext.schema_version must not be empty")
