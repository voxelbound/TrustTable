"""Prompt-injection risk detector (`DET-SEC-01`), matching
`docs/detector-framework.md` §14's "Security detector" requirements:
bounded safe pattern matching across eight required pattern families,
case/whitespace normalization, length-limited inspection, negative
controls, exposure-aware severity, cautious wording, and row/column
evidence. Never executes or interprets matched text as an instruction
(`docs/product-requirements.md` §11, `docs/domain-model.md` §15) — this
module only reads and pattern-matches text; it contains no `eval`/`exec`
or other dynamic-code-execution of any scanned or matched value.

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


def _normalize(value: str) -> str:
    """Collapse whitespace runs to a single space and strip, then
    truncate to `_MAX_INSPECTED_LENGTH` before matching. Case
    normalization is handled by `re.IGNORECASE` on every pattern."""
    collapsed = re.sub(r"\s+", " ", value).strip()
    return collapsed[:_MAX_INSPECTED_LENGTH]


def _matched_families(value: str) -> frozenset[str]:
    normalized = _normalize(value)
    if not normalized:
        return frozenset()
    return frozenset(family for family, pattern in _PATTERN_FAMILIES if pattern.search(normalized))


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
    normalized = _normalize(value)
    return normalized[:_TRUNCATED_SAMPLE_LENGTH]


class PossiblePromptInjectionDetector:
    """`security.possible_llm_prompt_injection` — flags text-family
    column values containing bounded instruction-like patterns that
    could attempt to influence downstream LLM processing.

    One finding per column, aggregating every matched row.
    """

    metadata = DetectorMetadata(
        detector_id="security.possible_llm_prompt_injection",
        version="1",
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
            column_evidence = Evidence(
                evidence_id=evidence_id,
                evidence_type=EvidenceType.SECURITY_PATTERN,
                calculation_version="1",
                structured_payload={
                    "matched_pattern_categories": tuple(sorted(matched_families)),
                    "affected_row_count": len(affected_indices),
                    "truncated_sample_prefix": _truncated_sample(first_matched_value),
                },
                affected_columns=(profile.column,),
                affected_row_references=affected_row_references,
                scope=SamplingScope.FULL,
                display_safe_summary=(
                    f"Column '{profile.column.original_name}' has "
                    f"{len(affected_indices)} value(s) with possible instruction-like "
                    f"content matching {family_count} pattern "
                    f"categor{'y' if family_count == 1 else 'ies'} that could attempt "
                    "to influence downstream LLM processing."
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
