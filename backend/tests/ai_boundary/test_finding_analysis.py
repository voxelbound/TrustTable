"""Tests for the structured finding-analysis contract and its role-aware
validator (`AI-08`, `docs/decision-log.md` D-040).

Every rejection reason is proven with a positive (rejected), a negative
(honest text still accepted) and, where a bound exists, a boundary case.
The end-to-end relationships (real route, real provider factory) live in
`tests/api/test_finding_analysis_end_to_end.py`; this module proves the
validator and the contract in isolation.
"""

from __future__ import annotations

import copy
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from trusttable_backend.ai_boundary.envelope import PromptEnvelope
from trusttable_backend.ai_boundary.finding_analysis import (
    FINDING_ANALYSIS_CONTRACT_NAME,
    FINDING_ANALYSIS_INSTRUCTIONS,
    FINDING_ANALYSIS_MAX_OUTPUT_TOKENS,
    FINDING_ANALYSIS_SCHEMA_VERSION,
    MAX_IMPACT_STATEMENTS,
    MAX_REMEDIATION_STEPS,
    build_finding_analysis_contract,
    finding_analysis_json_schema,
    mock_finding_analysis_output,
    validate_finding_analysis_output,
)
from trusttable_backend.ai_boundary.validation import RejectionReason
from trusttable_backend.domain.evidence import Evidence, EvidenceType
from trusttable_backend.domain.explanation import ImpactBasis, ValidationRuleType
from trusttable_backend.domain.parsing import SamplingScope
from trusttable_backend.domain.value_objects import ColumnReference, RowReference

R = RejectionReason


def make_column(key: str = "quantity", ordinal: int = 0) -> ColumnReference:
    return ColumnReference(original_name=key, internal_key=key, ordinal=ordinal)


def make_evidence(
    evidence_id: str = "ev.1",
    *,
    columns: tuple[str, ...] = ("quantity",),
    row_numbers: tuple[int, ...] = (4, 9),
    payload: dict[str, object] | None = None,
    summary: str = "2 of 300 rows in 'quantity' hold negative values",
) -> Evidence:
    return Evidence(
        evidence_id=evidence_id,
        evidence_type=EvidenceType.METRIC,
        calculation_version="1",
        structured_payload=payload if payload is not None else {"negative_count": 2, "rows": 300},
        affected_columns=tuple(make_column(key, ordinal) for ordinal, key in enumerate(columns)),
        affected_row_references=tuple(RowReference(row_number=n) for n in row_numbers),
        scope=SamplingScope.FULL,
        display_safe_summary=summary,
    )


def make_envelope(
    evidence: tuple[Evidence, ...] | None = None,
    *,
    confirmed_context: Mapping[str, object] | None = None,
) -> PromptEnvelope:
    return PromptEnvelope(
        task="Analyze the finding.",
        computed_evidence=evidence if evidence is not None else (make_evidence(),),
        confirmed_context=confirmed_context or {},
        untrusted_dataset_samples=(),
        sample_sending_enabled=False,
    )


def good_output() -> dict[str, Any]:
    """A realistic, grounded, well-formed output for `make_envelope()`."""
    return {
        "schema_version": FINDING_ANALYSIS_SCHEMA_VERSION,
        "provenance": "ai_interpretation",
        "explanation": (
            "2 of 300 rows in the quantity column hold negative values, which is unusual "
            "for a quantity."
        ),
        "business_impact": [
            {
                "basis": "evidence",
                "statement": "Negative quantities can reduce totals computed from this column.",
                "evidence_ids": ["ev.1"],
                "context_fields": [],
                "assumption": "",
            },
            {
                "basis": "assumption",
                "statement": "Reports built on this column may understate volumes.",
                "evidence_ids": [],
                "context_fields": [],
                "assumption": "the column is summed in reports",
            },
        ],
        "remediation": [
            "Review the 2 flagged rows and confirm whether the negative values are returns "
            "or entry errors.",
            "Correct wrong values in the source system.",
        ],
        "validation_rule": {
            "rule_type": "numeric_range",
            "columns": ["quantity"],
            "description": "Values in quantity should be zero or greater.",
        },
        "referenced_evidence_ids": ["ev.1"],
        "referenced_columns": ["quantity"],
    }


def check(
    output: object,
    envelope: PromptEnvelope | None = None,
    facts: dict[str, float] | None = None,
) -> tuple[bool, tuple[RejectionReason, ...]]:
    outcome = validate_finding_analysis_output(
        output,  # type: ignore[arg-type]
        envelope if envelope is not None else make_envelope(),
        known_numeric_facts=facts if facts is not None else {"negative_count": 2.0, "rows": 300.0},
    )
    return outcome.accepted, outcome.rejection_reasons


def mutated(mutator: Any) -> dict[str, Any]:
    output = copy.deepcopy(good_output())
    mutator(output)
    return output


# ---------------------------------------------------------------------------
# Acceptance
# ---------------------------------------------------------------------------


def test_well_formed_grounded_output_is_accepted() -> None:
    assert check(good_output()) == (True, ())


def test_accepted_outcome_summary_is_the_word_accepted() -> None:
    outcome = validate_finding_analysis_output(
        good_output(), make_envelope(), known_numeric_facts={"negative_count": 2.0, "rows": 300.0}
    )
    assert outcome.safe_summary == "accepted"


@pytest.mark.parametrize(
    "envelope",
    [
        make_envelope(),
        make_envelope((make_evidence("ev.a", columns=("a", "b")), make_evidence("ev.b"))),
        make_envelope((make_evidence(columns=()),)),
    ],
)
def test_mock_default_output_is_accepted_for_any_real_evidence(envelope: PromptEnvelope) -> None:
    output = mock_finding_analysis_output(envelope)
    facts: dict[str, float] = {}
    outcome = validate_finding_analysis_output(output, envelope, known_numeric_facts=facts)
    assert outcome.accepted, outcome.safe_summary


def test_mock_default_output_is_accepted_when_there_is_no_evidence() -> None:
    envelope = make_envelope(())
    output = mock_finding_analysis_output(envelope)
    outcome = validate_finding_analysis_output(output, envelope, known_numeric_facts={})
    assert outcome.accepted, outcome.safe_summary
    assert output["business_impact"][0]["basis"] == "assumption"  # type: ignore[index]


def test_conditional_statement_may_use_consequence_terms_when_labelled_an_assumption() -> None:
    output = mutated(
        lambda o: o["business_impact"].append(
            {
                "basis": "assumption",
                "statement": "Customers could receive incorrect invoices and refunds.",
                "evidence_ids": ["ev.1"],
                "context_fields": [],
                "assumption": "these rows feed customer billing",
            }
        )
    )
    assert check(output) == (True, ())


# ---------------------------------------------------------------------------
# Schema, types, bounds, control fields
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("garbage", [None, "text", 3, [], [1, 2], object()])
def test_non_mapping_output_is_schema_invalid_and_never_raises(garbage: object) -> None:
    assert check(garbage) == (False, (R.SCHEMA_INVALID,))


def test_empty_mapping_is_schema_invalid() -> None:
    accepted, reasons = check({})
    assert not accepted
    assert reasons == (R.SCHEMA_INVALID,)


@pytest.mark.parametrize(
    "key",
    [
        "schema_version",
        "provenance",
        "explanation",
        "business_impact",
        "remediation",
        "validation_rule",
        "referenced_evidence_ids",
        "referenced_columns",
    ],
)
def test_each_required_key_is_required(key: str) -> None:
    output = good_output()
    del output[key]
    accepted, reasons = check(output)
    assert not accepted
    assert R.SCHEMA_INVALID in reasons


def test_wrong_schema_version_is_schema_invalid() -> None:
    accepted, reasons = check(mutated(lambda o: o.update(schema_version="1")))
    assert not accepted and R.SCHEMA_INVALID in reasons


@pytest.mark.parametrize("extra", ["severity", "trust_score", "remove_finding", "risk", "notes"])
def test_extra_top_level_key_is_an_unsupported_control_field(extra: str) -> None:
    accepted, reasons = check(mutated(lambda o: o.update({extra: "high"})))
    assert not accepted
    assert R.UNSUPPORTED_CONTROL_FIELD in reasons


def test_extra_key_inside_an_impact_statement_is_an_unsupported_control_field() -> None:
    output = mutated(lambda o: o["business_impact"][0].update(severity="low"))
    accepted, reasons = check(output)
    assert not accepted and R.UNSUPPORTED_CONTROL_FIELD in reasons


def test_extra_key_inside_the_rule_is_an_unsupported_control_field() -> None:
    output = mutated(lambda o: o["validation_rule"].update(active=True))
    accepted, reasons = check(output)
    assert not accepted and R.UNSUPPORTED_CONTROL_FIELD in reasons


def test_wrong_provenance_is_rejected() -> None:
    accepted, reasons = check(mutated(lambda o: o.update(provenance="calculated")))
    assert not accepted and reasons == (R.INVALID_PROVENANCE,)


def test_non_string_provenance_is_schema_invalid() -> None:
    accepted, reasons = check(mutated(lambda o: o.update(provenance=5)))
    assert not accepted and R.SCHEMA_INVALID in reasons


@pytest.mark.parametrize("value", [5, None, "", "   ", ["a"]])
def test_explanation_must_be_a_non_blank_string(value: object) -> None:
    accepted, reasons = check(mutated(lambda o: o.update(explanation=value)))
    assert not accepted and R.SCHEMA_INVALID in reasons


def test_explanation_length_boundary() -> None:
    at_limit = "x" * 600
    over_limit = "x" * 601
    assert check(mutated(lambda o: o.update(explanation=at_limit)))[0] is True
    accepted, reasons = check(mutated(lambda o: o.update(explanation=over_limit)))
    assert not accepted and R.SCHEMA_INVALID in reasons


def test_impact_statement_count_boundary() -> None:
    entry = good_output()["business_impact"][0]
    assert check(mutated(lambda o: o.update(business_impact=[entry] * MAX_IMPACT_STATEMENTS)))[0]
    for bad in ([], [entry] * (MAX_IMPACT_STATEMENTS + 1), "text", None):
        accepted, reasons = check(mutated(lambda o, b=bad: o.update(business_impact=b)))
        assert not accepted and R.SCHEMA_INVALID in reasons


def test_remediation_step_count_boundary() -> None:
    step = "Correct wrong values in the source system."
    assert check(mutated(lambda o: o.update(remediation=[step] * MAX_REMEDIATION_STEPS)))[0]
    for bad in ([], [step] * (MAX_REMEDIATION_STEPS + 1), "text", None, [5]):
        accepted, reasons = check(mutated(lambda o, b=bad: o.update(remediation=b)))
        assert not accepted and R.SCHEMA_INVALID in reasons


@pytest.mark.parametrize("bad_type", ["numeric_range_extra", "range", "", 4, None])
def test_rule_type_must_be_in_the_closed_set(bad_type: object) -> None:
    output = mutated(lambda o: o["validation_rule"].update(rule_type=bad_type))
    accepted, reasons = check(output)
    assert not accepted and R.SCHEMA_INVALID in reasons


@pytest.mark.parametrize("rule_type", [member.value for member in ValidationRuleType])
def test_every_documented_rule_type_is_accepted(rule_type: str) -> None:
    output = mutated(lambda o: o["validation_rule"].update(rule_type=rule_type))
    assert check(output) == (True, ())


def test_rule_must_carry_all_keys() -> None:
    output = mutated(lambda o: o["validation_rule"].pop("description"))
    accepted, reasons = check(output)
    assert not accepted and R.SCHEMA_INVALID in reasons


def test_rule_must_be_an_object() -> None:
    accepted, reasons = check(mutated(lambda o: o.update(validation_rule="not_null")))
    assert not accepted and R.SCHEMA_INVALID in reasons


def test_rule_column_count_boundary() -> None:
    columns = tuple(f"c{i}" for i in range(6))
    envelope = make_envelope((make_evidence(columns=columns),))
    output = mutated(lambda o: o["validation_rule"].update(columns=list(columns[:5])))
    output["referenced_columns"] = list(columns[:5])
    assert check(output, envelope)[0] is True
    output["validation_rule"]["columns"] = list(columns)
    accepted, reasons = check(output, envelope)
    assert not accepted and R.SCHEMA_INVALID in reasons


def test_impact_statement_missing_keys_is_schema_invalid() -> None:
    output = mutated(lambda o: o["business_impact"][0].pop("assumption"))
    accepted, reasons = check(output)
    assert not accepted and R.SCHEMA_INVALID in reasons


def test_impact_statement_must_be_an_object() -> None:
    accepted, reasons = check(mutated(lambda o: o.update(business_impact=["text"])))
    assert not accepted and R.SCHEMA_INVALID in reasons


def test_unknown_basis_is_schema_invalid() -> None:
    output = mutated(lambda o: o["business_impact"][0].update(basis="fact"))
    accepted, reasons = check(output)
    assert not accepted and R.SCHEMA_INVALID in reasons


def test_assumption_length_boundary() -> None:
    def set_assumption(text: str) -> dict[str, Any]:
        return mutated(lambda o: o["business_impact"][1].update(assumption=text))

    assert check(set_assumption("y" * 300))[0] is True
    accepted, reasons = check(set_assumption("y" * 301))
    assert not accepted and R.SCHEMA_INVALID in reasons


# ---------------------------------------------------------------------------
# Grounding: evidence ids, columns, context fields
# ---------------------------------------------------------------------------


def test_unknown_top_level_evidence_id_is_rejected() -> None:
    output = mutated(lambda o: o.update(referenced_evidence_ids=["ev.1", "ev.999"]))
    assert check(output) == (False, (R.UNKNOWN_EVIDENCE_ID,))


def test_referenced_evidence_ids_must_be_non_empty_when_evidence_was_sent() -> None:
    accepted, reasons = check(mutated(lambda o: o.update(referenced_evidence_ids=[])))
    assert not accepted and R.SCHEMA_INVALID in reasons


def test_referenced_evidence_ids_may_be_empty_when_no_evidence_was_sent() -> None:
    envelope = make_envelope(())
    output = mutated(
        lambda o: o.update(
            referenced_evidence_ids=[],
            referenced_columns=[],
            business_impact=[o["business_impact"][1]],
            validation_rule={
                "rule_type": "not_null",
                "columns": [],
                "description": "Values should not be blank.",
            },
            explanation="A check flagged this condition.",
            remediation=["Correct wrong values in the source system."],
        )
    )
    assert check(output, envelope, {}) == (True, ())


def test_unknown_referenced_column_is_rejected() -> None:
    output = mutated(lambda o: o.update(referenced_columns=["quantity", "ghost"]))
    assert check(output) == (False, (R.UNKNOWN_COLUMN,))


def test_unknown_rule_column_is_rejected() -> None:
    output = mutated(lambda o: o["validation_rule"].update(columns=["ghost"]))
    assert check(output) == (False, (R.UNKNOWN_COLUMN,))


def test_unknown_evidence_id_inside_an_impact_statement_is_rejected() -> None:
    output = mutated(lambda o: o["business_impact"][0].update(evidence_ids=["ev.404"]))
    accepted, reasons = check(output)
    assert not accepted and R.UNKNOWN_EVIDENCE_ID in reasons


def test_reference_lists_must_be_lists_of_strings() -> None:
    for key in ("referenced_evidence_ids", "referenced_columns"):
        for bad in ("ev.1", 3, [1], None):
            accepted, reasons = check(mutated(lambda o, k=key, b=bad: o.update({k: b})))
            assert not accepted and R.SCHEMA_INVALID in reasons


# --- basis rules ----------------------------------------------------------


def test_evidence_statement_without_evidence_is_an_unsupported_impact_claim() -> None:
    output = mutated(lambda o: o["business_impact"][0].update(evidence_ids=[]))
    assert check(output) == (False, (R.UNSUPPORTED_IMPACT_CLAIM,))


def test_evidence_statement_carrying_an_assumption_is_an_unsupported_impact_claim() -> None:
    output = mutated(lambda o: o["business_impact"][0].update(assumption="something holds"))
    assert check(output) == (False, (R.UNSUPPORTED_IMPACT_CLAIM,))


def test_assumption_statement_without_an_assumption_is_an_unsupported_impact_claim() -> None:
    output = mutated(lambda o: o["business_impact"][1].update(assumption=""))
    assert check(output) == (False, (R.UNSUPPORTED_IMPACT_CLAIM,))


def test_assumption_statement_with_only_whitespace_assumption_is_unsupported() -> None:
    output = mutated(lambda o: o["business_impact"][1].update(assumption="   "))
    assert check(output) == (False, (R.UNSUPPORTED_IMPACT_CLAIM,))


def test_assumption_statement_may_cite_the_triggering_evidence() -> None:
    output = mutated(lambda o: o["business_impact"][1].update(evidence_ids=["ev.1"]))
    assert check(output) == (True, ())


CONFIRMED = {"probable_domain": {"value": "Sales orders", "confirmation_state": "confirmed"}}


def context_statement(fields: list[str], assumption: str = "") -> dict[str, Any]:
    return {
        "basis": "confirmed_context",
        "statement": "Sales order totals depend on this quantity column being reliable.",
        "evidence_ids": [],
        "context_fields": fields,
        "assumption": assumption,
    }


def test_context_backed_statement_is_accepted_when_the_field_was_sent() -> None:
    envelope = make_envelope(confirmed_context=CONFIRMED)
    output = mutated(lambda o: o["business_impact"].append(context_statement(["probable_domain"])))
    assert check(output, envelope) == (True, ())


def test_context_backed_statement_is_rejected_when_no_context_was_sent() -> None:
    output = mutated(lambda o: o["business_impact"].append(context_statement(["probable_domain"])))
    accepted, reasons = check(output)
    assert not accepted
    assert R.UNKNOWN_CONTEXT_FIELD in reasons


def test_context_backed_statement_naming_an_unsent_field_is_rejected() -> None:
    envelope = make_envelope(confirmed_context=CONFIRMED)
    output = mutated(lambda o: o["business_impact"].append(context_statement(["row_grain"])))
    accepted, reasons = check(output, envelope)
    assert not accepted and R.UNKNOWN_CONTEXT_FIELD in reasons


def test_context_backed_statement_without_fields_is_an_unsupported_impact_claim() -> None:
    envelope = make_envelope(confirmed_context=CONFIRMED)
    output = mutated(lambda o: o["business_impact"].append(context_statement([])))
    accepted, reasons = check(output, envelope)
    assert not accepted and R.UNSUPPORTED_IMPACT_CLAIM in reasons


def test_context_backed_statement_carrying_an_assumption_is_unsupported() -> None:
    envelope = make_envelope(confirmed_context=CONFIRMED)
    output = mutated(
        lambda o: o["business_impact"].append(context_statement(["probable_domain"], "x holds"))
    )
    accepted, reasons = check(output, envelope)
    assert not accepted and R.UNSUPPORTED_IMPACT_CLAIM in reasons


def test_assumption_statement_citing_context_fields_is_unsupported() -> None:
    envelope = make_envelope(confirmed_context=CONFIRMED)
    output = mutated(lambda o: o["business_impact"][1].update(context_fields=["probable_domain"]))
    accepted, reasons = check(output, envelope)
    assert not accepted and R.UNSUPPORTED_IMPACT_CLAIM in reasons


def test_evidence_statement_citing_context_fields_is_unsupported() -> None:
    envelope = make_envelope(confirmed_context=CONFIRMED)
    output = mutated(lambda o: o["business_impact"][0].update(context_fields=["probable_domain"]))
    accepted, reasons = check(output, envelope)
    assert not accepted and R.UNSUPPORTED_IMPACT_CLAIM in reasons


# ---------------------------------------------------------------------------
# Consequence terms
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "statement",
    [
        "Negative quantities cause financial loss for the business.",
        "This could expose the company to regulatory penalties.",
        "Customers will be overcharged because of these rows.",
        "Revenue is understated by these rows.",
        "This creates a compliance and audit problem.",
        "Fraud risk increases with these values.",
    ],
)
def test_ungrounded_consequence_in_an_evidence_statement_is_rejected(statement: str) -> None:
    output = mutated(lambda o: o["business_impact"][0].update(statement=statement))
    assert check(output) == (False, (R.UNSUPPORTED_IMPACT_CLAIM,))


def test_consequence_term_in_the_explanation_must_be_grounded() -> None:
    output = mutated(lambda o: o.update(explanation="These rows cause financial loss."))
    assert check(output) == (False, (R.UNSUPPORTED_IMPACT_CLAIM,))


def test_consequence_term_present_in_the_evidence_is_grounded() -> None:
    evidence = make_evidence(
        columns=("revenue",), summary="2 of 300 rows in 'revenue' are negative"
    )
    envelope = make_envelope((evidence,))
    output = mutated(
        lambda o: o["business_impact"][0].update(
            statement="Negative revenue values can distort totals computed from this column."
        )
    )
    output["referenced_columns"] = ["revenue"]
    output["validation_rule"]["columns"] = ["revenue"]
    output["explanation"] = "2 of 300 rows in the revenue column are negative."
    output["remediation"] = ["Correct wrong revenue values in the source system."]
    accepted, reasons = check(output, envelope)
    assert accepted, reasons


def test_consequence_term_present_in_confirmed_context_is_grounded() -> None:
    context = {
        "probable_domain": {"value": "Sales and customer orders", "confirmation_state": "confirmed"}
    }
    envelope = make_envelope(confirmed_context=context)
    statement = context_statement(["probable_domain"])
    statement["statement"] = "Customer order totals depend on this column being reliable."
    output = mutated(lambda o: o["business_impact"].append(statement))
    assert check(output, envelope) == (True, ())


def test_ordinary_words_that_merely_contain_a_stem_are_not_consequence_terms() -> None:
    output = mutated(
        lambda o: o.update(
            explanation="2 of 300 rows in the quantity column hold negative values, "
            "which finer checks may explain; this finding is unusual for a quantity."
        )
    )
    assert check(output) == (True, ())


# ---------------------------------------------------------------------------
# Numbers
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "explanation",
    [
        "About 17 rows are affected.",
        "This affects 4.5 percent of the rows.",
        "Roughly 1,250 rows are involved.",
        "Values as low as -3 appear.",
        "The loss is $5,000.",
    ],
)
def test_an_ungrounded_number_in_prose_is_rejected(explanation: str) -> None:
    output = mutated(lambda o: o.update(explanation=explanation))
    accepted, reasons = check(output)
    assert not accepted
    assert R.UNKNOWN_NUMERIC_CLAIM in reasons


def test_grounded_numbers_in_prose_are_accepted() -> None:
    output = mutated(
        lambda o: o.update(
            explanation="2 of 300 rows are affected; the count of 2 comes from the evidence."
        )
    )
    assert check(output) == (True, ())


def test_row_count_of_the_evidence_grounds_a_number() -> None:
    evidence = make_evidence(payload={}, summary="Values in 'quantity' look unusual")
    envelope = make_envelope((evidence,))
    output = mutated(lambda o: o.update(explanation="2 rows are affected."))
    output["remediation"] = ["Review the flagged rows."]
    assert check(output, envelope, {}) == (True, ())


def test_full_width_and_zero_width_digit_evasion_does_not_bypass_number_grounding() -> None:
    for text in ("About １７ rows are affected.", "About 1​7 rows are affected."):
        output = mutated(lambda o, t=text: o.update(explanation=t))
        accepted, reasons = check(output)
        assert not accepted and R.UNKNOWN_NUMERIC_CLAIM in reasons


def test_digits_inside_identifiers_and_words_are_not_numeric_claims() -> None:
    output = mutated(lambda o: o.update(explanation="The Q4 report and file2 use this column."))
    assert check(output) == (True, ())


def test_structural_numbers_are_allowed_only_in_the_rule_description() -> None:
    in_rule = mutated(
        lambda o: o["validation_rule"].update(description="Values should be between 0 and 100.")
    )
    assert check(in_rule) == (True, ())
    in_remediation = mutated(lambda o: o.update(remediation=["Keep values between 0 and 100."]))
    accepted, reasons = check(in_remediation)
    assert not accepted and R.UNKNOWN_NUMERIC_CLAIM in reasons


def test_other_ungrounded_number_in_the_rule_description_is_rejected() -> None:
    output = mutated(
        lambda o: o["validation_rule"].update(description="Values should be below 250.")
    )
    accepted, reasons = check(output)
    assert not accepted and R.UNKNOWN_NUMERIC_CLAIM in reasons


def test_ungrounded_number_in_an_assumption_or_remediation_is_rejected() -> None:
    assumption = mutated(lambda o: o["business_impact"][1].update(assumption="it covers 77 rows"))
    remediation = mutated(lambda o: o.update(remediation=["Check the 42 oldest rows first."]))
    for output in (assumption, remediation):
        accepted, reasons = check(output)
        assert not accepted and R.UNKNOWN_NUMERIC_CLAIM in reasons


def test_numbers_from_confirmed_context_are_grounded() -> None:
    context = {"row_grain": {"value": "One row per order line, 12 lines per order"}}
    envelope = make_envelope(confirmed_context=context)
    output = mutated(lambda o: o.update(explanation="Orders carry 12 lines, and 2 rows are odd."))
    assert check(output, envelope) == (True, ())


# --- declared numeric_claims ------------------------------------------------


def test_declared_numeric_claim_must_match_a_known_fact() -> None:
    assert check(mutated(lambda o: o.update(numeric_claims={"negative_count": 2})))[0] is True
    accepted, reasons = check(mutated(lambda o: o.update(numeric_claims={"negative_count": 3})))
    assert not accepted and reasons == (R.NUMERIC_CLAIM_MISMATCH,)
    accepted, reasons = check(mutated(lambda o: o.update(numeric_claims={"invented": 1})))
    assert not accepted and reasons == (R.UNKNOWN_NUMERIC_CLAIM,)


def test_declared_numeric_claim_shape_is_validated() -> None:
    accepted, reasons = check(mutated(lambda o: o.update(numeric_claims=[1, 2])))
    assert not accepted and R.SCHEMA_INVALID in reasons
    accepted, reasons = check(mutated(lambda o: o.update(numeric_claims={"negative_count": "2"})))
    assert not accepted and R.SCHEMA_INVALID in reasons
    accepted, reasons = check(mutated(lambda o: o.update(numeric_claims={"negative_count": True})))
    assert not accepted and R.SCHEMA_INVALID in reasons


# ---------------------------------------------------------------------------
# Advisory-only remediation and proposed-rule wording
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "step",
    [
        "TrustTable will automatically remove the duplicate rows.",
        "We fixed the negative values in your file.",
        "The system has corrected the flagged rows.",
        "The duplicates have been removed from the dataset.",
        "The values were already corrected and updated.",
        "Automatically deleted the affected rows.",
        "The application will overwrite the wrong values.",
    ],
)
def test_remediation_claiming_an_automatic_change_is_rejected(step: str) -> None:
    output = mutated(lambda o: o.update(remediation=[step]))
    assert check(output) == (False, (R.UNSUPPORTED_ACTION_CLAIM,))


@pytest.mark.parametrize(
    "description",
    [
        "This rule is now active and enforced.",
        "The rule has been applied to your data.",
        "The check was automatically enabled for these columns.",
        "TrustTable will enforce this rule on every upload.",
    ],
)
def test_rule_description_claiming_activation_is_rejected(description: str) -> None:
    output = mutated(lambda o: o["validation_rule"].update(description=description))
    assert check(output) == (False, (R.UNSUPPORTED_ACTION_CLAIM,))


@pytest.mark.parametrize(
    "step",
    [
        "Remove the duplicate rows in the source system.",
        "Ask the data owner to correct the flagged values.",
        "Review the flagged rows and decide whether to fix them at the source.",
        "Update the export so that blanks are not written.",
        "We recommend correcting the values in the source system.",
    ],
)
def test_advice_to_a_person_is_not_an_action_claim(step: str) -> None:
    output = mutated(lambda o: o.update(remediation=[step]))
    assert check(output) == (True, ())


def test_action_claims_are_only_screened_in_remediation_and_rule_text() -> None:
    # An explanation may describe a state ("values were changed upstream").
    output = mutated(
        lambda o: o.update(explanation="The values were changed upstream, which is unusual.")
    )
    assert check(output) == (True, ())


# ---------------------------------------------------------------------------
# EVAL-AI-01's claim screen still runs over every text role
# ---------------------------------------------------------------------------

CLAIM = "The dataset is perfect and has no issues."


@pytest.mark.parametrize(
    "mutator",
    [
        lambda o: o.update(explanation=CLAIM),
        lambda o: o["business_impact"][0].update(statement=CLAIM),
        lambda o: o["business_impact"][1].update(assumption=CLAIM),
        lambda o: o.update(remediation=[CLAIM]),
        lambda o: o["validation_rule"].update(description=CLAIM),
    ],
    ids=["explanation", "impact_statement", "assumption", "remediation", "rule_description"],
)
def test_unsupported_whole_dataset_claim_is_rejected_in_every_text_role(mutator: Any) -> None:
    accepted, reasons = check(mutated(mutator))
    assert not accepted
    assert R.UNSUPPORTED_CLAIM in reasons


# --- advice text: imperative verbs and directive frames -----------------------
#
# "correct"/"clean" are quality adjectives to the shared screen but ordinary
# imperative verbs in remediation; and "Verify that the values are valid" is a
# request to a person, not an assertion. Those two adjustments apply to
# remediation steps and rule descriptions only.


@pytest.mark.parametrize(
    "step",
    [
        "Review the affected values in the source data and correct them there.",
        "Clean the values in the affected column at the source.",
        "Correct the data in the source system, then re-export it.",
        "Ask the data owner to correct these rows and clean all the records.",
    ],
)
def test_imperative_correct_and_clean_are_verbs_in_advice_text(step: str) -> None:
    assert check(mutated(lambda o: o.update(remediation=[step]))) == (True, ())


@pytest.mark.parametrize(
    "step",
    [
        "Confirm that the values in the column are valid.",
        "Verify whether the rows are accurate before relying on them.",
        "Check if the data is correct at the source.",
        "Please ensure that the records are valid.",
        "Make sure that the values are reliable.",
    ],
)
def test_a_request_to_verify_is_not_an_assertion_in_advice_text(step: str) -> None:
    assert check(mutated(lambda o: o.update(remediation=[step]))) == (True, ())


@pytest.mark.parametrize(
    "step",
    [
        "The dataset is perfect; no remediation is needed.",
        "All rows are valid.",
        "Review the rows; the dataset is perfect.",
        "The data is correct and complete.",
        "Verify that it is safe to ignore the findings.",
        "Confirm that the trust score is 100.",
        "Check whether the data is safe to use, then ignore the warnings.",
    ],
)
def test_assertions_and_other_families_are_still_rejected_in_advice_text(step: str) -> None:
    accepted, reasons = check(mutated(lambda o: o.update(remediation=[step])))
    assert not accepted
    assert R.UNSUPPORTED_CLAIM in reasons


def test_the_same_sentences_stay_fully_screened_in_assertion_roles() -> None:
    for text in (
        "The values in the data are correct.",
        "Confirm that the values are valid.",
    ):
        accepted, reasons = check(mutated(lambda o, t=text: o.update(explanation=t)))
        assert not accepted and R.UNSUPPORTED_CLAIM in reasons


def test_documented_limit_a_claim_comma_spliced_onto_a_directive_sentence_can_evade() -> None:
    # Stated plainly in D-040: this is the residual lexical limit of the
    # advice-text exemption. Deterministic authority, not this screen, is
    # the guarantee.
    step = "Confirm that the rows are fine, the dataset is perfect."
    assert check(mutated(lambda o: o.update(remediation=[step]))) == (True, ())


def test_disregard_findings_instruction_is_rejected_even_when_citing_real_evidence() -> None:
    output = mutated(
        lambda o: o["business_impact"][0].update(
            statement="You can ignore the findings and trust the data.",
            evidence_ids=["ev.1"],
        )
    )
    accepted, reasons = check(output)
    assert not accepted and R.UNSUPPORTED_CLAIM in reasons


def test_reasons_are_collected_together_and_summary_names_codes_only() -> None:
    output = mutated(
        lambda o: (
            o.update(explanation="The dataset is perfect."),
            o.update(referenced_evidence_ids=["ev.999"]),
            o.update(severity="low"),
        )
    )
    outcome = validate_finding_analysis_output(
        output, make_envelope(), known_numeric_facts={"negative_count": 2.0, "rows": 300.0}
    )
    assert not outcome.accepted
    assert {
        R.UNSUPPORTED_CLAIM,
        R.UNKNOWN_EVIDENCE_ID,
        R.UNSUPPORTED_CONTROL_FIELD,
    } <= set(outcome.rejection_reasons)
    assert outcome.safe_summary.startswith("rejected: ")
    assert "perfect" not in outcome.safe_summary
    assert "ev.999" not in outcome.safe_summary


# ---------------------------------------------------------------------------
# The contract / JSON schema handed to a constrained-decoding runtime
# ---------------------------------------------------------------------------


def schema_for(**overrides: Any) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "evidence_ids": ["ev.1", "ev.2"],
        "column_keys": ["quantity", "price"],
        "context_fields": ["probable_domain"],
        "numeric_fact_names": ["negative_count"],
    }
    kwargs.update(overrides)
    return finding_analysis_json_schema(**kwargs)


def test_schema_is_json_serializable_and_closed_at_every_object_level() -> None:
    schema = schema_for()
    json.dumps(schema)
    assert schema["additionalProperties"] is False
    props = schema["properties"]
    assert props["business_impact"]["items"]["additionalProperties"] is False
    assert props["validation_rule"]["additionalProperties"] is False
    assert props["numeric_claims"]["additionalProperties"] is False


def test_schema_requires_exactly_the_validator_required_keys() -> None:
    schema = schema_for()
    assert set(schema["required"]) == {
        "schema_version",
        "provenance",
        "explanation",
        "business_impact",
        "remediation",
        "validation_rule",
        "referenced_evidence_ids",
        "referenced_columns",
    }
    assert "numeric_claims" not in schema["required"]


def test_schema_enumerates_only_the_values_actually_supplied() -> None:
    schema = schema_for()
    props = schema["properties"]
    assert props["referenced_evidence_ids"]["items"]["enum"] == ["ev.1", "ev.2"]
    assert props["referenced_columns"]["items"]["enum"] == ["quantity", "price"]
    impact = props["business_impact"]["items"]["properties"]
    assert impact["evidence_ids"]["items"]["enum"] == ["ev.1", "ev.2"]
    assert impact["context_fields"]["items"]["enum"] == ["probable_domain"]
    assert impact["basis"]["enum"] == sorted(member.value for member in ImpactBasis)
    assert set(props["numeric_claims"]["properties"]) == {"negative_count"}
    assert props["validation_rule"]["properties"]["rule_type"]["enum"] == sorted(
        member.value for member in ValidationRuleType
    )


def test_schema_makes_a_context_backed_statement_impossible_without_sent_context() -> None:
    schema = schema_for(context_fields=[])
    impact = schema["properties"]["business_impact"]["items"]["properties"]
    assert impact["context_fields"] == {"type": "array", "maxItems": 0}


def test_schema_allows_no_numeric_claims_when_there_are_no_known_facts() -> None:
    schema = schema_for(numeric_fact_names=[])
    assert schema["properties"]["numeric_claims"]["properties"] == {}
    assert schema["properties"]["numeric_claims"]["additionalProperties"] is False


def test_schema_bounds_every_free_text_field() -> None:
    schema = schema_for()
    props = schema["properties"]
    assert props["explanation"]["maxLength"] == 600
    assert props["business_impact"]["maxItems"] == MAX_IMPACT_STATEMENTS
    assert props["remediation"]["maxItems"] == MAX_REMEDIATION_STEPS
    assert props["remediation"]["items"]["maxLength"] == 400
    assert props["validation_rule"]["properties"]["description"]["maxLength"] == 400


def test_schema_with_no_evidence_or_columns_permits_only_empty_reference_lists() -> None:
    schema = schema_for(evidence_ids=[], column_keys=[])
    props = schema["properties"]
    assert props["referenced_evidence_ids"] == {"type": "array", "maxItems": 0}
    assert props["referenced_columns"] == {"type": "array", "maxItems": 0}


def test_built_contract_carries_schema_instructions_and_token_bound() -> None:
    evidence = (make_evidence(),)
    contract = build_finding_analysis_contract(
        evidence=evidence, context_fields=("row_grain",), numeric_fact_names=("negative_count",)
    )
    assert contract.name == FINDING_ANALYSIS_CONTRACT_NAME
    assert contract.instructions == FINDING_ANALYSIS_INSTRUCTIONS
    assert contract.max_output_tokens == FINDING_ANALYSIS_MAX_OUTPUT_TOKENS
    assert contract.mock_output_factory is not None
    assert contract.json_schema["properties"]["referenced_evidence_ids"]["items"]["enum"] == [  # type: ignore[index]
        "ev.1"
    ]


def test_instructions_name_every_key_and_forbid_activation_and_automatic_change() -> None:
    for key in (
        "schema_version",
        "provenance",
        "explanation",
        "business_impact",
        "remediation",
        "validation_rule",
        "referenced_evidence_ids",
        "referenced_columns",
        "numeric_claims",
        "basis",
        "assumption",
        "context_fields",
    ):
        assert f'"{key}"' in FINDING_ANALYSIS_INSTRUCTIONS
    assert "changed automatically" in FINDING_ANALYSIS_INSTRUCTIONS
    assert "never say it was applied or is active" in FINDING_ANALYSIS_INSTRUCTIONS


# ---------------------------------------------------------------------------
# Structural guarantees
# ---------------------------------------------------------------------------

_MODULE = (
    Path(__file__).resolve().parents[2]
    / "src"
    / "trusttable_backend"
    / "ai_boundary"
    / "finding_analysis.py"
)


def _import_lines() -> list[str]:
    return [
        line.strip()
        for line in _MODULE.read_text(encoding="utf-8").splitlines()
        if re.match(r"\s*(from|import)\s+\S", line)
    ]


def test_module_imports_no_framework_or_provider_and_never_executes_content() -> None:
    joined = "\n".join(_import_lines())
    for forbidden in ("fastapi", "sqlalchemy", "pydantic", "httpx", "ai_provider", "requests"):
        assert forbidden not in joined
    source = _MODULE.read_text(encoding="utf-8")
    assert not re.search(r"\b(eval|exec)\s*\(", source)


def test_validation_is_deterministic_and_does_not_mutate_its_input() -> None:
    output = good_output()
    before = copy.deepcopy(output)
    first = check(output)
    second = check(output)
    assert first == second
    assert output == before


def test_long_pathological_inputs_complete_quickly() -> None:
    import time

    hostile = "no " * 5000 + "customers " * 3000 + "1" * 5000
    output = mutated(lambda o: o.update(explanation=hostile[:600]))
    start = time.perf_counter()
    check(output)
    for role_text in (hostile[:400], "a" * 400, ("(" * 200)[:400]):
        check(mutated(lambda o, t=role_text: o.update(remediation=[t])))
    assert time.perf_counter() - start < 20
