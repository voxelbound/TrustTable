"""Deterministic rule generation from findings (`RULE-02` slice 1,
`WP-080`).

`docs/implementation-backlog.md#RULE-02`: "Prefer deterministic mappings;
validate and execute before offering." For 9 of the 13 detector ids that
`explanation.guidance.build_deterministic_guidance` already proposes a
`rule_type` for (`ProposedValidationRule`, `AI-08`), this module derives
the *executable* parameters that proposal's `description` text alone
cannot carry — every value is read verbatim from the finding's own
already-computed `Evidence.structured_payload`, or is a fixed constant
the detector's own definition already implies (e.g. "non-negative" means
`minimum=0.0`). Nothing here performs a new calculation over raw rows,
and nothing here calls AI.

The remaining 4 categories are deliberately **not** mapped, because no
existing `RULE-01` rule type can faithfully represent the detector:

- `consistency.inconsistent_capitalization` /
  `statistical.suspiciously_constant_column`: the evidence never records
  which observed value is the intended canonical one, so no safe
  `accepted_values` list can be derived without guessing.
- `cross_field.line_total_mismatch`: the real check is multiplicative
  (`quantity x unit_price x (1 - discount_pct/100) x (1 + tax_pct/100)`);
  `RULE-01`'s only structurally similar type, `APPROXIMATE_EQUALITY`,
  checks an *additive* `total ~= sum(components)` condition
  (`rules.engine._run_approximate_equality`) — mapping onto it would
  silently generate a rule that fails almost every row for the wrong
  reason.
- `security.possible_llm_prompt_injection`: its 8 pattern families are
  matched case-insensitively and, combined, can exceed
  `domain.rules.MAX_REGEX_PATTERN_LENGTH` (200); `REGEX` rules carry no
  per-rule case-insensitivity flag, so reusing them would either exceed
  the limit or silently weaken the check.
- any detector id without a dedicated `explanation.guidance` template
  (the generic `CONDITIONAL_RULE` fallback): no real WHEN/THEN semantics
  exist to derive.

Framework-independent: no FastAPI/SQLAlchemy/pydantic/ai_boundary/
ai_provider import, no `eval`/`exec`. Stdlib only besides the domain,
detector-contract and guidance types.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date
from typing import Final

from ..detectors.contract import FindingCandidate
from ..domain.evidence import Evidence
from ..domain.explanation import ValidationRuleType
from ..domain.value_objects import ColumnReference
from ..explanation.guidance import build_deterministic_guidance

#: A bounded, non-backtracking pattern equivalent to
#: `consistency.leading_trailing_whitespace`'s own `value != value.strip()`
#: check: a match means leading or trailing whitespace is present.
_WHITESPACE_PATTERN: Final[str] = r"^\s|\s$"


@dataclass(frozen=True, slots=True)
class RuleProposalParameters:
    """The `ValidationRule` fields one detector-specific generator derives
    from a finding's own `Evidence`, beyond `rule_type`/`columns`/
    `description` (already supplied by `explanation.guidance`'s existing
    deterministic proposal). `columns`, when set, overrides the base
    proposal's columns (needed only for
    `structural.exact_duplicate_rows`, whose finding carries no
    `affected_columns` of its own — see `_generate_exact_duplicate_rows`).
    Every other field left `None` means that parameter does not apply."""

    columns: tuple[ColumnReference, ...] | None = None
    accepted_values: tuple[str, ...] | None = None
    minimum: float | None = None
    maximum: float | None = None
    minimum_date: date | None = None
    maximum_date: date | None = None
    pattern: str | None = None
    threshold_percentage: float | None = None
    tolerance: float | None = None


@dataclass(frozen=True, slots=True)
class RuleProposal:
    """One detector's deterministically generated candidate — not yet a
    `domain.rules.ValidationRule` (no `rule_id`/`severity`/`provenance`
    yet; those are the calling service's job, `analysis.service.
    generate_rule_proposal`)."""

    rule_type: ValidationRuleType
    columns: tuple[ColumnReference, ...]
    name: str
    description: str
    parameters: RuleProposalParameters


_Generator = Callable[
    [FindingCandidate, Mapping[str, Evidence], tuple[ColumnReference, ...]],
    RuleProposalParameters,
]


def _payload(
    finding: FindingCandidate, evidence_by_id: Mapping[str, Evidence]
) -> Mapping[str, object]:
    """The first evidence item's `structured_payload` — every generator in
    this module reads its detector's single evidence object, matching how
    each of these 9 detectors themselves each produce exactly one."""
    item = evidence_by_id[finding.evidence_ids[0]]
    return item.structured_payload


def _generate_exact_duplicate_rows(
    finding: FindingCandidate,
    evidence_by_id: Mapping[str, Evidence],
    all_columns: tuple[ColumnReference, ...],
) -> RuleProposalParameters:
    del finding, evidence_by_id
    # `structural.exact_duplicate_rows`'s own finding/evidence carry no
    # `affected_columns` (an exact duplicate is a whole-row condition) —
    # the composite key for `UNIQUE` is every one of the analysis's real
    # columns, read from the caller's own already-resolved column list,
    # never a fresh calculation.
    return RuleProposalParameters(columns=all_columns)


def _generate_no_extra_parameters(
    finding: FindingCandidate,
    evidence_by_id: Mapping[str, Evidence],
    all_columns: tuple[ColumnReference, ...],
) -> RuleProposalParameters:
    del finding, evidence_by_id, all_columns
    return RuleProposalParameters()


def _generate_excessive_missing_values(
    finding: FindingCandidate,
    evidence_by_id: Mapping[str, Evidence],
    all_columns: tuple[ColumnReference, ...],
) -> RuleProposalParameters:
    del all_columns
    ratio = _payload(finding, evidence_by_id)["missing_ratio"]
    assert isinstance(ratio, (int, float))
    return RuleProposalParameters(threshold_percentage=round(float(ratio) * 100, 1))


def _generate_future_dates(
    finding: FindingCandidate,
    evidence_by_id: Mapping[str, Evidence],
    all_columns: tuple[ColumnReference, ...],
) -> RuleProposalParameters:
    del all_columns
    reference_date = _payload(finding, evidence_by_id)["reference_date"]
    assert isinstance(reference_date, str)
    return RuleProposalParameters(maximum_date=date.fromisoformat(reference_date))


def _generate_non_negative(
    finding: FindingCandidate,
    evidence_by_id: Mapping[str, Evidence],
    all_columns: tuple[ColumnReference, ...],
) -> RuleProposalParameters:
    del finding, evidence_by_id, all_columns
    return RuleProposalParameters(minimum=0.0)


def _generate_valid_percentage(
    finding: FindingCandidate,
    evidence_by_id: Mapping[str, Evidence],
    all_columns: tuple[ColumnReference, ...],
) -> RuleProposalParameters:
    del finding, evidence_by_id, all_columns
    return RuleProposalParameters(minimum=0.0, maximum=100.0)


def _generate_extreme_outliers(
    finding: FindingCandidate,
    evidence_by_id: Mapping[str, Evidence],
    all_columns: tuple[ColumnReference, ...],
) -> RuleProposalParameters:
    del all_columns
    payload = _payload(finding, evidence_by_id)
    lower, upper = payload["lower_fence"], payload["upper_fence"]
    assert isinstance(lower, (int, float)) and isinstance(upper, (int, float))
    return RuleProposalParameters(minimum=float(lower), maximum=float(upper))


def _generate_leading_trailing_whitespace(
    finding: FindingCandidate,
    evidence_by_id: Mapping[str, Evidence],
    all_columns: tuple[ColumnReference, ...],
) -> RuleProposalParameters:
    del finding, evidence_by_id, all_columns
    return RuleProposalParameters(pattern=_WHITESPACE_PATTERN)


_GENERATORS: Final[dict[str, _Generator]] = {
    "structural.exact_duplicate_rows": _generate_exact_duplicate_rows,
    "structural.empty_column": _generate_no_extra_parameters,
    "completeness.excessive_missing_values": _generate_excessive_missing_values,
    "completeness.missing_likely_identifier": _generate_no_extra_parameters,
    "validity.future_dates": _generate_future_dates,
    "validity.negative_likely_non_negative_values": _generate_non_negative,
    "validity.invalid_percentages": _generate_valid_percentage,
    "statistical.extreme_outliers": _generate_extreme_outliers,
    "consistency.leading_trailing_whitespace": _generate_leading_trailing_whitespace,
}

#: Detector ids `RULE-02` slice 1 can generate a proposal for (used by
#: tests to prove full coverage of the disclosed 9-detector set, and to
#: prove every other `explanation.guidance` detector id is excluded).
GENERATABLE_DETECTOR_IDS: Final[frozenset[str]] = frozenset(_GENERATORS)


def generate_rule_proposal(
    finding: FindingCandidate,
    evidence: tuple[Evidence, ...],
    all_columns: tuple[ColumnReference, ...],
) -> tuple[RuleProposal | None, str | None]:
    """Return `(proposal, None)` when `finding.detector_id` is one of the
    9 supported detector ids, or `(None, reason)` otherwise. Every
    `RuleProposal` field is read verbatim from `finding`/`evidence`/
    `all_columns` — this function performs no new calculation over raw
    rows and never invents a value."""
    generator = _GENERATORS.get(finding.detector_id)
    if generator is None:
        return None, (
            f"No deterministic rule mapping exists for detector "
            f"{finding.detector_id!r}. RULE-02 slice 1 supports: "
            f"{', '.join(sorted(GENERATABLE_DETECTOR_IDS))}."
        )

    base = build_deterministic_guidance(finding).validation_rule
    evidence_by_id = {item.evidence_id: item for item in evidence}
    parameters = generator(finding, evidence_by_id, all_columns)
    columns = parameters.columns if parameters.columns is not None else base.columns

    return (
        RuleProposal(
            rule_type=base.rule_type,
            columns=columns,
            name=f"Generated rule for finding ({finding.detector_id})",
            description=base.description,
            parameters=parameters,
        ),
        None,
    )


__all__ = [
    "GENERATABLE_DETECTOR_IDS",
    "RuleProposal",
    "RuleProposalParameters",
    "generate_rule_proposal",
]
