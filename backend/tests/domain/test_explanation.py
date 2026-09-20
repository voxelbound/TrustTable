"""Tests for `domain.explanation.FindingExplanation` (`AI-05`, `WP-061`).

Covers AC-01: non-empty-narrative and provenance-membership invariants.
"""

from __future__ import annotations

import pytest

from trusttable_backend.domain.explanation import (
    BusinessImpactStatement,
    FindingExplanation,
    ImpactBasis,
    ProposedValidationRule,
    ValidationRuleType,
    derive_impact_basis,
)
from trusttable_backend.domain.value_objects import ColumnReference, Provenance


def make_explanation(**overrides: object) -> FindingExplanation:
    fields: dict[str, object] = {
        "narrative": "This finding matters because of X.",
        "provenance": Provenance.DETERMINISTIC_FALLBACK,
        "referenced_evidence_ids": ("ev-1",),
        "referenced_columns": (),
    }
    fields.update(overrides)
    return FindingExplanation(**fields)  # type: ignore[arg-type]


def test_finding_explanation_constructs_with_deterministic_fallback_provenance() -> None:
    explanation = make_explanation(provenance=Provenance.DETERMINISTIC_FALLBACK)
    assert explanation.provenance is Provenance.DETERMINISTIC_FALLBACK


def test_finding_explanation_constructs_with_ai_interpretation_provenance() -> None:
    explanation = make_explanation(provenance=Provenance.AI_INTERPRETATION)
    assert explanation.provenance is Provenance.AI_INTERPRETATION


def test_finding_explanation_rejects_empty_narrative() -> None:
    with pytest.raises(ValueError, match="narrative"):
        make_explanation(narrative="")


@pytest.mark.parametrize(
    "provenance",
    [Provenance.CALCULATED, Provenance.USER_CONFIRMED, Provenance.USER_CORRECTED],
)
def test_finding_explanation_rejects_disallowed_provenance(provenance: Provenance) -> None:
    with pytest.raises(ValueError, match="provenance"):
        make_explanation(provenance=provenance)


def test_finding_explanation_provider_fields_default_to_none() -> None:
    explanation = make_explanation()
    assert explanation.provider_name is None
    assert explanation.model_identifier is None


def test_finding_explanation_provider_fields_carry_supplied_values() -> None:
    explanation = make_explanation(provider_name="mock", model_identifier="mock-v1")
    assert explanation.provider_name == "mock"
    assert explanation.model_identifier == "mock-v1"


def test_finding_explanation_carries_referenced_evidence_and_columns() -> None:
    column = ColumnReference(original_name="qty", internal_key="qty", ordinal=0)
    explanation = make_explanation(
        referenced_evidence_ids=("ev-1", "ev-2"), referenced_columns=(column,)
    )
    assert explanation.referenced_evidence_ids == ("ev-1", "ev-2")
    assert explanation.referenced_columns == (column,)


# ---------------------------------------------------------------------------
# AI-08: the three further advisory sections
# ---------------------------------------------------------------------------


def test_the_advisory_sections_default_to_empty_for_a_bare_explanation() -> None:
    explanation = make_explanation()
    assert explanation.business_impact == ()
    assert explanation.remediation == ()
    assert explanation.validation_rule is None


def test_validation_rule_types_are_exactly_the_documented_product_requirement_set() -> None:
    # docs/product-requirements.md section 13, "Supported rule types".
    assert {member.value for member in ValidationRuleType} == {
        "not_null",
        "unique",
        "accepted_values",
        "numeric_range",
        "date_range",
        "regex",
        "max_missing_percentage",
        "approximate_equality",
        "expression_comparison",
        "conditional_rule",
        "max_duplicate_percentage",
    }


def test_there_is_no_evidence_basis_a_consequence_can_award_itself() -> None:
    """The deterministic evidence establishes what was found in the data, not
    what it costs a business, so no impact statement can be presented as
    evidence-backed: the closed basis set has no such member."""
    assert {member.value for member in ImpactBasis} == {"confirmed_context", "assumption"}
    assert not hasattr(ImpactBasis, "EVIDENCE")


def test_a_context_informed_statement_cites_context_and_still_states_its_condition() -> None:
    statement = BusinessImpactStatement(
        statement="x",
        basis=ImpactBasis.CONFIRMED_CONTEXT,
        context_fields=("row_grain",),
        assumption="rows are summed per order",
    )
    assert statement.assumption == "rows are summed per order"
    with pytest.raises(ValueError, match="cite confirmed context"):
        BusinessImpactStatement(
            statement="x", basis=ImpactBasis.CONFIRMED_CONTEXT, assumption="if y"
        )
    with pytest.raises(ValueError, match="state its assumption"):
        BusinessImpactStatement(
            statement="x", basis=ImpactBasis.CONFIRMED_CONTEXT, context_fields=("row_grain",)
        )


def test_the_basis_is_derived_from_the_cited_context_fields_alone() -> None:
    assert derive_impact_basis(()) is ImpactBasis.ASSUMPTION
    assert derive_impact_basis(("row_grain",)) is ImpactBasis.CONFIRMED_CONTEXT
    assert derive_impact_basis(("row_grain", "primary_entity")) is ImpactBasis.CONFIRMED_CONTEXT


def test_a_conditional_statement_must_state_its_assumption() -> None:
    statement = BusinessImpactStatement(
        statement="x", basis=ImpactBasis.ASSUMPTION, assumption="it feeds reports"
    )
    assert statement.assumption == "it feeds reports"
    with pytest.raises(ValueError, match="state its assumption"):
        BusinessImpactStatement(statement="x", basis=ImpactBasis.ASSUMPTION)
    with pytest.raises(ValueError, match="state its assumption"):
        BusinessImpactStatement(statement="x", basis=ImpactBasis.ASSUMPTION, assumption="  ")
    with pytest.raises(ValueError, match="no confirmed context"):
        BusinessImpactStatement(
            statement="x",
            basis=ImpactBasis.ASSUMPTION,
            assumption="it feeds reports",
            context_fields=("row_grain",),
        )


def test_a_conditional_statement_may_cite_its_triggering_evidence() -> None:
    statement = BusinessImpactStatement(
        statement="x",
        basis=ImpactBasis.ASSUMPTION,
        assumption="it feeds reports",
        evidence_ids=("ev-1",),
    )
    assert statement.evidence_ids == ("ev-1",)


def test_an_impact_statement_must_not_be_empty() -> None:
    with pytest.raises(ValueError, match="statement"):
        BusinessImpactStatement(statement="", basis=ImpactBasis.ASSUMPTION, assumption="a")


def test_a_proposed_rule_is_always_proposed_and_never_active() -> None:
    rule = ProposedValidationRule(
        rule_type=ValidationRuleType.NOT_NULL, columns=(), description="Values should be filled."
    )
    assert rule.status == "proposed"
    assert not hasattr(rule, "active")
    assert not hasattr(rule, "enabled")
    with pytest.raises(AttributeError):
        rule.status = "active"  # type: ignore[misc]


def test_a_proposed_rule_needs_a_description() -> None:
    with pytest.raises(ValueError, match="description"):
        ProposedValidationRule(rule_type=ValidationRuleType.UNIQUE, columns=(), description="")


def test_an_explanation_carries_and_validates_its_advisory_sections() -> None:
    rule = ProposedValidationRule(
        rule_type=ValidationRuleType.UNIQUE, columns=(), description="Rows should be unique."
    )
    impact = BusinessImpactStatement(statement="x", basis=ImpactBasis.ASSUMPTION, assumption="a")
    explanation = make_explanation(
        business_impact=(impact,), remediation=("Review the rows.",), validation_rule=rule
    )
    assert explanation.business_impact == (impact,)
    assert explanation.remediation == ("Review the rows.",)
    assert explanation.validation_rule is rule
    with pytest.raises(ValueError, match="remediation"):
        make_explanation(remediation=("",))
