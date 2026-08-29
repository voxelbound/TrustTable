"""Model-output validation and the rejected-output audit result (`SEC-02`).

Validates a raw, already-parsed model output (`Mapping[str, object]`,
e.g. from `json.loads` or a mock provider) against exactly the
`PromptEnvelope` that was sent plus caller-supplied `known_numeric_facts`,
implementing every bullet in `docs/architecture.md` §7's output-
validation list: schema, evidence IDs, column names, numeric claims,
allowed severity and provenance, absence of unsupported control fields.

Deterministic authority (`docs/product-requirements.md` §5.3) is
enforced structurally: the validated schema has no field capable of
removing a finding or changing a score, so a hostile output cannot
express that intent at all — any attempt to add such a field is rejected
as an unsupported control field.

`validate_model_output` never raises on malformed `raw_output`; any
structural problem produces a rejected `ValidationOutcome` instead
(`docs/testing-strategy.md` §2.6's "safe fallback after malformed
output" — this is what makes a safe fallback possible in a future
provider package).

Framework-independent: no FastAPI/SQLAlchemy/pydantic import. Stdlib
only.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from ..domain.value_objects import Provenance, Severity
from .envelope import PromptEnvelope

#: Bumped whenever the validated output schema's field set/semantics
#: change in a way a future consumer needs to distinguish.
MODEL_OUTPUT_SCHEMA_VERSION = "1"

_REQUIRED_TOP_LEVEL_KEYS = frozenset({"schema_version", "narrative", "provenance"})
_ALLOWED_TOP_LEVEL_KEYS = frozenset(
    {
        "schema_version",
        "narrative",
        "referenced_evidence_ids",
        "referenced_columns",
        "numeric_claims",
        "severity",
        "provenance",
    }
)
_VALID_SEVERITY_VALUES = frozenset(member.value for member in Severity)


class RejectionReason(StrEnum):
    """Closed set of reasons a model output may be rejected for."""

    SCHEMA_INVALID = "schema_invalid"
    UNSUPPORTED_CONTROL_FIELD = "unsupported_control_field"
    INVALID_PROVENANCE = "invalid_provenance"
    UNKNOWN_EVIDENCE_ID = "unknown_evidence_id"
    UNKNOWN_COLUMN = "unknown_column"
    UNKNOWN_NUMERIC_CLAIM = "unknown_numeric_claim"
    NUMERIC_CLAIM_MISMATCH = "numeric_claim_mismatch"
    INVALID_SEVERITY = "invalid_severity"


@dataclass(frozen=True, slots=True)
class ValidationOutcome:
    """The rejected-output audit result.

    `safe_summary` never contains any raw value from `raw_output` — only
    reason codes — matching `docs/testing-strategy.md` §3's "logs do not
    expose the full value".
    """

    accepted: bool
    rejection_reasons: tuple[RejectionReason, ...]
    safe_summary: str


def _dedupe(reasons: list[RejectionReason]) -> tuple[RejectionReason, ...]:
    return tuple(dict.fromkeys(reasons))


def _safe_summary(accepted: bool, reasons: tuple[RejectionReason, ...]) -> str:
    if accepted:
        return "accepted"
    return "rejected: " + ", ".join(reason.value for reason in reasons)


def validate_model_output(
    raw_output: Mapping[str, object],
    envelope: PromptEnvelope,
    *,
    known_numeric_facts: Mapping[str, float],
) -> ValidationOutcome:
    """Validate `raw_output` against `envelope` and `known_numeric_facts`.

    Grounded entirely in what was actually sent (`envelope`), not a
    separately-passed allow-list, so a caller cannot accidentally pass
    mismatched allow-lists. Collects every distinct violation found
    rather than failing fast on the first.
    """
    if not isinstance(raw_output, Mapping):
        return ValidationOutcome(
            accepted=False,
            rejection_reasons=(RejectionReason.SCHEMA_INVALID,),
            safe_summary=_safe_summary(False, (RejectionReason.SCHEMA_INVALID,)),
        )

    reasons: list[RejectionReason] = []
    present_keys = set(raw_output.keys())

    if present_keys - _ALLOWED_TOP_LEVEL_KEYS:
        reasons.append(RejectionReason.UNSUPPORTED_CONTROL_FIELD)

    schema_invalid = bool(_REQUIRED_TOP_LEVEL_KEYS - present_keys)

    schema_version = raw_output.get("schema_version")
    if "schema_version" in raw_output and schema_version != MODEL_OUTPUT_SCHEMA_VERSION:
        schema_invalid = True

    narrative = raw_output.get("narrative")
    if "narrative" in raw_output and not isinstance(narrative, str):
        schema_invalid = True

    provenance_value = raw_output.get("provenance")
    if "provenance" in raw_output and not isinstance(provenance_value, str):
        schema_invalid = True
    elif (
        isinstance(provenance_value, str) and provenance_value != Provenance.AI_INTERPRETATION.value
    ):
        reasons.append(RejectionReason.INVALID_PROVENANCE)

    known_evidence_ids = {evidence.evidence_id for evidence in envelope.computed_evidence}
    referenced_evidence_ids = raw_output.get("referenced_evidence_ids")
    if referenced_evidence_ids is not None:
        if isinstance(referenced_evidence_ids, list | tuple):
            if any(eid not in known_evidence_ids for eid in referenced_evidence_ids):
                reasons.append(RejectionReason.UNKNOWN_EVIDENCE_ID)
        else:
            schema_invalid = True

    known_columns: set[str] = set()
    for evidence in envelope.computed_evidence:
        known_columns.update(column.internal_key for column in evidence.affected_columns)
    known_columns.update(
        sample.column.internal_key for sample in envelope.untrusted_dataset_samples
    )

    referenced_columns = raw_output.get("referenced_columns")
    if referenced_columns is not None:
        if isinstance(referenced_columns, list | tuple):
            if any(col not in known_columns for col in referenced_columns):
                reasons.append(RejectionReason.UNKNOWN_COLUMN)
        else:
            schema_invalid = True

    numeric_claims = raw_output.get("numeric_claims")
    if numeric_claims is not None:
        if isinstance(numeric_claims, Mapping):
            unknown_numeric = False
            mismatched_numeric = False
            for key, claimed_value in numeric_claims.items():
                if key not in known_numeric_facts:
                    unknown_numeric = True
                    continue
                if isinstance(claimed_value, bool) or not isinstance(claimed_value, int | float):
                    schema_invalid = True
                    continue
                if claimed_value != known_numeric_facts[key]:
                    mismatched_numeric = True
            if unknown_numeric:
                reasons.append(RejectionReason.UNKNOWN_NUMERIC_CLAIM)
            if mismatched_numeric:
                reasons.append(RejectionReason.NUMERIC_CLAIM_MISMATCH)
        else:
            schema_invalid = True

    severity_value = raw_output.get("severity")
    if severity_value is not None and (
        not isinstance(severity_value, str) or severity_value not in _VALID_SEVERITY_VALUES
    ):
        reasons.append(RejectionReason.INVALID_SEVERITY)

    if schema_invalid:
        reasons.insert(0, RejectionReason.SCHEMA_INVALID)

    deduped = _dedupe(reasons)
    accepted = not deduped
    return ValidationOutcome(
        accepted=accepted,
        rejection_reasons=deduped,
        safe_summary=_safe_summary(accepted, deduped),
    )


__all__ = [
    "MODEL_OUTPUT_SCHEMA_VERSION",
    "RejectionReason",
    "ValidationOutcome",
    "validate_model_output",
]
