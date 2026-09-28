"""The AI-assisted rule-generation structured output contract
(`RULE-02` slice 2, `WP-081`) — the seam that fills the one parameter
`rules/generation.py`'s slice 1 (`WP-080`) deliberately left unmapped
for `consistency.inconsistent_capitalization`: which of a finding's own
already-observed candidate values (`distinct_casings`) is canonical.

Unlike `finding_analysis` (`AI-08`), this contract carries **no prose at
all**. Its only field, `canonical_value`, is a closed JSON-Schema enum
built per request from exactly the finding's own evidence
(`rules.ai_generation.extract_ai_assist_candidates`, via
`rules.generation`). A provider cannot invent a value here — it can
only select one of the exact strings it was given, the model
equivalent of a multiple-choice answer, never free text. None of
`finding_analysis`'s claim-screen, numeric-grounding or
consequence-term machinery applies, for the same reason: there is no
narrative surface to screen, and no number to ground.

`RuleGenerationRejectionReason` is deliberately a separate, narrower
closed set from `ai_boundary.validation.RejectionReason`: this
contract has no narrative, evidence-id, column or context-field
surface those broader reasons describe.

Framework-independent: stdlib only, no I/O, no `eval`/`exec`.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Final

from ..domain.value_objects import Provenance
from .envelope import PromptEnvelope
from .output_contract import OutputContract

RULE_GENERATION_SCHEMA_VERSION: Final[str] = "rule_generation_v1"
RULE_GENERATION_CONTRACT_NAME: Final[str] = "rule_generation_v1"

#: Generous for a one-field, no-prose answer, yet small enough for a
#: CPU-bound baseline model — far below `finding_analysis`'s own
#: `FINDING_ANALYSIS_MAX_OUTPUT_TOKENS` (`1024`), since there is nothing
#: to write beyond one copied candidate string.
RULE_GENERATION_MAX_OUTPUT_TOKENS: Final[int] = 64

_MIN_CANDIDATES: Final[int] = 2

_REQUIRED_KEYS: Final[frozenset[str]] = frozenset(
    {"schema_version", "provenance", "canonical_value"}
)

RULE_GENERATION_INSTRUCTIONS_TEMPLATE: Final[str] = (
    "Respond with a single JSON object only: no other text, no markdown code "
    'fences. Use exactly these keys: "schema_version" (use "{schema_version}"), '
    '"provenance" (use "{provenance}"), and "canonical_value" (the one value, '
    "copied exactly character-for-character from the candidates list you were "
    "given, that should be treated as the correct spelling and capitalization "
    "every other row should match). Do not include any key not listed here. "
    "Do not invent a value that is not one of the exact candidates supplied."
)


class RuleGenerationRejectionReason(StrEnum):
    """Closed set of reasons a `rule_generation_v1` output may be
    rejected for."""

    SCHEMA_INVALID = "schema_invalid"
    UNSUPPORTED_CONTROL_FIELD = "unsupported_control_field"
    INVALID_PROVENANCE = "invalid_provenance"
    #: The provider's `canonical_value` is not one of the exact strings
    #: it was given — the one violation this contract exists to prevent.
    VALUE_NOT_CANDIDATE = "value_not_candidate"


@dataclass(frozen=True, slots=True)
class RuleGenerationOutcome:
    """The rejected-output audit result for one `rule_generation_v1`
    validation. `safe_summary` never contains the raw output — only
    reason codes."""

    accepted: bool
    canonical_value: str | None
    rejection_reasons: tuple[RuleGenerationRejectionReason, ...]
    safe_summary: str

    def __post_init__(self) -> None:
        if self.accepted and self.canonical_value is None:
            raise ValueError("RuleGenerationOutcome.canonical_value must be set when accepted")
        if not self.accepted and self.canonical_value is not None:
            raise ValueError("RuleGenerationOutcome.canonical_value must be None when not accepted")


def rule_generation_json_schema(candidates: Sequence[str]) -> dict[str, Any]:
    """The JSON Schema for `rule_generation_v1`, with `canonical_value`
    restricted to exactly the candidate values supplied for this
    request."""
    return {
        "type": "object",
        "additionalProperties": False,
        "required": sorted(_REQUIRED_KEYS),
        "properties": {
            "schema_version": {"type": "string", "enum": [RULE_GENERATION_SCHEMA_VERSION]},
            "provenance": {"type": "string", "enum": [Provenance.AI_INTERPRETATION.value]},
            "canonical_value": {"type": "string", "enum": list(candidates)},
        },
    }


def _mock_rule_generation_output_factory(
    candidates: tuple[str, ...],
) -> Callable[[PromptEnvelope], Mapping[str, object]]:
    def factory(envelope: PromptEnvelope) -> Mapping[str, object]:
        del envelope  # Nothing in the envelope changes the mock's answer.
        return {
            "schema_version": RULE_GENERATION_SCHEMA_VERSION,
            "provenance": Provenance.AI_INTERPRETATION.value,
            "canonical_value": candidates[0],
        }

    return factory


def build_rule_generation_contract(candidates: Sequence[str]) -> OutputContract:
    """Build the `OutputContract` for one AI-assisted rule-generation
    request, its schema restricted to exactly `candidates`.

    Raises `ValueError` when `candidates` has fewer than 2 entries: with
    zero or one candidate there is no genuine choice to ask a provider
    to make (`rules.generation.extract_ai_assist_candidates` already
    enforces this same minimum before a candidate list ever reaches
    here).
    """
    if len(candidates) < _MIN_CANDIDATES:
        raise ValueError(
            f"build_rule_generation_contract: candidates must have at least "
            f"{_MIN_CANDIDATES} entries"
        )
    ordered = tuple(candidates)
    return OutputContract(
        name=RULE_GENERATION_CONTRACT_NAME,
        json_schema=rule_generation_json_schema(ordered),
        instructions=RULE_GENERATION_INSTRUCTIONS_TEMPLATE.format(
            schema_version=RULE_GENERATION_SCHEMA_VERSION,
            provenance=Provenance.AI_INTERPRETATION.value,
        ),
        max_output_tokens=RULE_GENERATION_MAX_OUTPUT_TOKENS,
        mock_output_factory=_mock_rule_generation_output_factory(ordered),
    )


def _dedupe(
    reasons: list[RuleGenerationRejectionReason],
) -> tuple[RuleGenerationRejectionReason, ...]:
    return tuple(dict.fromkeys(reasons))


def _safe_summary(accepted: bool, reasons: tuple[RuleGenerationRejectionReason, ...]) -> str:
    if accepted:
        return "accepted"
    return "rejected: " + ", ".join(reason.value for reason in reasons)


def validate_rule_generation_output(
    raw_output: Mapping[str, object], candidates: Sequence[str]
) -> RuleGenerationOutcome:
    """Validate `raw_output` against exactly `candidates` — the same
    candidate list `build_rule_generation_contract` built the request's
    schema from. Never raises: any structural problem produces a
    rejected `RuleGenerationOutcome` instead, mirroring
    `ai_boundary.validation.validate_model_output`'s own safe-fallback
    contract.
    """
    if not isinstance(raw_output, Mapping):
        invalid_shape = (RuleGenerationRejectionReason.SCHEMA_INVALID,)
        return RuleGenerationOutcome(
            accepted=False,
            canonical_value=None,
            rejection_reasons=invalid_shape,
            safe_summary=_safe_summary(False, invalid_shape),
        )

    reasons: list[RuleGenerationRejectionReason] = []
    present_keys = set(raw_output.keys())

    if present_keys - _REQUIRED_KEYS:
        reasons.append(RuleGenerationRejectionReason.UNSUPPORTED_CONTROL_FIELD)
    if _REQUIRED_KEYS - present_keys:
        reasons.append(RuleGenerationRejectionReason.SCHEMA_INVALID)
        deduped = _dedupe(reasons)
        return RuleGenerationOutcome(
            accepted=False,
            canonical_value=None,
            rejection_reasons=deduped,
            safe_summary=_safe_summary(False, deduped),
        )

    if raw_output.get("schema_version") != RULE_GENERATION_SCHEMA_VERSION:
        reasons.append(RuleGenerationRejectionReason.SCHEMA_INVALID)

    if raw_output.get("provenance") != Provenance.AI_INTERPRETATION.value:
        reasons.append(RuleGenerationRejectionReason.INVALID_PROVENANCE)

    canonical_value = raw_output.get("canonical_value")
    if not isinstance(canonical_value, str):
        reasons.append(RuleGenerationRejectionReason.SCHEMA_INVALID)
    elif canonical_value not in candidates:
        reasons.append(RuleGenerationRejectionReason.VALUE_NOT_CANDIDATE)

    deduped = _dedupe(reasons)
    accepted = not deduped
    value = canonical_value if accepted and isinstance(canonical_value, str) else None
    return RuleGenerationOutcome(
        accepted=accepted,
        canonical_value=value,
        rejection_reasons=deduped,
        safe_summary=_safe_summary(accepted, deduped),
    )


__all__ = [
    "RULE_GENERATION_CONTRACT_NAME",
    "RULE_GENERATION_MAX_OUTPUT_TOKENS",
    "RULE_GENERATION_SCHEMA_VERSION",
    "RuleGenerationOutcome",
    "RuleGenerationRejectionReason",
    "build_rule_generation_contract",
    "rule_generation_json_schema",
    "validate_rule_generation_output",
]
