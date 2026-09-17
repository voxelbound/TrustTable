"""Tests for deterministic dataset-context heuristics (CTX-01, WP-056).

Covers this package's acceptance criteria AC-02..AC-06: each heuristic's
positive/negative/boundary cases, the two consolidation strategies
(role-field union, single-value-field best-confidence), the zero-
hypothesis UNKNOWN fallback for every field, determinism, and a real
end-to-end check against the committed `demo-data/sales_demo.csv`.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from trusttable_backend.context_inference.heuristics import (
    consolidate_dataset_context,
    infer_context_hypotheses,
    infer_dataset_context,
)
from trusttable_backend.domain.context import (
    ConfirmationState,
    ContextField,
    ContextFieldValue,
    ContextHypothesis,
)
from trusttable_backend.domain.parsing import SampleMetadata, SamplingScope
from trusttable_backend.domain.value_objects import ColumnReference, Provenance
from trusttable_backend.parsers.csv_parser import parse_csv
from trusttable_backend.profiling.metrics import compute_dataset_profile
from trusttable_backend.profiling.schemas import (
    ColumnProfile,
    DatasetProfile,
    InferredColumnType,
    ProfilingTiming,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
DEMO_CSV_PATH = REPO_ROOT / "demo-data" / "sales_demo.csv"

TIMESTAMP = datetime(2026, 9, 17, 12, 0, tzinfo=UTC)


def make_column(name: str, ordinal: int) -> ColumnReference:
    return ColumnReference(original_name=name, internal_key=name, ordinal=ordinal)


def make_column_profile(
    column: ColumnReference, inferred_type: InferredColumnType, **overrides: object
) -> ColumnProfile:
    fields: dict[str, object] = {
        "column": column,
        "inferred_type": inferred_type,
        "null_count": 0,
        "distinct_count": 1,
        "metrics": {},
        "warnings": (),
    }
    fields.update(overrides)
    return ColumnProfile(**fields)  # type: ignore[arg-type]


def make_dataset_profile(column_profiles: tuple[ColumnProfile, ...]) -> DatasetProfile:
    return DatasetProfile(
        schema_version="1",
        dataset_metrics={},
        column_profiles=column_profiles,
        sampling=SampleMetadata(scope=SamplingScope.FULL, population_size=10, sample_size=10),
        warnings=(),
        timing=ProfilingTiming(started_at=TIMESTAMP, completed_at=TIMESTAMP, duration_ms=1),
    )


def hypotheses_for(
    hypotheses: tuple[ContextHypothesis, ...], field: ContextField
) -> list[ContextHypothesis]:
    return [h for h in hypotheses if h.context_field is field]


# ---------------------------------------------------------------------------
# AC-02: candidate_keys
# ---------------------------------------------------------------------------


def test_identifier_typed_column_yields_high_confidence_candidate_key() -> None:
    column = make_column("order_id", 0)
    profile = make_dataset_profile((make_column_profile(column, InferredColumnType.IDENTIFIER),))

    hypotheses = hypotheses_for(infer_context_hypotheses(profile), ContextField.CANDIDATE_KEYS)

    assert len(hypotheses) == 1
    assert hypotheses[0].proposed_value == "order_id"
    assert hypotheses[0].confidence == 0.9
    assert hypotheses[0].provenance is Provenance.CALCULATED
    assert hypotheses[0].related_columns == (column,)
    assert hypotheses[0].evidence_ids == ()


def test_text_typed_likely_identifier_yields_lower_confidence_key() -> None:
    column = make_column("order_id", 0)
    profile = make_dataset_profile(
        (make_column_profile(column, InferredColumnType.TEXT, metrics={"likely_identifier": True}),)
    )

    hypotheses = hypotheses_for(infer_context_hypotheses(profile), ContextField.CANDIDATE_KEYS)

    assert len(hypotheses) == 1
    assert hypotheses[0].confidence == 0.7


def test_text_typed_column_without_likely_identifier_yields_no_candidate_key() -> None:
    column = make_column("notes", 0)
    profile = make_dataset_profile(
        (
            make_column_profile(
                column, InferredColumnType.TEXT, metrics={"likely_identifier": False}
            ),
        )
    )

    hypotheses = hypotheses_for(infer_context_hypotheses(profile), ContextField.CANDIDATE_KEYS)

    assert hypotheses == []


def test_categorical_typed_column_never_yields_candidate_key() -> None:
    column = make_column("region", 0)
    profile = make_dataset_profile(
        (
            make_column_profile(
                column, InferredColumnType.CATEGORICAL, metrics={"likely_identifier": True}
            ),
        )
    )

    hypotheses = hypotheses_for(infer_context_hypotheses(profile), ContextField.CANDIDATE_KEYS)

    assert hypotheses == []


def test_multiple_candidate_key_columns_each_yield_a_hypothesis() -> None:
    profile = make_dataset_profile(
        (
            make_column_profile(make_column("order_id", 0), InferredColumnType.IDENTIFIER),
            make_column_profile(make_column("customer_id", 1), InferredColumnType.IDENTIFIER),
        )
    )

    hypotheses = hypotheses_for(infer_context_hypotheses(profile), ContextField.CANDIDATE_KEYS)

    assert {h.proposed_value for h in hypotheses} == {"order_id", "customer_id"}


# ---------------------------------------------------------------------------
# AC-02: business_dates / measure_roles / dimensions
# ---------------------------------------------------------------------------


def test_date_typed_columns_yield_business_date_hypotheses() -> None:
    profile = make_dataset_profile(
        (make_column_profile(make_column("order_date", 0), InferredColumnType.DATE),)
    )

    hypotheses = hypotheses_for(infer_context_hypotheses(profile), ContextField.BUSINESS_DATES)

    assert len(hypotheses) == 1
    assert hypotheses[0].proposed_value == "order_date"
    assert hypotheses[0].confidence == 0.9


def test_numeric_typed_columns_yield_measure_role_hypotheses() -> None:
    profile = make_dataset_profile(
        (make_column_profile(make_column("quantity", 0), InferredColumnType.NUMERIC),)
    )

    hypotheses = hypotheses_for(infer_context_hypotheses(profile), ContextField.MEASURE_ROLES)

    assert len(hypotheses) == 1
    assert hypotheses[0].proposed_value == "quantity"
    assert hypotheses[0].confidence == 0.75


def test_categorical_typed_columns_yield_dimension_hypotheses() -> None:
    profile = make_dataset_profile(
        (make_column_profile(make_column("region", 0), InferredColumnType.CATEGORICAL),)
    )

    hypotheses = hypotheses_for(infer_context_hypotheses(profile), ContextField.DIMENSIONS)

    assert len(hypotheses) == 1
    assert hypotheses[0].proposed_value == "region"
    assert hypotheses[0].confidence == 0.7


def test_no_matching_columns_yields_no_hypotheses_for_role_fields() -> None:
    profile = make_dataset_profile(
        (make_column_profile(make_column("notes", 0), InferredColumnType.TEXT),)
    )

    hypotheses = infer_context_hypotheses(profile)

    assert hypotheses_for(hypotheses, ContextField.BUSINESS_DATES) == []
    assert hypotheses_for(hypotheses, ContextField.MEASURE_ROLES) == []
    assert hypotheses_for(hypotheses, ContextField.DIMENSIONS) == []


# ---------------------------------------------------------------------------
# AC-02: row_grain
# ---------------------------------------------------------------------------


def test_row_grain_hypothesis_when_exactly_one_candidate_key() -> None:
    profile = make_dataset_profile(
        (make_column_profile(make_column("order_id", 0), InferredColumnType.IDENTIFIER),)
    )

    hypotheses = hypotheses_for(infer_context_hypotheses(profile), ContextField.ROW_GRAIN)

    assert len(hypotheses) == 1
    assert hypotheses[0].proposed_value == "One row per order_id"


def test_row_grain_no_hypothesis_when_zero_candidate_keys() -> None:
    profile = make_dataset_profile(
        (make_column_profile(make_column("notes", 0), InferredColumnType.TEXT),)
    )

    hypotheses = hypotheses_for(infer_context_hypotheses(profile), ContextField.ROW_GRAIN)

    assert hypotheses == []


def test_row_grain_no_hypothesis_when_multiple_candidate_keys() -> None:
    profile = make_dataset_profile(
        (
            make_column_profile(make_column("order_id", 0), InferredColumnType.IDENTIFIER),
            make_column_profile(make_column("customer_id", 1), InferredColumnType.IDENTIFIER),
        )
    )

    hypotheses = hypotheses_for(infer_context_hypotheses(profile), ContextField.ROW_GRAIN)

    assert hypotheses == []


# ---------------------------------------------------------------------------
# AC-02: primary_entity
# ---------------------------------------------------------------------------


def test_primary_entity_hypothesis_when_key_matches_id_suffix() -> None:
    profile = make_dataset_profile(
        (make_column_profile(make_column("order_id", 0), InferredColumnType.IDENTIFIER),)
    )

    hypotheses = hypotheses_for(infer_context_hypotheses(profile), ContextField.PRIMARY_ENTITY)

    assert len(hypotheses) == 1
    assert hypotheses[0].proposed_value == "order"


def test_primary_entity_no_hypothesis_when_key_does_not_match_id_suffix() -> None:
    profile = make_dataset_profile(
        (make_column_profile(make_column("sku", 0), InferredColumnType.IDENTIFIER),)
    )

    hypotheses = hypotheses_for(infer_context_hypotheses(profile), ContextField.PRIMARY_ENTITY)

    assert hypotheses == []


def test_primary_entity_no_hypothesis_when_multiple_candidate_keys() -> None:
    profile = make_dataset_profile(
        (
            make_column_profile(make_column("order_id", 0), InferredColumnType.IDENTIFIER),
            make_column_profile(make_column("customer_id", 1), InferredColumnType.IDENTIFIER),
        )
    )

    hypotheses = hypotheses_for(infer_context_hypotheses(profile), ContextField.PRIMARY_ENTITY)

    assert hypotheses == []


# ---------------------------------------------------------------------------
# AC-02: probable_domain
# ---------------------------------------------------------------------------


def test_probable_domain_hypothesis_when_enough_markers_match() -> None:
    profile = make_dataset_profile(
        (
            make_column_profile(make_column("order_id", 0), InferredColumnType.IDENTIFIER),
            make_column_profile(make_column("customer_name", 1), InferredColumnType.TEXT),
            make_column_profile(make_column("product", 2), InferredColumnType.CATEGORICAL),
        )
    )

    hypotheses = hypotheses_for(infer_context_hypotheses(profile), ContextField.PROBABLE_DOMAIN)

    assert len(hypotheses) == 1
    assert hypotheses[0].proposed_value == "Sales / order transactions"


def test_probable_domain_no_hypothesis_below_match_boundary() -> None:
    profile = make_dataset_profile(
        (
            make_column_profile(make_column("order_id", 0), InferredColumnType.IDENTIFIER),
            make_column_profile(make_column("customer_name", 1), InferredColumnType.TEXT),
        )
    )

    hypotheses = hypotheses_for(infer_context_hypotheses(profile), ContextField.PROBABLE_DOMAIN)

    assert hypotheses == []


# ---------------------------------------------------------------------------
# AC-02: currency_behavior / expected_business_rules always empty
# ---------------------------------------------------------------------------


def test_currency_behavior_and_expected_business_rules_never_produce_hypotheses() -> None:
    profile = make_dataset_profile(
        (
            make_column_profile(make_column("order_id", 0), InferredColumnType.IDENTIFIER),
            make_column_profile(make_column("unit_price", 1), InferredColumnType.NUMERIC),
        )
    )

    hypotheses = infer_context_hypotheses(profile)

    assert hypotheses_for(hypotheses, ContextField.CURRENCY_BEHAVIOR) == []
    assert hypotheses_for(hypotheses, ContextField.EXPECTED_BUSINESS_RULES) == []


# ---------------------------------------------------------------------------
# AC-05: consolidation
# ---------------------------------------------------------------------------


def test_consolidation_unions_role_field_hypotheses_and_averages_confidence() -> None:
    profile = make_dataset_profile(
        (
            make_column_profile(make_column("quantity", 0), InferredColumnType.NUMERIC),
            make_column_profile(make_column("unit_price", 1), InferredColumnType.NUMERIC),
        )
    )

    context = infer_dataset_context(profile)

    assert context.measure_roles.value == ("quantity", "unit_price")
    assert context.measure_roles.confidence == pytest.approx(0.75)
    assert context.measure_roles.confirmation_state is ConfirmationState.INFERRED


def test_consolidation_role_field_value_is_deterministically_ordered() -> None:
    profile = make_dataset_profile(
        (
            make_column_profile(make_column("unit_price", 0), InferredColumnType.NUMERIC),
            make_column_profile(make_column("quantity", 1), InferredColumnType.NUMERIC),
        )
    )

    context = infer_dataset_context(profile)

    assert context.measure_roles.value == ("quantity", "unit_price")


def test_consolidation_single_value_field_selects_highest_confidence() -> None:
    higher = ContextHypothesis(
        hypothesis_id="ctx-primary_entity-1",
        context_field=ContextField.PRIMARY_ENTITY,
        proposed_value="order",
        confidence=0.8,
        provenance=Provenance.CALCULATED,
        related_columns=(),
        evidence_ids=(),
        rationale="stronger signal",
    )
    lower = ContextHypothesis(
        hypothesis_id="ctx-primary_entity-2",
        context_field=ContextField.PRIMARY_ENTITY,
        proposed_value="transaction",
        confidence=0.4,
        provenance=Provenance.CALCULATED,
        related_columns=(),
        evidence_ids=(),
        rationale="weaker signal",
    )

    context = consolidate_dataset_context((lower, higher))

    assert context.primary_entity.value == "order"
    assert context.primary_entity.confidence == 0.8


def test_consolidation_ignores_superseded_hypotheses() -> None:
    superseded = ContextHypothesis(
        hypothesis_id="ctx-primary_entity-1",
        context_field=ContextField.PRIMARY_ENTITY,
        proposed_value="stale",
        confidence=0.9,
        provenance=Provenance.CALCULATED,
        related_columns=(),
        evidence_ids=(),
        rationale="superseded",
        superseded=True,
    )

    context = consolidate_dataset_context((superseded,))

    assert context.primary_entity.confirmation_state is ConfirmationState.UNKNOWN
    assert context.primary_entity.confidence == 0.0


def test_consolidation_falls_back_to_unknown_for_every_field_with_no_hypotheses() -> None:
    context = consolidate_dataset_context(())

    for field in ContextField:
        field_value = getattr(context, field.value)
        assert field_value.confirmation_state is ConfirmationState.UNKNOWN
        assert field_value.confidence == 0.0

    assert context.candidate_keys.value == ()
    assert context.probable_domain.value == "unknown"


# ---------------------------------------------------------------------------
# AC-03: no AI/LLM import
# ---------------------------------------------------------------------------


def test_no_ai_boundary_or_ai_provider_import_in_heuristics_module() -> None:
    module_path = (
        REPO_ROOT / "backend" / "src" / "trusttable_backend" / "context_inference" / "heuristics.py"
    )
    source = module_path.read_text(encoding="utf-8")
    import_lines = [line for line in source.splitlines() if line.startswith(("import ", "from "))]
    assert not any("ai_boundary" in line or "ai_provider" in line for line in import_lines)


# ---------------------------------------------------------------------------
# AC-04: no eval/exec
# ---------------------------------------------------------------------------


def test_no_eval_or_exec_in_heuristics_module() -> None:
    module_path = (
        REPO_ROOT / "backend" / "src" / "trusttable_backend" / "context_inference" / "heuristics.py"
    )
    source = module_path.read_text(encoding="utf-8")
    assert "eval(" not in source
    assert "exec(" not in source


# ---------------------------------------------------------------------------
# AC-05: determinism
# ---------------------------------------------------------------------------


def test_infer_dataset_context_is_deterministic() -> None:
    profile = make_dataset_profile(
        (
            make_column_profile(make_column("order_id", 0), InferredColumnType.IDENTIFIER),
            make_column_profile(make_column("order_date", 1), InferredColumnType.DATE),
            make_column_profile(make_column("quantity", 2), InferredColumnType.NUMERIC),
        )
    )

    first = infer_dataset_context(profile)
    second = infer_dataset_context(profile)

    assert first == second


# ---------------------------------------------------------------------------
# AC-06: real end-to-end check against the committed demo dataset
# ---------------------------------------------------------------------------


def _real_demo_dataset_context() -> DatasetProfile:
    content = DEMO_CSV_PATH.read_bytes()
    parsed = parse_csv(content)
    return compute_dataset_profile(
        parsed.parsed_dataset.columns,
        parsed.rows,
        parsed.parsed_dataset.sampling,
        as_of=date(2026, 8, 24),
    )


def _role_values(field_value: ContextFieldValue) -> tuple[str, ...]:
    """Narrow a `ContextFieldValue.value` (typed `object`) to the
    `tuple[str, ...]` shape the four column-role fields always use."""
    value = field_value.value
    assert isinstance(value, tuple)
    return value


def test_real_demo_csv_context_matches_known_shape() -> None:
    profile = _real_demo_dataset_context()

    context = infer_dataset_context(profile)

    assert "order_id" in _role_values(context.candidate_keys)
    assert "order_date" in _role_values(context.business_dates)
    for measure in ("quantity", "unit_price", "discount_pct", "tax_pct", "line_total"):
        assert measure in _role_values(context.measure_roles)
    for dimension in ("category", "region"):
        assert dimension in _role_values(context.dimensions)

    assert context.row_grain.value == "One row per order_id"
    assert context.primary_entity.value == "order"
    assert context.probable_domain.value == "Sales / order transactions"
    assert context.probable_domain.confirmation_state is ConfirmationState.INFERRED

    assert context.currency_behavior.confirmation_state is ConfirmationState.UNKNOWN
    assert context.currency_behavior.confidence == 0.0
    assert context.expected_business_rules.confirmation_state is ConfirmationState.UNKNOWN
    assert context.expected_business_rules.confidence == 0.0


def test_real_demo_csv_context_is_deterministic() -> None:
    profile = _real_demo_dataset_context()

    first = infer_dataset_context(profile)
    second = infer_dataset_context(profile)

    assert first == second
