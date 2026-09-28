"""Tests for `ai_boundary.rule_generation` (`RULE-02` slice 2, `WP-081`).

Per case: exactly one of the supplied candidates is accepted and
produces the identical `canonical_value`, unmodified. Any value outside
the exact candidate set, wrong type, or extra/missing key is proven
rejected with a stated `RuleGenerationRejectionReason`, and
`RuleGenerationOutcome.canonical_value` is `None` on every rejection.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

import pytest

from trusttable_backend.ai_boundary.envelope import PromptEnvelope
from trusttable_backend.ai_boundary.rule_generation import (
    RULE_GENERATION_SCHEMA_VERSION,
    RuleGenerationRejectionReason,
    build_rule_generation_contract,
    rule_generation_json_schema,
    validate_rule_generation_output,
)
from trusttable_backend.domain.value_objects import Provenance

CANDIDATES = ("ny", "NY")


def well_formed_output(canonical_value: str = "NY", **overrides: object) -> dict[str, object]:
    output: dict[str, object] = {
        "schema_version": RULE_GENERATION_SCHEMA_VERSION,
        "provenance": Provenance.AI_INTERPRETATION.value,
        "canonical_value": canonical_value,
    }
    output.update(overrides)
    return output


# ---------------------------------------------------------------------------
# Acceptance: the model's answer, verbatim
# ---------------------------------------------------------------------------


def test_accepts_a_value_that_is_exactly_one_of_the_candidates() -> None:
    outcome = validate_rule_generation_output(well_formed_output("NY"), CANDIDATES)

    assert outcome.accepted is True
    assert outcome.canonical_value == "NY"
    assert outcome.rejection_reasons == ()
    assert outcome.safe_summary == "accepted"


def test_accepts_the_other_exact_candidate_too() -> None:
    outcome = validate_rule_generation_output(well_formed_output("ny"), CANDIDATES)

    assert outcome.accepted is True
    assert outcome.canonical_value == "ny"


# ---------------------------------------------------------------------------
# VALUE_NOT_CANDIDATE: the one violation this contract exists to prevent
# ---------------------------------------------------------------------------


def test_rejects_a_value_not_in_the_candidate_set() -> None:
    outcome = validate_rule_generation_output(well_formed_output("Ny"), CANDIDATES)

    assert outcome.accepted is False
    assert outcome.canonical_value is None
    assert outcome.rejection_reasons == (RuleGenerationRejectionReason.VALUE_NOT_CANDIDATE,)


def test_rejects_an_invented_value_entirely_absent_from_evidence() -> None:
    outcome = validate_rule_generation_output(well_formed_output("New York"), CANDIDATES)

    assert outcome.accepted is False
    assert RuleGenerationRejectionReason.VALUE_NOT_CANDIDATE in outcome.rejection_reasons


def test_rejects_empty_string_value() -> None:
    outcome = validate_rule_generation_output(well_formed_output(""), CANDIDATES)

    assert outcome.accepted is False
    assert RuleGenerationRejectionReason.VALUE_NOT_CANDIDATE in outcome.rejection_reasons


# ---------------------------------------------------------------------------
# Schema/type violations
# ---------------------------------------------------------------------------


def test_rejects_non_string_canonical_value() -> None:
    outcome = validate_rule_generation_output(well_formed_output(123), CANDIDATES)  # type: ignore[arg-type]

    assert outcome.accepted is False
    assert RuleGenerationRejectionReason.SCHEMA_INVALID in outcome.rejection_reasons
    assert outcome.canonical_value is None


def test_rejects_missing_required_key() -> None:
    output = well_formed_output()
    del output["canonical_value"]

    outcome = validate_rule_generation_output(output, CANDIDATES)

    assert outcome.accepted is False
    assert RuleGenerationRejectionReason.SCHEMA_INVALID in outcome.rejection_reasons


def test_rejects_wrong_schema_version() -> None:
    outcome = validate_rule_generation_output(
        well_formed_output(schema_version="rule_generation_v0"), CANDIDATES
    )

    assert outcome.accepted is False
    assert RuleGenerationRejectionReason.SCHEMA_INVALID in outcome.rejection_reasons


def test_rejects_non_mapping_output() -> None:
    outcome = validate_rule_generation_output("not a mapping", CANDIDATES)  # type: ignore[arg-type]

    assert outcome.accepted is False
    assert outcome.rejection_reasons == (RuleGenerationRejectionReason.SCHEMA_INVALID,)
    assert outcome.canonical_value is None


def test_rejects_wrong_provenance() -> None:
    outcome = validate_rule_generation_output(
        well_formed_output(provenance="calculated"), CANDIDATES
    )

    assert outcome.accepted is False
    assert RuleGenerationRejectionReason.INVALID_PROVENANCE in outcome.rejection_reasons


def test_rejects_unsupported_control_field() -> None:
    outcome = validate_rule_generation_output(well_formed_output(override_risk_score=0), CANDIDATES)

    assert outcome.accepted is False
    assert RuleGenerationRejectionReason.UNSUPPORTED_CONTROL_FIELD in outcome.rejection_reasons


# ---------------------------------------------------------------------------
# Non-leakage
# ---------------------------------------------------------------------------


def test_safe_summary_never_contains_the_invented_value() -> None:
    distinctive_marker = "SECRET_INVENTED_VALUE_XYZ"
    outcome = validate_rule_generation_output(well_formed_output(distinctive_marker), CANDIDATES)

    assert outcome.accepted is False
    assert distinctive_marker not in outcome.safe_summary


# ---------------------------------------------------------------------------
# Contract/schema construction
# ---------------------------------------------------------------------------


def test_contract_schema_enumerates_exactly_the_supplied_candidates() -> None:
    contract = build_rule_generation_contract(CANDIDATES)

    properties = cast(Mapping[str, Mapping[str, object]], contract.json_schema["properties"])
    assert properties["canonical_value"]["enum"] == list(CANDIDATES)


def test_contract_raises_for_fewer_than_two_candidates() -> None:
    with pytest.raises(ValueError):
        build_rule_generation_contract(("NY",))


def test_mock_output_factory_produces_a_value_the_validator_accepts() -> None:
    contract = build_rule_generation_contract(CANDIDATES)
    assert contract.mock_output_factory is not None
    mock_output = contract.mock_output_factory(_empty_envelope())

    outcome = validate_rule_generation_output(mock_output, CANDIDATES)
    assert outcome.accepted is True


def _empty_envelope() -> PromptEnvelope:
    """`mock_output_factory` for this contract ignores its envelope
    argument entirely (the mock's answer never depends on it) — a bare,
    real, empty envelope proves that without needing any evidence."""
    return PromptEnvelope(
        task="unused",
        computed_evidence=(),
        confirmed_context={},
        untrusted_dataset_samples=(),
    )


def test_rule_generation_json_schema_rejects_empty_candidates_shape() -> None:
    schema = rule_generation_json_schema(())
    assert schema["properties"]["canonical_value"]["enum"] == []


def test_rejection_reason_set_is_exactly_this_contracts_own_closed_set() -> None:
    assert {reason.value for reason in RuleGenerationRejectionReason} == {
        "schema_invalid",
        "unsupported_control_field",
        "invalid_provenance",
        "value_not_candidate",
    }
