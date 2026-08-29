"""Tests for model-output validation (SEC-02).

Covers this package's acceptance criteria AC-13..AC-23: schema
validity, provenance, evidence/column allow-lists, numeric-claim exact
equality, severity validity, unsupported control fields, a combined
hostile fixture, a fully well-formed acceptance case, and safe-summary
non-leakage.
"""

from __future__ import annotations

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
