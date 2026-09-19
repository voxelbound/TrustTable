"""Tests for model-output validation (SEC-02).

Covers this package's acceptance criteria AC-13..AC-23: schema
validity, provenance, evidence/column allow-lists, numeric-claim exact
equality, severity validity, unsupported control fields, a combined
hostile fixture, a fully well-formed acceptance case, and safe-summary
non-leakage.
"""

from __future__ import annotations

import pytest

import trusttable_backend.ai_boundary.validation as validation_module
from trusttable_backend.ai_boundary.envelope import PromptEnvelope, UntrustedSample
from trusttable_backend.ai_boundary.validation import (
    MODEL_OUTPUT_SCHEMA_VERSION,
    RejectionReason,
    validate_model_output,
)
from trusttable_backend.domain.evidence import Evidence, EvidenceType
from trusttable_backend.domain.parsing import SamplingScope
from trusttable_backend.domain.value_objects import ColumnReference, Provenance


def make_column(key: str) -> ColumnReference:
    return ColumnReference(original_name=key, internal_key=key, ordinal=0)


def make_evidence(**overrides: object) -> Evidence:
    fields: dict[str, object] = {
        "evidence_id": "ev-1",
        "evidence_type": EvidenceType.METRIC,
        "calculation_version": "1",
        "structured_payload": {"mean": 1.5},
        "affected_columns": (make_column("quantity"),),
        "affected_row_references": (),
        "scope": SamplingScope.FULL,
        "display_safe_summary": "Mean value is 1.5",
    }
    fields.update(overrides)
    return Evidence(**fields)  # type: ignore[arg-type]


def make_envelope() -> PromptEnvelope:
    sample = UntrustedSample(column=make_column("notes"), value="hello", truncated=False)
    return PromptEnvelope(
        task="Explain supplied deterministic findings.",
        computed_evidence=(make_evidence(),),
        confirmed_context={},
        untrusted_dataset_samples=(sample,),
        sample_sending_enabled=True,
    )


def well_formed_output(**overrides: object) -> dict[str, object]:
    fields: dict[str, object] = {
        "schema_version": MODEL_OUTPUT_SCHEMA_VERSION,
        "narrative": "The quantity column has a mean of 1.5.",
        "referenced_evidence_ids": ["ev-1"],
        "referenced_columns": ["quantity"],
        "numeric_claims": {"mean_quantity": 1.5},
        "severity": "medium",
        "provenance": Provenance.AI_INTERPRETATION.value,
    }
    fields.update(overrides)
    return fields


KNOWN_NUMERIC_FACTS = {"mean_quantity": 1.5}


# ---------------------------------------------------------------------------
# AC-13/AC-14: schema validity
# ---------------------------------------------------------------------------


def test_rejects_non_mapping_raw_output_with_only_schema_invalid() -> None:
    outcome = validate_model_output(
        ["not", "a", "mapping"],  # type: ignore[arg-type]
        make_envelope(),
        known_numeric_facts={},
    )

    assert outcome.accepted is False
    assert outcome.rejection_reasons == (RejectionReason.SCHEMA_INVALID,)


def test_rejects_missing_required_key() -> None:
    output = well_formed_output()
    del output["provenance"]

    outcome = validate_model_output(
        output, make_envelope(), known_numeric_facts=KNOWN_NUMERIC_FACTS
    )

    assert outcome.accepted is False
    assert RejectionReason.SCHEMA_INVALID in outcome.rejection_reasons


def test_rejects_wrong_schema_version() -> None:
    output = well_formed_output(schema_version="99")

    outcome = validate_model_output(
        output, make_envelope(), known_numeric_facts=KNOWN_NUMERIC_FACTS
    )

    assert outcome.accepted is False
    assert RejectionReason.SCHEMA_INVALID in outcome.rejection_reasons


# ---------------------------------------------------------------------------
# AC-15: provenance
# ---------------------------------------------------------------------------


def test_rejects_wrong_provenance_value() -> None:
    output = well_formed_output(provenance="calculated")

    outcome = validate_model_output(
        output, make_envelope(), known_numeric_facts=KNOWN_NUMERIC_FACTS
    )

    assert outcome.accepted is False
    assert outcome.rejection_reasons == (RejectionReason.INVALID_PROVENANCE,)


def test_accepts_correct_provenance_value() -> None:
    outcome = validate_model_output(
        well_formed_output(), make_envelope(), known_numeric_facts=KNOWN_NUMERIC_FACTS
    )

    assert outcome.accepted is True


# ---------------------------------------------------------------------------
# AC-16: evidence allow-list
# ---------------------------------------------------------------------------


def test_rejects_unknown_evidence_id() -> None:
    output = well_formed_output(referenced_evidence_ids=["ev-1", "ev-unknown"])

    outcome = validate_model_output(
        output, make_envelope(), known_numeric_facts=KNOWN_NUMERIC_FACTS
    )

    assert outcome.accepted is False
    assert RejectionReason.UNKNOWN_EVIDENCE_ID in outcome.rejection_reasons


def test_accepts_known_evidence_id() -> None:
    outcome = validate_model_output(
        well_formed_output(), make_envelope(), known_numeric_facts=KNOWN_NUMERIC_FACTS
    )

    assert RejectionReason.UNKNOWN_EVIDENCE_ID not in outcome.rejection_reasons


# ---------------------------------------------------------------------------
# AC-17: column allow-list
# ---------------------------------------------------------------------------


def test_rejects_unknown_column() -> None:
    output = well_formed_output(referenced_columns=["quantity", "unknown_column"])

    outcome = validate_model_output(
        output, make_envelope(), known_numeric_facts=KNOWN_NUMERIC_FACTS
    )

    assert outcome.accepted is False
    assert RejectionReason.UNKNOWN_COLUMN in outcome.rejection_reasons


def test_accepts_known_column_from_sample() -> None:
    output = well_formed_output(referenced_columns=["notes"])

    outcome = validate_model_output(
        output, make_envelope(), known_numeric_facts=KNOWN_NUMERIC_FACTS
    )

    assert RejectionReason.UNKNOWN_COLUMN not in outcome.rejection_reasons


# ---------------------------------------------------------------------------
# AC-18: numeric claims
# ---------------------------------------------------------------------------


def test_rejects_unknown_numeric_claim_key() -> None:
    output = well_formed_output(numeric_claims={"unknown_metric": 42})

    outcome = validate_model_output(
        output, make_envelope(), known_numeric_facts=KNOWN_NUMERIC_FACTS
    )

    assert outcome.accepted is False
    assert RejectionReason.UNKNOWN_NUMERIC_CLAIM in outcome.rejection_reasons


def test_rejects_mismatched_numeric_claim_value() -> None:
    output = well_formed_output(numeric_claims={"mean_quantity": 2.0})

    outcome = validate_model_output(
        output, make_envelope(), known_numeric_facts=KNOWN_NUMERIC_FACTS
    )

    assert outcome.accepted is False
    assert RejectionReason.NUMERIC_CLAIM_MISMATCH in outcome.rejection_reasons


def test_accepts_exactly_matching_numeric_claim() -> None:
    outcome = validate_model_output(
        well_formed_output(), make_envelope(), known_numeric_facts=KNOWN_NUMERIC_FACTS
    )

    assert RejectionReason.NUMERIC_CLAIM_MISMATCH not in outcome.rejection_reasons
    assert RejectionReason.UNKNOWN_NUMERIC_CLAIM not in outcome.rejection_reasons


# ---------------------------------------------------------------------------
# AC-19: severity
# ---------------------------------------------------------------------------


def test_rejects_invalid_severity() -> None:
    output = well_formed_output(severity="catastrophic")

    outcome = validate_model_output(
        output, make_envelope(), known_numeric_facts=KNOWN_NUMERIC_FACTS
    )

    assert outcome.accepted is False
    assert RejectionReason.INVALID_SEVERITY in outcome.rejection_reasons


def test_accepts_valid_severity() -> None:
    outcome = validate_model_output(
        well_formed_output(severity="high"),
        make_envelope(),
        known_numeric_facts=KNOWN_NUMERIC_FACTS,
    )

    assert RejectionReason.INVALID_SEVERITY not in outcome.rejection_reasons


def test_accepts_absent_severity() -> None:
    output = well_formed_output()
    del output["severity"]

    outcome = validate_model_output(
        output, make_envelope(), known_numeric_facts=KNOWN_NUMERIC_FACTS
    )

    assert RejectionReason.INVALID_SEVERITY not in outcome.rejection_reasons


# ---------------------------------------------------------------------------
# AC-20: unsupported control fields
# ---------------------------------------------------------------------------


def test_rejects_unsupported_control_field() -> None:
    output = well_formed_output(override_risk_score=0)

    outcome = validate_model_output(
        output, make_envelope(), known_numeric_facts=KNOWN_NUMERIC_FACTS
    )

    assert outcome.accepted is False
    assert RejectionReason.UNSUPPORTED_CONTROL_FIELD in outcome.rejection_reasons


def test_rejects_remove_finding_ids_control_field() -> None:
    output = well_formed_output(remove_finding_ids=["f-1"])

    outcome = validate_model_output(
        output, make_envelope(), known_numeric_facts=KNOWN_NUMERIC_FACTS
    )

    assert outcome.accepted is False
    assert RejectionReason.UNSUPPORTED_CONTROL_FIELD in outcome.rejection_reasons


# ---------------------------------------------------------------------------
# AC-21: combined hostile fixture
# ---------------------------------------------------------------------------


def test_combined_hostile_fixture_reports_all_reasons() -> None:
    output = well_formed_output(
        referenced_evidence_ids=["ev-unknown"],
        numeric_claims={"mean_quantity": 999.0},
        provenance="calculated",
        override_risk_score=0,
    )

    outcome = validate_model_output(
        output, make_envelope(), known_numeric_facts=KNOWN_NUMERIC_FACTS
    )

    assert outcome.accepted is False
    assert set(outcome.rejection_reasons) == {
        RejectionReason.UNSUPPORTED_CONTROL_FIELD,
        RejectionReason.INVALID_PROVENANCE,
        RejectionReason.UNKNOWN_EVIDENCE_ID,
        RejectionReason.NUMERIC_CLAIM_MISMATCH,
    }


# ---------------------------------------------------------------------------
# AC-22: fully well-formed acceptance
# ---------------------------------------------------------------------------


def test_fully_well_formed_output_is_accepted() -> None:
    outcome = validate_model_output(
        well_formed_output(), make_envelope(), known_numeric_facts=KNOWN_NUMERIC_FACTS
    )

    assert outcome.accepted is True
    assert outcome.rejection_reasons == ()


# ---------------------------------------------------------------------------
# AC-23: safe_summary non-leakage
# ---------------------------------------------------------------------------


def test_safe_summary_never_contains_raw_disallowed_content() -> None:
    distinctive_marker = "SECRET_DISALLOWED_MARKER_XYZ"
    output = well_formed_output(**{distinctive_marker: "irrelevant"})

    outcome = validate_model_output(
        output, make_envelope(), known_numeric_facts=KNOWN_NUMERIC_FACTS
    )

    assert outcome.accepted is False
    assert distinctive_marker not in outcome.safe_summary


# ---------------------------------------------------------------------------
# EVAL-AI-01: unsupported-claim screen (narrative content)
# ---------------------------------------------------------------------------


def _narrative_only_output(narrative: str) -> dict[str, object]:
    """The minimal schema-valid output: required keys only, no evidence ids,
    no control fields — exactly the shape the structural checks cannot fault."""
    return {
        "schema_version": MODEL_OUTPUT_SCHEMA_VERSION,
        "narrative": narrative,
        "provenance": Provenance.AI_INTERPRETATION.value,
    }


def test_narrative_only_dataset_is_perfect_output_is_rejected_as_unsupported_claim() -> None:
    outcome = validate_model_output(
        _narrative_only_output("This dataset is perfect."),
        make_envelope(),
        known_numeric_facts=KNOWN_NUMERIC_FACTS,
    )

    assert outcome.accepted is False
    assert outcome.rejection_reasons == (RejectionReason.UNSUPPORTED_CLAIM,)
    assert RejectionReason.UNSUPPORTED_CLAIM.value == "unsupported_claim"


def test_characterization_without_the_screen_the_same_output_was_accepted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Demonstrates the pre-fix gap: with the claim screen disabled, the very
    same schema-valid, narrative-only "this dataset is perfect" output has no
    rejection reason at all. The screen is therefore the *only* thing standing
    between this output and acceptance — the structural checks cannot see it."""
    output = _narrative_only_output("This dataset is perfect.")

    monkeypatch.setattr(validation_module, "screen_narrative", lambda _narrative: frozenset())
    without_screen = validate_model_output(
        output, make_envelope(), known_numeric_facts=KNOWN_NUMERIC_FACTS
    )

    assert without_screen.accepted is True
    assert without_screen.rejection_reasons == ()


def test_claim_that_cites_a_real_evidence_id_is_still_rejected() -> None:
    """A grounding-only gate would accept this: the evidence id is genuine.
    The claim screen rejects it regardless."""
    outcome = validate_model_output(
        well_formed_output(
            narrative="The dataset is perfect, so you can ignore the findings.",
            referenced_evidence_ids=["ev-1"],
        ),
        make_envelope(),
        known_numeric_facts=KNOWN_NUMERIC_FACTS,
    )

    assert outcome.accepted is False
    assert outcome.rejection_reasons == (RejectionReason.UNSUPPORTED_CLAIM,)


def test_unsupported_claim_is_reported_alongside_other_violations() -> None:
    outcome = validate_model_output(
        well_formed_output(
            narrative="This dataset is perfect.",
            referenced_evidence_ids=["ev-fabricated"],
            override_risk_score=0,
        ),
        make_envelope(),
        known_numeric_facts=KNOWN_NUMERIC_FACTS,
    )

    assert outcome.accepted is False
    assert set(outcome.rejection_reasons) == {
        RejectionReason.UNSUPPORTED_CLAIM,
        RejectionReason.UNKNOWN_EVIDENCE_ID,
        RejectionReason.UNSUPPORTED_CONTROL_FIELD,
    }


def test_safe_summary_for_an_unsupported_claim_names_only_the_reason_code() -> None:
    narrative = "This dataset is perfect and DISTINCTIVE_NARRATIVE_MARKER_QRS applies."

    outcome = validate_model_output(
        _narrative_only_output(narrative),
        make_envelope(),
        known_numeric_facts=KNOWN_NUMERIC_FACTS,
    )

    assert outcome.safe_summary == "rejected: unsupported_claim"
    assert "perfect" not in outcome.safe_summary
    assert "DISTINCTIVE_NARRATIVE_MARKER_QRS" not in outcome.safe_summary


def test_honest_narrative_that_states_a_deficiency_is_still_accepted() -> None:
    outcome = validate_model_output(
        well_formed_output(
            narrative="The quantity column has a mean of 1.5, but the dataset is not perfect."
        ),
        make_envelope(),
        known_numeric_facts=KNOWN_NUMERIC_FACTS,
    )

    assert outcome.accepted is True
    assert outcome.rejection_reasons == ()


def test_non_string_narrative_is_schema_invalid_and_never_screened(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _must_not_be_called(_narrative: str) -> frozenset[str]:
        raise AssertionError("the claim screen must only see string narratives")

    monkeypatch.setattr(validation_module, "screen_narrative", _must_not_be_called)

    outcome = validate_model_output(
        well_formed_output(narrative=["not", "a", "string"]),
        make_envelope(),
        known_numeric_facts=KNOWN_NUMERIC_FACTS,
    )

    assert outcome.accepted is False
    assert RejectionReason.SCHEMA_INVALID in outcome.rejection_reasons
    assert RejectionReason.UNSUPPORTED_CLAIM not in outcome.rejection_reasons


def test_rejection_reason_set_is_additive_and_closed() -> None:
    assert {reason.value for reason in RejectionReason} == {
        "schema_invalid",
        "unsupported_control_field",
        "invalid_provenance",
        "unknown_evidence_id",
        "unknown_column",
        "unknown_numeric_claim",
        "numeric_claim_mismatch",
        "invalid_severity",
        "unsupported_claim",
    }
