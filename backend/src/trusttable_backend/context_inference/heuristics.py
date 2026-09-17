"""Deterministic dataset-context heuristics (`CTX-01`).

Two-stage design, matching `docs/domain-model.md` §8/§9's distinct
`ContextHypothesis` (candidate) / `DatasetContext` (consolidated)
concepts:

- `infer_context_hypotheses`: from a `DatasetProfile` alone, produce
  zero or more `ContextHypothesis` candidates per `ContextField`, using
  fixed, disclosed heuristics over `PROF-02`/`PROF-03`'s already-
  computed column types and metrics. No dataset content is re-read, no
  file access.
- `consolidate_dataset_context`: fold a set of hypotheses into one
  `DatasetContext` snapshot. The four "role" fields (`candidate_keys`,
  `business_dates`, `measure_roles`, `dimensions`) union every
  non-superseded hypothesis's column into that field's value (a dataset
  commonly has more than one date/measure/dimension/candidate-key
  column at once). The five "single value" fields (`probable_domain`,
  `row_grain`, `primary_entity`, `currency_behavior`,
  `expected_business_rules`) select the single highest-confidence
  hypothesis, or fall back to `ConfirmationState.UNKNOWN` with
  `confidence=0.0` when no hypothesis exists for that field.
- `infer_dataset_context`: convenience composing both stages.

Heuristics implemented (each fixed, disclosed, and reversible — the
same accepted-limitation pattern already established by
`risk.scoring._MONETARY_NAME_MARKERS` and
`detectors.validity._PERCENTAGE_NAME_MARKERS`):

- `candidate_keys`: `IDENTIFIER`-typed columns (confidence
  `_IDENTIFIER_CONFIDENCE_UNIQUE`), or `TEXT`-typed columns flagged
  `likely_identifier` by `PROF-03` (confidence
  `_IDENTIFIER_CONFIDENCE_HEURISTIC`).
- `business_dates`: `DATE`-typed columns.
- `measure_roles`: `NUMERIC`-typed columns.
- `dimensions`: `CATEGORICAL`-typed columns.
- `row_grain`: `"One row per <column>"` when exactly one candidate-key
  column exists; left with no hypothesis (falls back to `UNKNOWN`) when
  zero or multiple candidates exist — a deliberately conservative
  choice, not a guess under ambiguity.
- `primary_entity`: derived from the sole candidate-key column's name
  when it matches the `"<entity>_id"` naming convention; otherwise no
  hypothesis.
- `probable_domain`: a narrow, disclosed keyword heuristic recognizing
  only a "Sales / order transactions" pattern (at least
  `_SALES_DOMAIN_MIN_MATCHES` column names matching a fixed marker
  list); otherwise no hypothesis. Not a general domain classifier — a
  single-domain heuristic, extensible in a future package.
- `currency_behavior`, `expected_business_rules`: this package
  generates no hypothesis for either field — no deterministic signal
  exists yet. Both always consolidate to `UNKNOWN`/`confidence=0.0`,
  disclosed rather than silently guessed. Deferred to `CTX-02`
  (AI-assisted) or a later rules-generation package (`RULE-01`/
  `RULE-02`).

Framework-independent: no FastAPI/SQLAlchemy/pydantic/ai_boundary/
ai_provider import. Stdlib only.
"""

from __future__ import annotations

from typing import Final

from ..domain.context import (
    ConfirmationState,
    ContextField,
    ContextFieldValue,
    ContextHypothesis,
    DatasetContext,
)
from ..domain.value_objects import ColumnReference, Provenance
from ..profiling.schemas import ColumnProfile, DatasetProfile, InferredColumnType

_SCHEMA_VERSION: Final[str] = "1"

_ROLE_FIELDS: Final[frozenset[ContextField]] = frozenset(
    {
        ContextField.CANDIDATE_KEYS,
        ContextField.BUSINESS_DATES,
        ContextField.MEASURE_ROLES,
        ContextField.DIMENSIONS,
    }
)
"""`ContextField` values consolidated by union-of-all-hypotheses rather
than best-single-hypothesis (see module docstring)."""

_IDENTIFIER_CONFIDENCE_UNIQUE: Final[float] = 0.9
_IDENTIFIER_CONFIDENCE_HEURISTIC: Final[float] = 0.7
_DATE_CONFIDENCE: Final[float] = 0.9
_MEASURE_CONFIDENCE: Final[float] = 0.75
_DIMENSION_CONFIDENCE: Final[float] = 0.7
_ROW_GRAIN_CONFIDENCE: Final[float] = 0.6
_PRIMARY_ENTITY_CONFIDENCE: Final[float] = 0.55
_PROBABLE_DOMAIN_CONFIDENCE: Final[float] = 0.5

_ENTITY_ID_SUFFIX: Final[str] = "_id"

_SALES_DOMAIN_MARKERS: Final[tuple[str, ...]] = (
    "order",
    "customer",
    "product",
    "sku",
    "invoice",
    "sale",
    "price",
    "quantity",
    "discount",
    "tax",
    "region",
)
"""Matches `order_id`/`customer_name`/`product`/`region`/`quantity`/
`unit_price`/`discount_pct`/`tax_pct` in the committed `demo-data/
sales_demo.csv`. A disclosed, single-domain heuristic; a differently-
worded sales dataset or a non-sales dataset are both out of scope for
this package (same disclosed-limitation class as `risk.scoring`'s own
column-name markers)."""

_SALES_DOMAIN_MIN_MATCHES: Final[int] = 3
"""Minimum distinct matching column names required before proposing the
`probable_domain` hypothesis, avoiding a false-positive guess from one
coincidental name match."""

_PROBABLE_DOMAIN_VALUE: Final[str] = "Sales / order transactions"


def _type_hypotheses(
    dataset_profile: DatasetProfile,
    inferred_type: InferredColumnType,
    context_field: ContextField,
    confidence: float,
    type_description: str,
) -> list[ContextHypothesis]:
    hypotheses: list[ContextHypothesis] = []
    matching = [
        column_profile
        for column_profile in dataset_profile.column_profiles
        if column_profile.inferred_type is inferred_type
    ]
    for index, column_profile in enumerate(matching, start=1):
        column = column_profile.column
        hypotheses.append(
            ContextHypothesis(
                hypothesis_id=f"ctx-{context_field.value}-{index}",
                context_field=context_field,
                proposed_value=column.original_name,
                confidence=confidence,
                provenance=Provenance.CALCULATED,
                related_columns=(column,),
                evidence_ids=(),
                rationale=f"Column '{column.original_name}' is {type_description}.",
            )
        )
    return hypotheses


def _is_heuristic_identifier(column_profile: ColumnProfile) -> bool:
    return column_profile.inferred_type is InferredColumnType.TEXT and bool(
        column_profile.metrics.get("likely_identifier")
    )


def _candidate_key_hypotheses(dataset_profile: DatasetProfile) -> list[ContextHypothesis]:
    hypotheses: list[ContextHypothesis] = []
    index = 0
    for column_profile in dataset_profile.column_profiles:
        column = column_profile.column
        if column_profile.inferred_type is InferredColumnType.IDENTIFIER:
            index += 1
            hypotheses.append(
                ContextHypothesis(
                    hypothesis_id=f"ctx-candidate_keys-{index}",
                    context_field=ContextField.CANDIDATE_KEYS,
                    proposed_value=column.original_name,
                    confidence=_IDENTIFIER_CONFIDENCE_UNIQUE,
                    provenance=Provenance.CALCULATED,
                    related_columns=(column,),
                    evidence_ids=(),
                    rationale=(
                        f"Column '{column.original_name}' is inferred as IDENTIFIER "
                        "(PROF-02): fully unique, non-blank values."
                    ),
                )
            )
        elif _is_heuristic_identifier(column_profile):
            index += 1
            hypotheses.append(
                ContextHypothesis(
                    hypothesis_id=f"ctx-candidate_keys-{index}",
                    context_field=ContextField.CANDIDATE_KEYS,
                    proposed_value=column.original_name,
                    confidence=_IDENTIFIER_CONFIDENCE_HEURISTIC,
                    provenance=Provenance.CALCULATED,
                    related_columns=(column,),
                    evidence_ids=(),
                    rationale=(
                        f"Column '{column.original_name}' is TEXT-typed but flagged "
                        "likely_identifier by PROF-03 (near-unique, mostly non-blank "
                        "values)."
                    ),
                )
            )
    return hypotheses


def _row_grain_hypotheses(
    candidate_keys: list[ContextHypothesis],
) -> list[ContextHypothesis]:
    if len(candidate_keys) != 1:
        return []
    key = candidate_keys[0]
    return [
        ContextHypothesis(
            hypothesis_id="ctx-row_grain-1",
            context_field=ContextField.ROW_GRAIN,
            proposed_value=f"One row per {key.proposed_value}",
            confidence=_ROW_GRAIN_CONFIDENCE,
            provenance=Provenance.CALCULATED,
            related_columns=key.related_columns,
            evidence_ids=(),
            rationale=(
                f"Exactly one candidate-key column ('{key.proposed_value}') was "
                "found; a single, unambiguous candidate key is treated as a "
                "conservative signal for row grain."
            ),
        )
    ]


def _primary_entity_hypotheses(
    candidate_keys: list[ContextHypothesis],
) -> list[ContextHypothesis]:
    if len(candidate_keys) != 1:
        return []
    key = candidate_keys[0]
    lowered = key.proposed_value.lower()
    if not lowered.endswith(_ENTITY_ID_SUFFIX):
        return []
    entity = lowered[: -len(_ENTITY_ID_SUFFIX)]
    if not entity:
        return []
    return [
        ContextHypothesis(
            hypothesis_id="ctx-primary_entity-1",
            context_field=ContextField.PRIMARY_ENTITY,
            proposed_value=entity,
            confidence=_PRIMARY_ENTITY_CONFIDENCE,
            provenance=Provenance.CALCULATED,
            related_columns=key.related_columns,
            evidence_ids=(),
            rationale=(
                f"Sole candidate-key column '{key.proposed_value}' matches the "
                "'<entity>_id' naming convention; a disclosed, reversible "
                "column-name heuristic, not a semantic guarantee."
            ),
        )
    ]


def _probable_domain_hypotheses(dataset_profile: DatasetProfile) -> list[ContextHypothesis]:
    matched_columns: tuple[ColumnReference, ...] = tuple(
        column_profile.column
        for column_profile in dataset_profile.column_profiles
        if any(
            marker in column_profile.column.original_name.lower()
            for marker in _SALES_DOMAIN_MARKERS
        )
    )
    if len(matched_columns) < _SALES_DOMAIN_MIN_MATCHES:
        return []
    return [
        ContextHypothesis(
            hypothesis_id="ctx-probable_domain-1",
            context_field=ContextField.PROBABLE_DOMAIN,
            proposed_value=_PROBABLE_DOMAIN_VALUE,
            confidence=_PROBABLE_DOMAIN_CONFIDENCE,
            provenance=Provenance.CALCULATED,
            related_columns=matched_columns,
            evidence_ids=(),
            rationale=(
                f"{len(matched_columns)} column name(s) matched a fixed "
                "sales/order-domain keyword list — a disclosed, narrow, "
                "single-domain heuristic (extensible in a future package), "
                "not a general domain classifier."
            ),
        )
    ]


def infer_context_hypotheses(dataset_profile: DatasetProfile) -> tuple[ContextHypothesis, ...]:
    """Produce every deterministic `ContextHypothesis` derivable from
    `dataset_profile` alone. Order-stable: column-role hypotheses follow
    `dataset_profile.column_profiles`'s own order; scalar hypotheses
    follow row_grain -> primary_entity -> probable_domain.
    """
    candidate_keys = _candidate_key_hypotheses(dataset_profile)
    business_dates = _type_hypotheses(
        dataset_profile,
        InferredColumnType.DATE,
        ContextField.BUSINESS_DATES,
        _DATE_CONFIDENCE,
        "DATE-typed (PROF-02)",
    )
    measure_roles = _type_hypotheses(
        dataset_profile,
        InferredColumnType.NUMERIC,
        ContextField.MEASURE_ROLES,
        _MEASURE_CONFIDENCE,
        "NUMERIC-typed (PROF-02)",
    )
    dimensions = _type_hypotheses(
        dataset_profile,
        InferredColumnType.CATEGORICAL,
        ContextField.DIMENSIONS,
        _DIMENSION_CONFIDENCE,
        "CATEGORICAL-typed (PROF-02)",
    )

    scalar: list[ContextHypothesis] = []
    scalar.extend(_row_grain_hypotheses(candidate_keys))
    scalar.extend(_primary_entity_hypotheses(candidate_keys))
    scalar.extend(_probable_domain_hypotheses(dataset_profile))

    return tuple(candidate_keys + business_dates + measure_roles + dimensions + scalar)


def _unknown_field_value(field: ContextField) -> ContextFieldValue:
    return ContextFieldValue(
        value=() if field in _ROLE_FIELDS else "unknown",
        confidence=0.0,
        inference_source=Provenance.DETERMINISTIC_FALLBACK,
        confirmation_state=ConfirmationState.UNKNOWN,
        evidence_ids=(),
    )


def _consolidate_role_field(candidates: list[ContextHypothesis]) -> ContextFieldValue:
    values = tuple(sorted({hypothesis.proposed_value for hypothesis in candidates}))
    evidence_ids = tuple(
        sorted(
            {evidence_id for hypothesis in candidates for evidence_id in hypothesis.evidence_ids}
        )
    )
    average_confidence = sum(hypothesis.confidence for hypothesis in candidates) / len(candidates)
    return ContextFieldValue(
        value=values,
        confidence=average_confidence,
        inference_source=Provenance.CALCULATED,
        confirmation_state=ConfirmationState.INFERRED,
        evidence_ids=evidence_ids,
    )


def _consolidate_single_value_field(candidates: list[ContextHypothesis]) -> ContextFieldValue:
    best = max(candidates, key=lambda hypothesis: hypothesis.confidence)
    return ContextFieldValue(
        value=best.proposed_value,
        confidence=best.confidence,
        inference_source=best.provenance,
        confirmation_state=ConfirmationState.INFERRED,
        evidence_ids=best.evidence_ids,
    )


def consolidate_dataset_context(hypotheses: tuple[ContextHypothesis, ...]) -> DatasetContext:
    """Fold `hypotheses` into one `DatasetContext` snapshot. See module
    docstring for the per-field consolidation rule."""
    by_field: dict[ContextField, list[ContextHypothesis]] = {field: [] for field in ContextField}
    for hypothesis in hypotheses:
        if not hypothesis.superseded:
            by_field[hypothesis.context_field].append(hypothesis)

    fields: dict[ContextField, ContextFieldValue] = {}
    for field in ContextField:
        candidates = by_field[field]
        if not candidates:
            fields[field] = _unknown_field_value(field)
        elif field in _ROLE_FIELDS:
            fields[field] = _consolidate_role_field(candidates)
        else:
            fields[field] = _consolidate_single_value_field(candidates)

    return DatasetContext(
        schema_version=_SCHEMA_VERSION,
        probable_domain=fields[ContextField.PROBABLE_DOMAIN],
        row_grain=fields[ContextField.ROW_GRAIN],
        primary_entity=fields[ContextField.PRIMARY_ENTITY],
        candidate_keys=fields[ContextField.CANDIDATE_KEYS],
        business_dates=fields[ContextField.BUSINESS_DATES],
        measure_roles=fields[ContextField.MEASURE_ROLES],
        dimensions=fields[ContextField.DIMENSIONS],
        currency_behavior=fields[ContextField.CURRENCY_BEHAVIOR],
        expected_business_rules=fields[ContextField.EXPECTED_BUSINESS_RULES],
    )


def infer_dataset_context(dataset_profile: DatasetProfile) -> DatasetContext:
    """Convenience composing `infer_context_hypotheses` and
    `consolidate_dataset_context`."""
    return consolidate_dataset_context(infer_context_hypotheses(dataset_profile))
