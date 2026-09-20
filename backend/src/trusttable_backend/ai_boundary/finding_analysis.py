"""The structured finding-analysis output contract and its role-aware
validator (`AI-08`, `docs/decision-log.md` D-040, resolving `FUP-011`'s
durable direction for the finding-analysis surface).

`EVAL-AI-01`/D-039 showed that screening unrestricted prose lexically has
open-ended coverage. This module moves the finding-analysis call to a
**versioned, structurally constrained output contract** whose semantic roles
are validated separately instead:

1. **explanation** — what the finding means, grounded in supplied evidence;
2. **business impact** — 1 to 3 *potential*-impact statements, each stating
   the condition under which it would hold. The model does **not** choose how
   a statement is labelled: it has no `basis` field. TrustTable derives the
   label afterwards from what it can establish (a statement that cites a
   context field that was actually sent as confirmed context is shown as
   informed by that context; every other statement is shown as conditional),
   so model prose can never award itself the standing of an established fact;
3. **remediation** — 1 to 3 advisory steps a person could take;
4. **validation rule** — one *proposed* rule from the closed set in
   `docs/product-requirements.md` §13, never an active or applied rule.

The contract is built per request (`build_finding_analysis_contract`) so the
JSON schema handed to a constrained-decoding runtime enumerates exactly the
evidence ids, column keys, context fields and numeric-fact names that were
actually sent: a runtime that honors it cannot even emit an unknown id or a
context-backed statement when no confirmed context was supplied. The
validator below is nevertheless the sole acceptance authority — a provider
that ignores the schema is held to the same rules.

Validation rules (each a distinct, tested `RejectionReason`):

- schema, types, bounds and enums; extra keys are unsupported control fields
  (there is no severity, score or finding field to override);
- provenance must be `ai_interpretation`;
- evidence ids and columns must be real (top level and per statement), and a
  named context field must be one that was actually sent;
- every impact statement must state the condition under which it would hold
  (`assumption`), and a context field it cites must be one that was actually
  sent; there is no model-chosen basis to validate, and no lexical list
  decides whether a consequence is "established" — none is, by construction;
- an *explanation* (an assertion about the finding, not a potential impact)
  may not use a consequence term (loss, penalty, regulatory, customer,
  revenue, ...) that the supplied evidence or confirmed context does not
  itself contain;
- every number in prose must appear in the supplied evidence, confirmed
  context or known numeric facts (a small structural allowance for
  `0`/`1`/`100` applies only inside a proposed rule's description, where a
  bound is a proposal, not a claim about the data);
- remediation steps and rule descriptions may not claim that data was (or
  will automatically be) changed or that a rule was applied or activated;
- `EVAL-AI-01`'s claim screen still runs over every text field as defense
  in depth.

The residual limit is stated plainly (`docs/decision-log.md` D-040): the
free-text fields inside the structure remain lexically screened, so the
guarantee of deterministic authority — not this validator — is what makes a
misleading sentence non-authoritative.

Framework-independent: stdlib only, no I/O, no `eval`/`exec`, only bounded
regular-expression quantifiers.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Final

from ..domain.evidence import Evidence
from ..domain.explanation import ValidationRuleType
from ..domain.value_objects import Provenance
from .claim_screen import (
    CLAIM_FAMILY_DATASET_PERFECTION,
    CLAIM_FAMILY_NO_ISSUES,
    normalize_narrative,
    screen_narrative,
)
from .envelope import PromptEnvelope
from .output_contract import OutputContract
from .prompt import serialize_evidence_for_provider
from .validation import RejectionReason, ValidationOutcome

FINDING_ANALYSIS_SCHEMA_VERSION: Final[str] = "finding_analysis_v1"
FINDING_ANALYSIS_CONTRACT_NAME: Final[str] = "finding_analysis_v1"

MAX_EXPLANATION_LENGTH: Final[int] = 600
MAX_STATEMENT_LENGTH: Final[int] = 400
MAX_ASSUMPTION_LENGTH: Final[int] = 300
MAX_STEP_LENGTH: Final[int] = 400
MAX_RULE_DESCRIPTION_LENGTH: Final[int] = 400
MAX_IMPACT_STATEMENTS: Final[int] = 3
MAX_REMEDIATION_STEPS: Final[int] = 3
MAX_RULE_COLUMNS: Final[int] = 5
MAX_REFERENCE_LIST: Final[int] = 10

#: An output-token bound generous for the worst case the schema's own length
#: limits allow, yet small enough for a CPU-bound baseline model.
FINDING_ANALYSIS_MAX_OUTPUT_TOKENS: Final[int] = 1024

#: Numbers that may appear in a proposed rule's *description* without being
#: grounded in evidence: structural bounds a rule proposes (a percentage
#: lies between 0 and 100; a count is at least 0 or 1). Never applied to
#: explanation, impact or remediation prose.
RULE_DESCRIPTION_STRUCTURAL_NUMBERS: Final[frozenset[float]] = frozenset({0.0, 1.0, 100.0})

_REQUIRED_KEYS: Final[frozenset[str]] = frozenset(
    {
        "schema_version",
        "provenance",
        "explanation",
        "business_impact",
        "remediation",
        "validation_rule",
        "referenced_evidence_ids",
        "referenced_columns",
    }
)
_ALLOWED_KEYS: Final[frozenset[str]] = _REQUIRED_KEYS | {"numeric_claims"}
_IMPACT_KEYS: Final[frozenset[str]] = frozenset(
    {"statement", "evidence_ids", "context_fields", "assumption"}
)
_RULE_KEYS: Final[frozenset[str]] = frozenset({"rule_type", "columns", "description"})
_RULE_TYPES: Final[frozenset[str]] = frozenset(member.value for member in ValidationRuleType)

FINDING_ANALYSIS_INSTRUCTIONS: Final[str] = (
    "Respond with a single JSON object only: no other text, no markdown code "
    "fences. Use exactly these keys: "
    f'"schema_version" (use "{FINDING_ANALYSIS_SCHEMA_VERSION}"), '
    '"provenance" (use "ai_interpretation"), '
    '"explanation" (one or two plain sentences on what the finding means), '
    '"business_impact" (1 to 3 objects, each with the keys "statement", '
    '"evidence_ids", "context_fields" and "assumption"), '
    '"remediation" (1 to 3 short advisory steps a person could take), '
    '"validation_rule" (one object with "rule_type", "columns" and "description": '
    "a single proposed data-quality rule), "
    '"referenced_evidence_ids" (the evidence ids you relied on), '
    '"referenced_columns" (the column keys you relied on), and optionally '
    '"numeric_claims" (an object mapping a supplied number\'s name to its exact '
    "supplied value). Each business_impact object is a POTENTIAL impact, not an "
    'established fact: put the statement in "statement", the condition that must '
    'hold for it to apply in "assumption" (never empty), the evidence ids it '
    'relates to in "evidence_ids", and, only if it draws on the supplied '
    'confirmed_context, those field names in "context_fields" (otherwise an empty '
    "list). You do not label how well-founded a statement is; that is decided "
    "elsewhere. Never state a monetary amount, a named customer, a regulation or "
    "a business process unless it appears in the supplied evidence or confirmed "
    "context. Use only numbers that appear in "
    "the supplied evidence or confirmed context. Remediation steps are advice for "
    "a person: never say data was or will be changed automatically. The "
    "validation rule is only a proposal: never say it was applied or is active. "
    "Do not include any key not listed here."
)


# --- Contract construction -------------------------------------------------


def _string_schema(max_length: int, *, min_length: int = 1) -> dict[str, Any]:
    return {"type": "string", "minLength": min_length, "maxLength": max_length}


def _enum_list_schema(
    values: Sequence[str], *, max_items: int, min_items: int = 0
) -> dict[str, Any]:
    """An array whose items are drawn from `values` only. An empty `values`
    yields an array that can only be empty."""
    if not values:
        return {"type": "array", "maxItems": 0}
    return {
        "type": "array",
        "minItems": min_items,
        "maxItems": max_items,
        "items": {"type": "string", "enum": list(values)},
    }


def finding_analysis_json_schema(
    *,
    evidence_ids: Sequence[str],
    column_keys: Sequence[str],
    context_fields: Sequence[str],
    numeric_fact_names: Sequence[str],
) -> dict[str, Any]:
    """The JSON Schema for `finding_analysis_v1`, with every reference list
    restricted to the values actually supplied for this request."""
    numeric_properties: dict[str, Any] = {name: {"type": "number"} for name in numeric_fact_names}
    return {
        "type": "object",
        "additionalProperties": False,
        "required": sorted(_REQUIRED_KEYS),
        "properties": {
            "schema_version": {"type": "string", "enum": [FINDING_ANALYSIS_SCHEMA_VERSION]},
            "provenance": {"type": "string", "enum": [Provenance.AI_INTERPRETATION.value]},
            "explanation": _string_schema(MAX_EXPLANATION_LENGTH),
            "business_impact": {
                "type": "array",
                "minItems": 1,
                "maxItems": MAX_IMPACT_STATEMENTS,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": sorted(_IMPACT_KEYS),
                    "properties": {
                        "statement": _string_schema(MAX_STATEMENT_LENGTH),
                        "evidence_ids": _enum_list_schema(
                            evidence_ids, max_items=MAX_REFERENCE_LIST
                        ),
                        "context_fields": _enum_list_schema(
                            context_fields, max_items=MAX_REFERENCE_LIST
                        ),
                        "assumption": _string_schema(MAX_ASSUMPTION_LENGTH),
                    },
                },
            },
            "remediation": {
                "type": "array",
                "minItems": 1,
                "maxItems": MAX_REMEDIATION_STEPS,
                "items": _string_schema(MAX_STEP_LENGTH),
            },
            "validation_rule": {
                "type": "object",
                "additionalProperties": False,
                "required": sorted(_RULE_KEYS),
                "properties": {
                    "rule_type": {"type": "string", "enum": sorted(_RULE_TYPES)},
                    "columns": _enum_list_schema(column_keys, max_items=MAX_RULE_COLUMNS),
                    "description": _string_schema(MAX_RULE_DESCRIPTION_LENGTH),
                },
            },
            "referenced_evidence_ids": _enum_list_schema(
                evidence_ids, max_items=MAX_REFERENCE_LIST, min_items=1 if evidence_ids else 0
            ),
            "referenced_columns": _enum_list_schema(column_keys, max_items=MAX_REFERENCE_LIST),
            "numeric_claims": {
                "type": "object",
                "additionalProperties": False,
                "properties": numeric_properties,
            },
        },
    }


def _evidence_column_keys(evidence: Sequence[Evidence]) -> list[str]:
    return list(
        dict.fromkeys(column.internal_key for item in evidence for column in item.affected_columns)
    )


def mock_finding_analysis_output(envelope: PromptEnvelope) -> dict[str, object]:
    """A schema-valid, grounded default output for `MockProvider`, built
    only from what `envelope` actually carries. Deliberately plain: no
    digits, no consequence terms, no context references, so it is accepted
    for any real finding."""
    evidence_ids = [item.evidence_id for item in envelope.computed_evidence]
    column_keys = _evidence_column_keys(envelope.computed_evidence)
    impact: dict[str, object] = {
        "statement": "Downstream users may draw conclusions from data with this condition.",
        "evidence_ids": evidence_ids[:1],
        "context_fields": [],
        "assumption": "the affected data is used for decisions",
    }
    return {
        "schema_version": FINDING_ANALYSIS_SCHEMA_VERSION,
        "provenance": Provenance.AI_INTERPRETATION.value,
        "explanation": (
            "A deterministic check flagged this finding; the supplied evidence shows what "
            "was found."
        ),
        "business_impact": [impact],
        "remediation": ["Review the affected values in the source data and correct them there."],
        "validation_rule": {
            "rule_type": ValidationRuleType.NOT_NULL.value,
            "columns": column_keys[:MAX_RULE_COLUMNS],
            "description": "Proposed: the affected columns should satisfy this check.",
        },
        "referenced_evidence_ids": evidence_ids,
        "referenced_columns": column_keys,
    }


def build_finding_analysis_contract(
    *,
    evidence: Sequence[Evidence],
    context_fields: Sequence[str],
    numeric_fact_names: Sequence[str],
) -> OutputContract:
    """Build the `OutputContract` for one finding-analysis request, its
    schema restricted to the evidence ids, columns, context fields and
    numeric-fact names actually supplied."""
    schema = finding_analysis_json_schema(
        evidence_ids=[item.evidence_id for item in evidence],
        column_keys=_evidence_column_keys(evidence),
        context_fields=list(context_fields),
        numeric_fact_names=list(numeric_fact_names),
    )
    factory: Callable[[PromptEnvelope], Mapping[str, object]] = mock_finding_analysis_output
    return OutputContract(
        name=FINDING_ANALYSIS_CONTRACT_NAME,
        json_schema=schema,
        instructions=FINDING_ANALYSIS_INSTRUCTIONS,
        max_output_tokens=FINDING_ANALYSIS_MAX_OUTPUT_TOKENS,
        mock_output_factory=factory,
    )


# --- Text grounding helpers ------------------------------------------------

_NUMBER_RE: Final[re.Pattern[str]] = re.compile(r"(?<![\w.])(\d[\d,]{0,30}(?:\.\d{1,20})?)(?!\w)")

# A bounded, closed list of consequence terms. A term here is only an
# unsupported claim when the supplied evidence and confirmed context do not
# themselves contain it (a `revenue` column grounds the word "revenue").
_CONSEQUENCE_STEMS: Final[tuple[str, ...]] = (
    "revenue",
    "profit",
    "loss",
    "cost",
    "penalt",
    "fine",
    "lawsuit",
    "legal",
    "regulat",
    "complian",
    "audit",
    "gdpr",
    "hipaa",
    "sox",
    "churn",
    "refund",
    "chargeback",
    "customer",
    "client",
    "supplier",
    "vendor",
    "shipment",
    "invoice",
    "payroll",
    "patient",
    "employee",
    "contract",
    "tax",
    "fraud",
    "bankrupt",
    "shareholder",
    "investor",
)
# Stems whose plain prefix match would also hit ordinary, unrelated words
# ("fine" -> "finer", "loss" -> "lossless", "cost" -> "costume", "tax" ->
# "taxonomy") get an exact-form pattern instead.
_CONSEQUENCE_EXACT: Final[dict[str, str]] = {
    "fine": r"\b(?:fines|fined)\b",
    "loss": r"\b(?:loss|losses)\b",
    "cost": r"\bcost(?:s|ly)?\b",
    "tax": r"\btax(?:es|ation)?\b",
    "sox": r"\bsox\b",
}
_CONSEQUENCE_RES: Final[tuple[tuple[str, re.Pattern[str]], ...]] = tuple(
    (
        stem,
        re.compile(_CONSEQUENCE_EXACT.get(stem, rf"\b{re.escape(stem)}\w{{0,12}}")),
    )
    for stem in _CONSEQUENCE_STEMS
)

_PERFORMED_VERBS: Final[str] = (
    r"(?:fix|correct|repair|remov|delet|drop|updat|clean|overwrit|modif|chang|alter|merg|"
    r"imput|fill|normali[sz]|standardi[sz]|appl|activat|enabl|enforc)"
)
_PAST_PARTICIPLES: Final[str] = (
    r"(?:fixed|corrected|repaired|removed|deleted|dropped|updated|cleaned|overwritten|"
    r"modified|changed|altered|merged|imputed|filled|normali[sz]ed|standardi[sz]ed|"
    r"applied|activated|enabled|enforced)"
)
_ACTION_CLAIM_RES: Final[tuple[re.Pattern[str], ...]] = (
    # "we fixed", "TrustTable will remove", "the system has corrected"
    re.compile(
        r"\b(?:trusttable|the\s+(?:application|system|tool|app|platform)|we|i)\s+"
        r"(?:(?:have|has|had|will|shall|can|would|are\s+going\s+to)\s+)?"
        r"(?:(?:already|automatically|also|then)\s+){0,2}" + _PERFORMED_VERBS + r"\w{0,6}"
    ),
    # "automatically removed", "already corrected", "auto fixes"
    re.compile(r"\b(?:automatically|auto|already)\s+(?:been\s+)?" + _PERFORMED_VERBS),
    # "the duplicates have been removed", "the data was corrected"
    re.compile(
        r"\b(?:data|values?|rows?|records?|files?|datasets?|duplicates?|entries)\s+"
        r"(?:has|have|had|was|were)\s+been\s+" + _PAST_PARTICIPLES + r"\b"
    ),
    # "this rule is now active", "the check has been enforced"
    re.compile(
        r"\b(?:rules?|checks?|validations?)\s+"
        r"(?:is|are|was|were|has\s+been|have\s+been|will\s+be)\s+"
        r"(?:(?:now|already|automatically)\s+){0,2}"
        r"(?:active|activated|enabled|applied|enforced|running|live|in\s+effect|in\s+force)\b"
    ),
)

# Voice-independent action claims (semantic review of revision 5). The patterns
# above need an explicit subject or a fixed word order, so a passive or
# subject-less claim ("The duplicate rows will be removed automatically.",
# "Rows get deleted for you.", "The rule will run on every upload.") passed.
# These are applied per sentence, whatever the grammatical voice, and are biased
# toward rejecting: advice to a person never needs to say that something happens
# "automatically" or "for you", and a false rejection degrades safely to the
# built-in guidance. A sentence that is a request to a person ("Verify that the
# duplicates were removed") is exempt, as everywhere in advice text.
_AUTOMATION_MARKER_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(?:automatically|autonomously|by\s+itself|on\s+(?:its|their)\s+own|for\s+you|"
    r"behind\s+the\s+scenes|without\s+(?:any\s+)?(?:manual|human)\s+(?:action|effort|input))\b"
)
_CHANGE_PARTICIPLES: Final[str] = (
    r"(?:fixed|corrected|repaired|removed|deleted|dropped|updated|cleaned|cleansed|overwritten|"
    r"modified|changed|altered|merged|imputed|filled|normali[sz]ed|standardi[sz]ed|replaced|"
    r"trimmed|converted|reformatted|rewritten|deduplicated|de-duplicated|purged|erased|"
    r"discarded|edited|adjusted|patched|reset|truncated|applied|activated|enabled|enforced)"
)
_FUTURE_OR_GET_CLAIM_RE: Final[re.Pattern[str]] = re.compile(
    # "will be removed", "get deleted", "is being fixed", "will then be cleaned"
    r"(?:\b(?:will|shall)\b|'ll\b|\bgets?\b|\bgot\b|\b(?:is|are)\s+being\b)\s+"
    r"(?:(?:now|then|also|already|always|immediately|simply)\s+){0,2}(?:be\s+)?"
    r"(?:(?:now|then|also|already|always|immediately|simply)\s+){0,2}" + _CHANGE_PARTICIPLES
)
_RULE_EXECUTION_CLAIM_RE: Final[re.Pattern[str]] = re.compile(
    # "will run", "will be enforced", "will block rows that fail"
    r"(?:\b(?:will|shall)\b|'ll\b)\s+(?:(?:now|then|also|always)\s+){0,2}(?:be\s+)?"
    r"(?:(?:now|then|also|always)\s+){0,2}(?:run|execute[ds]?|appl(?:y|ied)|enforce[ds]?|trigger(?:ed)?|activate[ds]?|"
    r"enable[ds]?|block(?:ed)?|reject(?:ed)?)\b"
)
_STATE_CLAIM_RE: Final[re.Pattern[str]] = re.compile(
    # "The duplicates are removed", "Rows are fixed" — a present-tense state claim
    # anchored on a data noun; exempted below when the sentence is purposive or
    # modal advice ("... so that rows are cleaned before loading").
    r"\b(?:data|values?|rows?|records?|entries|files?|datasets?|duplicates?|columns?|cells?)\s+"
    r"(?:is|are)\s+(?:(?:now|then|also|already)\s+)?" + _CHANGE_PARTICIPLES
)
_PURPOSIVE_OR_MODAL_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(?:so|that|before|until|unless|once|after|when|if|whether|should|must|need|needs|"
    r"ought|ensure|consider|recommend\w*|suggest\w*)\b"
)


# --- Claim screening for directive (advice) text --------------------------
#
# EVAL-AI-01's screen is context-blind: it cannot tell the imperative verb in
# "correct them at the source" from the quality adjective in "the data is
# correct", nor a request to a person ("Verify that the values are valid")
# from an assertion. Explanations and impact statements are *assertions*, so
# they get the full screen unchanged. Remediation steps and rule descriptions
# are *advice*, so two narrow, tested adjustments apply to them only:
#
# 1. "correct"/"clean" followed by an object or determiner is a verb, not the
#    quality adjective ("... and correct them there"), and is rewritten to a
#    neutral verb before screening;
# 2. a sentence that begins with a directive verb plus "that"/"whether"/"if"
#    ("Confirm that the rows are valid") is a request, not an assertion, so it
#    is exempt from the two whole-dataset quality families only. Every other
#    family (disregard findings, score override, fitness assurance) still
#    applies to it, and every non-directive sentence is screened in full.
#
# Residual limit, stated plainly in D-040: a claim comma-spliced onto a
# directive sentence can evade the exemption; deterministic authority, not
# this screen, remains the guarantee.

_IMPERATIVE_OBJECT_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(?:correct|clean)\s+(?=(?:them|it|these|those|this|that|the|all|any|each|every|"
    r"your|our|its|their|a|an)\b)",
    re.IGNORECASE,
)
_DIRECTIVE_FRAME_RE: Final[re.Pattern[str]] = re.compile(
    r"^\W*(?:please\s+)?(?:verify|confirm|check|ensure|make\s+sure|determine|decide|"
    r"investigate|review|see|assess|validate|test|find\s+out)\s+(?:that|whether|if)\b",
    re.IGNORECASE,
)
_SENTENCE_SPLIT_RE: Final[re.Pattern[str]] = re.compile(r"[.!?;:\n]+")
_QUALITY_FAMILIES: Final[frozenset[str]] = frozenset(
    {CLAIM_FAMILY_DATASET_PERFECTION, CLAIM_FAMILY_NO_ISSUES}
)


def _directive_text_makes_a_claim(text: str) -> bool:
    """Whether advice text (a remediation step or rule description) asserts
    an unsupported claim, under the two adjustments described above."""
    rewritten = _IMPERATIVE_OBJECT_RE.sub("fix ", text)
    sentences = [s for s in _SENTENCE_SPLIT_RE.split(rewritten) if s.strip()]
    if not any(_DIRECTIVE_FRAME_RE.match(s) for s in sentences):
        return bool(screen_narrative(rewritten))
    for sentence in sentences:
        families = screen_narrative(sentence)
        if _DIRECTIVE_FRAME_RE.match(sentence):
            families = families - _QUALITY_FAMILIES
        if families:
            return True
    return False


def _numbers_in(text: str) -> list[float]:
    values: list[float] = []
    for match in _NUMBER_RE.finditer(normalize_narrative(text)):
        try:
            values.append(float(match.group(1).replace(",", "")))
        except ValueError:
            continue
    return values


def _walk_scalars(value: object) -> list[object]:
    if isinstance(value, Mapping):
        found: list[object] = []
        for key, inner in value.items():
            found.append(key)
            found.extend(_walk_scalars(inner))
        return found
    if isinstance(value, list | tuple | set | frozenset):
        found = []
        for inner in value:
            found.extend(_walk_scalars(inner))
        return found
    return [value]


class _Grounding:
    """What the model was actually given: the only source a number or a
    consequence term in its prose may be grounded in."""

    def __init__(
        self,
        envelope: PromptEnvelope,
        known_numeric_facts: Mapping[str, float],
    ) -> None:
        numbers: list[float] = [float(value) for value in known_numeric_facts.values()]
        texts: list[str] = []

        def take(scalar: object) -> None:
            if isinstance(scalar, bool):
                return
            if isinstance(scalar, int | float):
                numbers.append(float(scalar))
            elif isinstance(scalar, str):
                texts.append(scalar)
                numbers.extend(_numbers_in(scalar))

        for item in envelope.computed_evidence:
            # Ground only in what the provider was actually shown (the
            # allow-listed serialization), never in the canonical evidence:
            # a term or number that appears only in withheld raw content —
            # a flagged cell's excerpt, a raw casing — must not count as
            # "supplied", or a model could pass validation on knowledge it
            # was never given.
            sent = serialize_evidence_for_provider(item)
            take(sent["evidence_id"])
            take(sent["display_safe_summary"])
            numbers.append(float(sent["affected_row_count"]))
            for column_key in sent["affected_columns"]:
                take(column_key)
            for scalar in _walk_scalars(sent["structured_payload"]):
                take(scalar)
        for scalar in _walk_scalars(dict(envelope.confirmed_context)):
            take(scalar)
        self.numbers: tuple[float, ...] = tuple(numbers)
        self.corpus: str = normalize_narrative(" ".join(texts))

    def has_number(self, value: float) -> bool:
        return any(math.isclose(value, known, rel_tol=1e-9, abs_tol=1e-9) for known in self.numbers)

    def has_term(self, stem: str) -> bool:
        return stem in self.corpus


def _ungrounded_numbers(
    text: str, grounding: _Grounding, *, structural: frozenset[float] = frozenset()
) -> bool:
    for value in _numbers_in(text):
        if value in structural:
            continue
        if not grounding.has_number(value):
            return True
    return False


def _ungrounded_consequence_term(text: str, grounding: _Grounding) -> bool:
    normalized = normalize_narrative(text)
    return any(
        pattern.search(normalized) is not None and not grounding.has_term(stem)
        for stem, pattern in _CONSEQUENCE_RES
    )


def _claims_action_was_taken(text: str) -> bool:
    """Whether advice text says data was, or will be, changed, or that a rule
    was, or will be, applied, run or enforced — see the two pattern groups
    above (subject-anchored, and voice-independent per sentence)."""
    normalized = normalize_narrative(text)
    if any(pattern.search(normalized) is not None for pattern in _ACTION_CLAIM_RES):
        return True
    # Split first: normalization strips the punctuation the split relies on.
    for raw_sentence in _SENTENCE_SPLIT_RE.split(text):
        sentence = normalize_narrative(raw_sentence)
        if not sentence or _DIRECTIVE_FRAME_RE.match(sentence):
            continue
        if (
            _AUTOMATION_MARKER_RE.search(sentence) is not None
            or _FUTURE_OR_GET_CLAIM_RE.search(sentence) is not None
            or _RULE_EXECUTION_CLAIM_RE.search(sentence) is not None
        ):
            return True
        if (
            _STATE_CLAIM_RE.search(sentence) is not None
            and _PURPOSIVE_OR_MODAL_RE.search(sentence) is None
        ):
            return True
    return False


# --- Validation -------------------------------------------------------------


class _Findings:
    """Accumulates rejection reasons for one validation run."""

    def __init__(self) -> None:
        self.reasons: list[RejectionReason] = []
        self.schema_invalid = False

    def add(self, reason: RejectionReason) -> None:
        self.reasons.append(reason)

    def invalid(self) -> None:
        self.schema_invalid = True


def _bounded_text(
    value: object, max_length: int, findings: _Findings, *, allow_empty: bool = False
) -> str | None:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        findings.invalid()
        return None
    if len(value) > max_length:
        findings.invalid()
        return None
    return value


def _string_list(
    value: object,
    findings: _Findings,
    *,
    max_items: int,
    min_items: int = 0,
) -> list[str] | None:
    if not isinstance(value, list | tuple):
        findings.invalid()
        return None
    items = list(value)
    if len(items) > max_items or len(items) < min_items:
        findings.invalid()
        return None
    if not all(isinstance(item, str) for item in items):
        findings.invalid()
        return None
    return [str(item) for item in items]


def _check_impact_statement(
    raw: object,
    *,
    findings: _Findings,
    known_evidence_ids: set[str],
    sent_context_fields: set[str],
    grounding: _Grounding,
    texts: list[str],
) -> None:
    if not isinstance(raw, Mapping):
        findings.invalid()
        return
    keys = set(raw.keys())
    if keys - _IMPACT_KEYS:
        findings.add(RejectionReason.UNSUPPORTED_CONTROL_FIELD)
    if _IMPACT_KEYS - keys:
        findings.invalid()
        return

    statement = _bounded_text(raw["statement"], MAX_STATEMENT_LENGTH, findings)
    evidence_ids = _string_list(raw["evidence_ids"], findings, max_items=MAX_REFERENCE_LIST)
    context_fields = _string_list(raw["context_fields"], findings, max_items=MAX_REFERENCE_LIST)
    assumption = _bounded_text(raw["assumption"], MAX_ASSUMPTION_LENGTH, findings)
    if statement is None or evidence_ids is None or context_fields is None or assumption is None:
        return

    if any(eid not in known_evidence_ids for eid in evidence_ids):
        findings.add(RejectionReason.UNKNOWN_EVIDENCE_ID)
    if any(field not in sent_context_fields for field in context_fields):
        findings.add(RejectionReason.UNKNOWN_CONTEXT_FIELD)

    # There is no model-chosen basis to check. A statement is a *potential*
    # impact: it must state the condition under which it would hold
    # (`_bounded_text` above already rejected a blank one), and the label a
    # person sees is derived afterwards by TrustTable, never awarded by the
    # model. No lexical list is consulted here: whatever consequence the prose
    # names, it is presented as conditional advice, not as an established fact.
    texts.append(statement)
    texts.append(assumption)
    for prose in (statement, assumption):
        if _ungrounded_numbers(prose, grounding):
            findings.add(RejectionReason.UNKNOWN_NUMERIC_CLAIM)


def validate_finding_analysis_output(
    raw_output: Mapping[str, object],
    envelope: PromptEnvelope,
    *,
    known_numeric_facts: Mapping[str, float],
) -> ValidationOutcome:
    """Validate a `finding_analysis_v1` output against exactly what was
    sent in `envelope` plus `known_numeric_facts`. Collects every distinct
    violation rather than failing fast. Never raises on malformed input.
    """
    if not isinstance(raw_output, Mapping):
        return _outcome([RejectionReason.SCHEMA_INVALID])

    findings = _Findings()
    present = set(raw_output.keys())
    if present - _ALLOWED_KEYS:
        findings.add(RejectionReason.UNSUPPORTED_CONTROL_FIELD)
    if _REQUIRED_KEYS - present:
        findings.invalid()

    known_evidence_ids = {item.evidence_id for item in envelope.computed_evidence}
    known_columns: set[str] = set(_evidence_column_keys(envelope.computed_evidence))
    known_columns.update(
        sample.column.internal_key for sample in envelope.untrusted_dataset_samples
    )
    sent_context_fields = {str(key) for key in envelope.confirmed_context}
    grounding = _Grounding(envelope, known_numeric_facts)
    assertion_texts: list[str] = []
    directive_texts: list[str] = []

    if "schema_version" in raw_output and (
        raw_output["schema_version"] != FINDING_ANALYSIS_SCHEMA_VERSION
    ):
        findings.invalid()

    if "provenance" in raw_output:
        provenance = raw_output["provenance"]
        if not isinstance(provenance, str):
            findings.invalid()
        elif provenance != Provenance.AI_INTERPRETATION.value:
            findings.add(RejectionReason.INVALID_PROVENANCE)

    explanation: str | None = None
    if "explanation" in raw_output:
        explanation = _bounded_text(raw_output["explanation"], MAX_EXPLANATION_LENGTH, findings)
    if explanation is not None:
        assertion_texts.append(explanation)
        if _ungrounded_consequence_term(explanation, grounding):
            findings.add(RejectionReason.UNSUPPORTED_IMPACT_CLAIM)
        if _ungrounded_numbers(explanation, grounding):
            findings.add(RejectionReason.UNKNOWN_NUMERIC_CLAIM)

    if "business_impact" in raw_output:
        impact = raw_output["business_impact"]
        if not isinstance(impact, list | tuple) or not 1 <= len(impact) <= MAX_IMPACT_STATEMENTS:
            findings.invalid()
        else:
            for entry in impact:
                _check_impact_statement(
                    entry,
                    findings=findings,
                    known_evidence_ids=known_evidence_ids,
                    sent_context_fields=sent_context_fields,
                    grounding=grounding,
                    texts=assertion_texts,
                )

    if "remediation" in raw_output:
        steps = raw_output["remediation"]
        if not isinstance(steps, list | tuple) or not 1 <= len(steps) <= MAX_REMEDIATION_STEPS:
            findings.invalid()
        else:
            for step in steps:
                text = _bounded_text(step, MAX_STEP_LENGTH, findings)
                if text is None:
                    continue
                directive_texts.append(text)
                if _claims_action_was_taken(text):
                    findings.add(RejectionReason.UNSUPPORTED_ACTION_CLAIM)
                if _ungrounded_numbers(text, grounding):
                    findings.add(RejectionReason.UNKNOWN_NUMERIC_CLAIM)

    if "validation_rule" in raw_output:
        rule = raw_output["validation_rule"]
        if not isinstance(rule, Mapping):
            findings.invalid()
        else:
            if set(rule.keys()) - _RULE_KEYS:
                findings.add(RejectionReason.UNSUPPORTED_CONTROL_FIELD)
            if _RULE_KEYS - set(rule.keys()):
                findings.invalid()
            else:
                rule_type = rule["rule_type"]
                if not isinstance(rule_type, str) or rule_type not in _RULE_TYPES:
                    findings.invalid()
                columns = _string_list(rule["columns"], findings, max_items=MAX_RULE_COLUMNS)
                if columns is not None and any(col not in known_columns for col in columns):
                    findings.add(RejectionReason.UNKNOWN_COLUMN)
                description = _bounded_text(
                    rule["description"], MAX_RULE_DESCRIPTION_LENGTH, findings
                )
                if description is not None:
                    directive_texts.append(description)
                    if _claims_action_was_taken(description):
                        findings.add(RejectionReason.UNSUPPORTED_ACTION_CLAIM)
                    if _ungrounded_numbers(
                        description, grounding, structural=RULE_DESCRIPTION_STRUCTURAL_NUMBERS
                    ):
                        findings.add(RejectionReason.UNKNOWN_NUMERIC_CLAIM)

    if "referenced_evidence_ids" in raw_output:
        ids = _string_list(
            raw_output["referenced_evidence_ids"],
            findings,
            max_items=MAX_REFERENCE_LIST,
            min_items=1 if known_evidence_ids else 0,
        )
        if ids is not None and any(eid not in known_evidence_ids for eid in ids):
            findings.add(RejectionReason.UNKNOWN_EVIDENCE_ID)

    if "referenced_columns" in raw_output:
        cols = _string_list(
            raw_output["referenced_columns"], findings, max_items=MAX_REFERENCE_LIST
        )
        if cols is not None and any(col not in known_columns for col in cols):
            findings.add(RejectionReason.UNKNOWN_COLUMN)

    if "numeric_claims" in raw_output:
        claims = raw_output["numeric_claims"]
        if not isinstance(claims, Mapping):
            findings.invalid()
        else:
            for key, claimed in claims.items():
                if key not in known_numeric_facts:
                    findings.add(RejectionReason.UNKNOWN_NUMERIC_CLAIM)
                    continue
                if isinstance(claimed, bool) or not isinstance(claimed, int | float):
                    findings.invalid()
                    continue
                if claimed != known_numeric_facts[key]:
                    findings.add(RejectionReason.NUMERIC_CLAIM_MISMATCH)

    # Defense in depth: EVAL-AI-01's claim screen over every text field —
    # in full over assertions, with the two advice-text adjustments over
    # remediation steps and the rule description.
    if any(screen_narrative(text) for text in assertion_texts) or any(
        _directive_text_makes_a_claim(text) for text in directive_texts
    ):
        findings.add(RejectionReason.UNSUPPORTED_CLAIM)

    reasons = list(findings.reasons)
    if findings.schema_invalid:
        reasons.insert(0, RejectionReason.SCHEMA_INVALID)
    return _outcome(reasons)


def _outcome(reasons: list[RejectionReason]) -> ValidationOutcome:
    deduped = tuple(dict.fromkeys(reasons))
    accepted = not deduped
    summary = (
        "accepted" if accepted else "rejected: " + ", ".join(reason.value for reason in deduped)
    )
    return ValidationOutcome(accepted=accepted, rejection_reasons=deduped, safe_summary=summary)


__all__ = [
    "FINDING_ANALYSIS_CONTRACT_NAME",
    "FINDING_ANALYSIS_INSTRUCTIONS",
    "FINDING_ANALYSIS_MAX_OUTPUT_TOKENS",
    "FINDING_ANALYSIS_SCHEMA_VERSION",
    "MAX_ASSUMPTION_LENGTH",
    "MAX_EXPLANATION_LENGTH",
    "MAX_IMPACT_STATEMENTS",
    "MAX_REFERENCE_LIST",
    "MAX_REMEDIATION_STEPS",
    "MAX_RULE_COLUMNS",
    "MAX_RULE_DESCRIPTION_LENGTH",
    "MAX_STATEMENT_LENGTH",
    "MAX_STEP_LENGTH",
    "RULE_DESCRIPTION_STRUCTURAL_NUMBERS",
    "build_finding_analysis_contract",
    "finding_analysis_json_schema",
    "mock_finding_analysis_output",
    "validate_finding_analysis_output",
]
