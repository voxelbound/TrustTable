"""Prompt-injection risk detector (`DET-SEC-01`), matching
`docs/detector-framework.md` §14's "Security detector" requirements:
bounded safe pattern matching across eight required pattern families,
case/whitespace normalization, length-limited inspection, negative
controls, exposure-aware severity, cautious wording, and row/column
evidence. Never executes or interprets matched text as an instruction
(`docs/product-requirements.md` §11, `docs/domain-model.md` §15) — this
module only reads and pattern-matches text; it contains no `eval`/`exec`
or other dynamic-code-execution of any scanned or matched value.

`DET-03` closure package 3 (`WP-110`, D-061, owner decision SD-989e7edf3d5a
option R; version 2): catalogue entries 40 (data-exfiltration instruction) and
41 (suspicious secret-request text) are covered by explicit **evidence subtypes**
of this detector, not by a second detector. The two heightened families
(`exfiltrate_data`, `disclose_secrets`) gain extended phrasings, matching adds
compatibility normalization and removal of invisible format characters, and the
stored excerpt is bounded and redacted. Finding identity, text, confidence,
severity and the trust score are unchanged for every column in which version 2
matches nothing that version 1 missed. Newly recognised phrasings count wherever
they appear (owner decision SD-0cc2de8a9889, option A), so a column version 1
already flagged can rise in confidence and severity when it also contains one.

Restricted to text-family columns (`TEXT`/`CATEGORICAL`/`IDENTIFIER`),
the same scope `consistency.py` already uses for its own detectors — the
only inferred types free-text/categorical instruction-like content can
realistically appear in.

Reuses `DET-01`'s existing `SecurityExposureState` unchanged for
exposure-aware severity (`docs/security-threat-model.md` §4); no "local
vs. remote model" distinction exists yet, so the "remote model
transmission: high" severity tier is not reachable by this detector — a
disclosed limitation, not a defect.

This is a separate, evidence-producing implementation from
`profiling.metrics`'s existing coarse `_INSTRUCTION_LIKE_PATTERN`
heuristic, which that module's own docstring already documents as
explicitly NOT this detector.

Framework-independent per `docs/architecture.md` §3's "Detectors" layer
rule; `pydantic.BaseModel` is used only for this detector's (currently
empty) `config_schema`.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Final

from pydantic import BaseModel

from ..domain.evidence import Evidence, EvidenceType
from ..domain.parsing import SamplingScope
from ..domain.value_objects import Severity
from ..profiling.schemas import InferredColumnType
from .contract import (
    DetectorCategory,
    DetectorMetadata,
    DetectorRunRequest,
    DetectorRunResult,
    DetectorRunStatus,
    DetectorSupportRequest,
    ExecutionMetrics,
    FindingCandidate,
    PerformanceClass,
    SecurityExposureState,
)


class _EmptyConfig(BaseModel):
    """No configurable parameters for this detector."""


_TEXT_FAMILY_TYPES: tuple[InferredColumnType, ...] = (
    InferredColumnType.TEXT,
    InferredColumnType.CATEGORICAL,
    InferredColumnType.IDENTIFIER,
)

_MAX_INSPECTED_LENGTH: Final[int] = 4000
"""Values are normalized then truncated to this many characters before
pattern matching. A new, disclosed constant (no document fixes an exact
number) — chosen well below `Settings.max_text_value_length_for_analysis`
(10,000, a different, already-existing general analysis-time bound) to
keep this detector's bounded regex scanning cheap per value while still
comfortably covering realistic free-text cell content. Content beyond
this bound is never inspected by this detector. This bound is also the
primary mechanism behind the "bounded safe matching"/"no catastrophic
regular expressions" requirement: every pattern below is additionally a
simple alternation with only small, fixed quantifiers (no unbounded
nested quantifiers), so no single scanned value can make matching
expensive regardless of its original length."""

_TRUNCATED_SAMPLE_LENGTH: Final[int] = 80
"""Evidence's `truncated_sample_prefix` is capped at this many
characters — `docs/domain-model.md` §15's "escaped, truncated display
sample" field, and `docs/security-threat-model.md` §5's "logs must not
contain... full suspicious text" requirement. Not a general-purpose
redaction engine (`PRIV-01`, still deferred) — a bounded literal excerpt
only."""

_HEIGHTENED_FAMILIES: Final[frozenset[str]] = frozenset({"disclose_secrets", "exfiltrate_data"})
"""Families that map to `docs/security-threat-model.md` §4's
"exfiltration or secret requests: high or critical" severity tier,
rather than its ordinary "no model transmission: informational or low" /
"local model transmission: medium" tier."""

_PATTERN_FAMILIES: Final[tuple[tuple[str, re.Pattern[str]], ...]] = (
    (
        "ignore_previous_instructions",
        re.compile(
            r"\b(ignore|disregard)\s+(all\s+)?(previous|prior)\s+instructions\b",
            re.IGNORECASE,
        ),
    ),
    (
        "reveal_system_prompt",
        re.compile(
            r"\b(reveal|show|print|display)\s+(me\s+)?(the\s+)?(system|hidden)\s+prompt\b",
            re.IGNORECASE,
        ),
    ),
    (
        "act_as_another_system",
        re.compile(
            r"\byou\s+are\s+now\b"
            r"|\bact\s+as\s+(a|an)\s+\w+(\s+\w+){0,3}\b"
            r"|\bpretend\s+(that\s+)?you\s+are\b",
            re.IGNORECASE,
        ),
    ),
    (
        "suppress_reporting",
        re.compile(
            r"\b(do\s+not|don'?t)\s+(report|mention|flag|disclose)\s+(this|these|any)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "claim_data_valid",
        re.compile(
            r"\b(claim|say|state)\s+(this|the)\s+(dataset|data)\s+is\s+"
            r"(perfect|valid|clean|accurate)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "forced_output_only",
        re.compile(
            r"\b(output|respond|answer)\s+only\b|\bonly\s+(output|respond|say|answer)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "disclose_secrets",
        re.compile(
            r"\b(reveal|disclose|share|give)\s+(me\s+)?(the\s+)?"
            r"(api\s*key|password|secret|credentials?)\b",
            re.IGNORECASE,
        ),
    ),
    (
        "exfiltrate_data",
        re.compile(
            r"\b(send|email|post|upload|export)\s+(this\s+|the\s+)?data\s+(to|externally)\b",
            re.IGNORECASE,
        ),
    ),
)
"""Eight fixed, bounded pattern families — one per
`docs/detector-framework.md` §14 example bullet ("ignore previous
instructions", "reveal system prompt", "act as another system", "do not
report this issue", "claim the data is valid", "output only a specified
answer", "disclose secrets", "send data externally"). Each pattern is a
simple alternation with small, fixed quantifiers only — no unbounded
nested quantifiers/catastrophic-backtracking shapes."""


_MAX_RAW_LENGTH: Final[int] = 16_000
"""A value is cut to this many characters **before** normalization so the
(linear) Unicode normalization below can never be driven by an arbitrarily long
cell. Always larger than `_MAX_INSPECTED_LENGTH`, so it never changes what is
inspected for ordinary text."""

SUBTYPE_PROMPT_INJECTION: Final[str] = "prompt_injection"
SUBTYPE_EXFILTRATION_INSTRUCTION: Final[str] = "exfiltration_instruction"
SUBTYPE_SECRET_REQUEST: Final[str] = "secret_request"

#: The closed, ordered subtype vocabulary (`DET-03` closure package 2 of the
#: Core detector catalogue, D-061 with owner decision SD-989e7edf3d5a option R).
#: Catalogue entry 39 is `prompt_injection`, entry 40 `exfiltration_instruction`
#: and entry 41 `secret_request`: one detector, one finding per column, explicit
#: evidence subtypes.
RISK_SUBTYPES: Final[tuple[str, ...]] = (
    SUBTYPE_PROMPT_INJECTION,
    SUBTYPE_EXFILTRATION_INSTRUCTION,
    SUBTYPE_SECRET_REQUEST,
)

_FAMILY_SUBTYPE: Final[dict[str, str]] = {
    "exfiltrate_data": SUBTYPE_EXFILTRATION_INSTRUCTION,
    "disclose_secrets": SUBTYPE_SECRET_REQUEST,
}
"""Every family not listed here is a `prompt_injection` family."""

_SECRET_NOUN: Final[str] = (
    r"(api[\s_-]?keys?|access\s+tokens?|auth(entication)?\s+tokens?|bearer\s+tokens?"
    r"|passwords?|passphrases?|secret\s+keys?|private\s+keys?|ssh\s+keys?|credentials?"
    r"|connection\s+strings?)"
)
_EXTENDED_PATTERNS: Final[dict[str, tuple[re.Pattern[str], ...]]] = {
    # Extended phrasings of the two heightened families. They are *additional*
    # patterns under the same family name, so every version 1 match still
    # matches. Each is a short alternation with fixed small quantifiers only.
    "disclose_secrets": (
        re.compile(
            r"\b(tell|provide|show|print|display|paste|send|email|output|return|list|dump"
            r"|expose|leak|hand\s+over|read\s+out)\s+(me\s+|us\s+)?"
            r"(the\s+|your\s+|all\s+the\s+|all\s+of\s+the\s+|all\s+|any\s+)?"
            + _SECRET_NOUN
            + r"\b",
            re.IGNORECASE,
        ),
        re.compile(r"\bwhat(\s+is|'s|s)\s+(the\s+|your\s+)" + _SECRET_NOUN + r"\b", re.IGNORECASE),
    ),
    "exfiltrate_data": (
        re.compile(
            r"\b(send|email|mail|post|upload|export|forward|transmit|copy|leak|sync|stream)\s+"
            r"(all\s+|any\s+)?(of\s+)?(this\s+|the\s+|these\s+|that\s+|my\s+|our\s+)?"
            r"(data|dataset|records|rows|table|file|spreadsheet|information)\s+"
            r"((to|into|onto)\s+(an?\s+|the\s+|my\s+|this\s+|that\s+)?"
            r"(external|outside|remote|third[\s-]party|unknown|public|personal|private"
            r"|attacker|own)\b"
            r"|externally\b|off[\s-]?site\b|outside\s+(the\s+)?(company|organi[sz]ation|network)\b)",
            re.IGNORECASE,
        ),
        re.compile(
            r"\b(exfiltrate|leak)\s+(all\s+)?(of\s+)?(the\s+|this\s+|these\s+)?"
            r"(data|dataset|records|rows|information)\b",
            re.IGNORECASE,
        ),
    ),
}

_TOKEN_RUN: Final[re.Pattern[str]] = re.compile(
    r"(?<![A-Za-z0-9+/=_-])[A-Za-z0-9+/=_-]{20,}(?![A-Za-z0-9+/=_-])"
)
_KNOWN_TOKEN: Final[re.Pattern[str]] = re.compile(
    r"\b(sk|pk|rk)-[A-Za-z0-9_-]{8,}|\bAKIA[0-9A-Z]{8,}|\bgh[pousr]_[A-Za-z0-9]{8,}"
    r"|\bxox[abpr]-[A-Za-z0-9-]{8,}"
)
_URL: Final[re.Pattern[str]] = re.compile(r"\bhttps?://\S+", re.IGNORECASE)
#: Bounded on purpose (RFC 5321 limits: 64 local part, 255 domain label run): the
#: lookbehind anchors each attempt at the start of a token, so a long run of
#: non-space characters is never rescanned from every position.
_EMAIL: Final[re.Pattern[str]] = re.compile(r"(?<![^\s@])[^\s@]{1,64}@[^\s@]{1,255}")
_REDACTION: Final[str] = "[redacted]"


def _normalize(value: str) -> str:
    """Normalize for matching: compatibility-normalize (NFKC, which folds
    full-width and other compatibility forms to plain letters), drop invisible
    format characters (zero-width and bidirectional controls, soft hyphen,
    byte-order mark), collapse whitespace runs to a single space and strip, then
    truncate to `_MAX_INSPECTED_LENGTH`. Case normalization is handled by
    `re.IGNORECASE` on every pattern. Homoglyphs from other scripts, leetspeak,
    encodings and words split by a space are deliberately **not** normalized: a
    documented limit of bounded literal matching."""
    folded = unicodedata.normalize("NFKC", value[:_MAX_RAW_LENGTH])
    visible = "".join(ch for ch in folded if unicodedata.category(ch) != "Cf")
    collapsed = re.sub(r"\s+", " ", visible).strip()
    return collapsed[:_MAX_INSPECTED_LENGTH]


def _family_matches(family: str, pattern: re.Pattern[str], normalized: str) -> re.Match[str] | None:
    match = pattern.search(normalized)
    if match is not None:
        return match
    for extended in _EXTENDED_PATTERNS.get(family, ()):
        match = extended.search(normalized)
        if match is not None:
            return match
    return None


def _matched_families(value: str) -> frozenset[str]:
    normalized = _normalize(value)
    if not normalized:
        return frozenset()
    return frozenset(
        family
        for family, pattern in _PATTERN_FAMILIES
        if _family_matches(family, pattern, normalized) is not None
    )


def _subtypes_of(families: frozenset[str]) -> frozenset[str]:
    return frozenset(_FAMILY_SUBTYPE.get(family, SUBTYPE_PROMPT_INJECTION) for family in families)


def _confidence_for(matched_families: frozenset[str]) -> float:
    """`docs/detector-framework.md` §12: "instruction-like content:
    confidence based on matched patterns, not intent." A new, disclosed,
    reversible design (no document fixes exact numbers): 0.6 for exactly
    one matched family (a coarser, more uncertain signal than any
    `1.0`-confidence `DET-02` detector's exact deterministic
    computation), 0.75 for two or more distinct matched families (a
    stronger, corroborating signal — still below `1.0` since this
    remains pattern matching, not an exact fact)."""
    return 0.75 if len(matched_families) >= 2 else 0.6


def _severity_for(
    matched_families: frozenset[str], security_exposure: SecurityExposureState
) -> Severity:
    """`docs/security-threat-model.md` §4's exposure-to-severity mapping,
    reusing `DET-01`'s existing `SecurityExposureState` exactly as-is."""
    heightened = bool(matched_families & _HEIGHTENED_FAMILIES)
    if security_exposure.sample_transmission_enabled:
        return Severity.CRITICAL if heightened else Severity.MEDIUM
    return Severity.HIGH if heightened else Severity.LOW


def _truncated_sample(value: str) -> str:
    """The bounded, redacted excerpt stored as evidence.

    Text after the first secret-request or exfiltration-request phrase is never
    kept: whatever follows such a request (a password, a destination, a token)
    is exactly the sensitive part. In **every** excerpt, whichever families
    matched, token-like strings, URLs and e-mail addresses are masked before the
    result is cut to `_TRUNCATED_SAMPLE_LENGTH`. A value with no secret or
    exfiltration phrase otherwise keeps the version 1 excerpt (its first
    characters). A short secret written in plain words (for example after "the
    password is") is not recognizable and is a documented limit."""
    normalized = _normalize(value)
    # The cut is the end of the *earliest-ending* heightened phrase over the base
    # **and every extended** pattern of both families, not the first pattern that
    # happens to match: an extended phrasing that comes first must cut first.
    ends = [
        match.end()
        for family, pattern in _PATTERN_FAMILIES
        if family in _FAMILY_SUBTYPE
        for candidate in (pattern, *_EXTENDED_PATTERNS.get(family, ()))
        if (match := candidate.search(normalized)) is not None
    ]
    kept = normalized[: min(ends)] if ends else normalized
    # Masking runs on every excerpt, before it is cut to length, so a token that
    # straddles the length bound is never stored as a recognizable fragment.
    for masker in (_URL, _EMAIL, _KNOWN_TOKEN, _TOKEN_RUN):
        kept = masker.sub(_REDACTION, kept)
    return kept[:_TRUNCATED_SAMPLE_LENGTH]


class PossiblePromptInjectionDetector:
    """`security.possible_llm_prompt_injection` — flags text-family
    column values containing bounded instruction-like patterns that
    could attempt to influence downstream LLM processing.

    One finding per column, aggregating every matched row.
    """

    metadata = DetectorMetadata(
        detector_id="security.possible_llm_prompt_injection",
        version="2",
        name="Possible LLM prompt injection",
        category=DetectorCategory.AI_PROCESSING_SECURITY,
        description=(
            "Flags text-family column values containing bounded instruction-like "
            "patterns that could attempt to influence downstream LLM processing."
        ),
        applicable_inferred_types=_TEXT_FAMILY_TYPES,
        required_profile_fields=("column_profiles[].inferred_type",),
        requires_raw_rows=True,
        requires_confirmed_context=False,
        default_configuration={},
        performance_class=PerformanceClass.LINEAR_BY_VALUE_LENGTH,
        documented_limitations=(
            "Bounded literal/regex pattern matching only, not semantic "
            "understanding; unusual phrasing or novel injection wording can be "
            "missed.",
            "May match legitimate discussion of prompt injection that happens to "
            "quote a matching phrase (e.g. security documentation); a disclosed, "
            "accepted false-positive class per docs/security-threat-model.md's own "
            "negative-control list.",
            "Restricted to text-family columns (TEXT/CATEGORICAL/IDENTIFIER); "
            "values in NUMERIC/DATE/BOOLEAN/MIXED/UNKNOWN columns are not scanned.",
            "Normalization is compatibility folding (NFKC) and removal of invisible format "
            "characters only; homoglyphs from other scripts, leetspeak, encodings (such as "
            "base64), reversed text and words split by a space are not detected, and a request "
            "split across cells is not combined.",
            "Evidence subtypes (prompt_injection, exfiltration_instruction, secret_request) "
            "label what was matched; they say nothing about intent. Text after a secret or "
            "exfiltration request is never stored, and token-like strings, URLs and e-mail "
            "addresses in every stored excerpt are masked; a short secret written in plain "
            "words (for example after 'the password is') is not recognizable and may remain "
            "in the excerpt.",
            "Severity reflects only the current SecurityExposureState "
            "(model-provider/sample-transmission enabled), not an actual "
            "per-analysis 'sent to model' or 'model output rejected' fact — those "
            "require a later orchestration package (AI-01/API-01) that assembles "
            "the full docs/domain-model.md §15 PromptInjectionRisk.",
        ),
    )
    config_schema: type[BaseModel] = _EmptyConfig

    def supports(self, request: DetectorSupportRequest) -> bool:
        del request  # Dataset-level, structurally always applicable.
        return True

    def run(self, request: DetectorRunRequest) -> DetectorRunResult:
        findings: list[FindingCandidate] = []
        evidence: list[Evidence] = []

        for profile in request.dataset_profile.column_profiles:
            if profile.inferred_type not in _TEXT_FAMILY_TYPES:
                continue

            affected_indices: list[int] = []
            column_matched_families: set[str] = set()
            subtype_row_counts: dict[str, int] = {}
            first_matched_value: str | None = None
            for index, row in enumerate(request.rows):
                value = row.get(profile.column.internal_key)
                if not isinstance(value, str) or not value:
                    continue
                matched = _matched_families(value)
                if not matched:
                    continue
                affected_indices.append(index)
                column_matched_families.update(matched)
                for subtype in _subtypes_of(matched):
                    subtype_row_counts[subtype] = subtype_row_counts.get(subtype, 0) + 1
                if first_matched_value is None:
                    first_matched_value = value

            if not affected_indices or first_matched_value is None:
                continue

            matched_families = frozenset(column_matched_families)
            confidence = _confidence_for(matched_families)
            severity = _severity_for(matched_families, request.security_exposure)
            affected_row_references = tuple(
                request.row_references[index] for index in affected_indices
            )

            evidence_id = (
                f"security.possible_llm_prompt_injection.evidence.{profile.column.internal_key}"
            )
            family_count = len(matched_families)
            risk_subtypes = tuple(s for s in RISK_SUBTYPES if s in subtype_row_counts)
            column_evidence = Evidence(
                evidence_id=evidence_id,
                evidence_type=EvidenceType.SECURITY_PATTERN,
                calculation_version="2",
                structured_payload={
                    "matched_pattern_categories": tuple(sorted(matched_families)),
                    "affected_row_count": len(affected_indices),
                    "truncated_sample_prefix": _truncated_sample(first_matched_value),
                    "risk_subtypes": risk_subtypes,
                    "subtype_row_counts": {s: subtype_row_counts[s] for s in risk_subtypes},
                },
                affected_columns=(profile.column,),
                affected_row_references=affected_row_references,
                scope=SamplingScope.FULL,
                display_safe_summary=(
                    f"Column '{profile.column.original_name}' has "
                    f"{len(affected_indices)} value(s) with possible instruction-like "
                    f"content matching {family_count} pattern "
                    f"categor{'y' if family_count == 1 else 'ies'} that could attempt "
                    "to influence downstream LLM processing "
                    f"(subtypes: {', '.join(risk_subtypes)})."
                ),
            )
            finding = FindingCandidate(
                detector_id=self.metadata.detector_id,
                detector_version=self.metadata.version,
                category=self.metadata.category,
                severity=severity,
                confidence=confidence,
                calculated_observation=(
                    f"Column '{profile.column.original_name}' has "
                    f"{len(affected_indices)} value(s) with possible instruction-like "
                    "content that could attempt to influence downstream LLM "
                    "processing (possible risk; not confirmed malicious intent)."
                ),
                affected_columns=(profile.column,),
                affected_row_references=affected_row_references,
                evidence_ids=(evidence_id,),
                default_remediation_template_key=None,
                default_validation_rule_template_key=None,
            )
            evidence.append(column_evidence)
            findings.append(finding)

        return DetectorRunResult(
            detector_id=self.metadata.detector_id,
            detector_version=self.metadata.version,
            status=DetectorRunStatus.SUCCESS,
            findings=tuple(findings),
            evidence=tuple(evidence),
            warnings=(),
            execution_metrics=ExecutionMetrics(duration_ms=0),
        )
