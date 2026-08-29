"""Deterministic risk scoring (`RISK-01`), matching
`docs/product-requirements.md` §9's "Trust assessment" factor list and
§8.6's "deterministic priority score" `Finding` field.

Two independent, pure functions:

- `calculate_finding_priority_score(s)`: a per-finding `[0, 100]` score
  from a fixed severity base-weight table, scaled by confidence, plus
  capped affected-row-percentage and column-role bonuses.
- `calculate_trust_assessment`: a dataset-level `[0, 100]` score and one
  of four fixed `TrustLabel` values, computed from the per-finding
  priority scores, a "reinforcing findings" amplification (findings that
  share an affected column), and a fixed AI-processing-exposure penalty.

Neither function accepts any AI/LLM-shaped input (no `ai_boundary`
import anywhere in this module) — "AI cannot alter the score"
(`docs/product-requirements.md` §5.3) is a structural guarantee of the
function signatures, not a runtime check.

Framework-independent: no FastAPI/SQLAlchemy/pydantic import. Stdlib
only (`dataclasses`, `enum`).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Final

from ..detectors.contract import DetectorCategory, FindingCandidate, SecurityExposureState
from ..domain.value_objects import Severity
from ..profiling.schemas import DatasetProfile, InferredColumnType

_SEVERITY_BASE_WEIGHT: Final[dict[Severity, float]] = {
    Severity.CRITICAL: 100.0,
    Severity.HIGH: 75.0,
    Severity.MEDIUM: 50.0,
    Severity.LOW: 25.0,
    Severity.INFORMATIONAL: 10.0,
}
"""A new, disclosed, reversible severity base-weight table (no document
fixes exact numbers) — a simple, evenly-legible 0-100 scale matching
`Severity`'s own five-value ordering exactly. Scaled by
`finding.confidence` (a direct multiplicative factor, per
`docs/detector-framework.md` §12: "confidence reflects pattern
strength")."""

_ROW_PERCENTAGE_BONUS_MAX: Final[float] = 15.0
"""A finding's priority-score bonus for affecting a large fraction of
rows, linear in `len(affected_row_references) / population_size`, capped
at this value. A new, disclosed constant."""

_IDENTIFIER_DATE_BONUS: Final[float] = 10.0
"""Priority-score bonus when any affected column's `PROF-02`
`InferredColumnType` is `IDENTIFIER` or `DATE` — `docs/product-
requirements.md` §9's "identifier/date... impact" factor."""

_MONETARY_NAME_BONUS: Final[float] = 10.0
"""Priority-score bonus when any affected column's name matches
`_MONETARY_NAME_MARKERS` — `docs/product-requirements.md` §9's
"...monetary impact" factor. No confirmed column role (`CTX-01`) exists
yet, so this is a disclosed name heuristic, the same accepted-limitation
pattern already established by `detectors.validity.
_PERCENTAGE_NAME_MARKERS`."""

_MONETARY_NAME_MARKERS: Final[tuple[str, ...]] = (
    "price",
    "total",
    "amount",
    "cost",
    "revenue",
    "balance",
    "payment",
    "fee",
    "charge",
    "value",
)
"""Matches `unit_price`/`line_total` in the committed `demo-data/
sales_demo.csv` exactly. A disclosed, reversible heuristic; a
differently-named monetary column would be missed, and a coincidentally-
matching non-monetary column would be incorrectly bonused (both
disclosed limitations, same class as `_PERCENTAGE_NAME_MARKERS`)."""

_COLUMN_ROLE_BONUS_MAX: Final[float] = 15.0
"""Combined cap for the identifier/date bonus and the monetary-name
bonus together, even when both apply to the same finding."""

_SCORE_MIN: Final[float] = 0.0
_SCORE_MAX: Final[float] = 100.0

_DATASET_START_SCORE: Final[float] = 100.0
"""A dataset with zero findings starts at (and remains at) a perfect
trust score."""

_DATASET_DEDUCTION_FACTOR: Final[float] = 0.15
"""Each finding deducts `priority_score * _DATASET_DEDUCTION_FACTOR`
from the dataset-level trust score. A new, disclosed constant chosen so
a single `CRITICAL`-severity, full-confidence, full-row-coverage finding
alone (priority score `100`) deducts `15` points — landing at `85`,
inside "usable with caution" rather than "high confidence"."""

_REINFORCEMENT_MULTIPLIER: Final[float] = 1.3
"""A finding's dataset-level deduction is multiplied by this factor when
it shares at least one affected column (`ColumnReference.internal_key`
equality) with another finding in the same assessed set —
`docs/product-requirements.md` §9's "reinforcing findings" factor, a
disclosed interpretation of an otherwise-unspecified term."""

_AI_EXPOSURE_PENALTY: Final[float] = 10.0
"""A fixed, one-time (not per-finding) dataset-level deduction applied
when at least one `AI_PROCESSING_SECURITY`-category finding is present
together with `security_exposure.sample_transmission_enabled=True` —
`docs/product-requirements.md` §9's "AI-processing exposure for
instruction-like content" factor."""

_LABEL_HIGH_CONFIDENCE_MIN: Final[float] = 90.0
_LABEL_USABLE_WITH_CAUTION_MIN: Final[float] = 70.0
_LABEL_MATERIAL_CONCERNS_MIN: Final[float] = 40.0
"""Fixed, disclosed thresholds mapping the continuous `[0, 100]` dataset
score onto `docs/product-requirements.md` §9's four ordered labels. A
deliberately cautious calibration, reversible in a future package once
real usage data exists to recalibrate against."""


class TrustLabel(StrEnum):
    """Closed set of dataset trust-assessment labels
    (`docs/product-requirements.md` §9, exact wording)."""

    HIGH_CONFIDENCE = "high_confidence"
    USABLE_WITH_CAUTION = "usable_with_caution"
    MATERIAL_QUALITY_CONCERNS = "material_quality_concerns"
    NOT_RELIABLE_FOR_DECISION_MAKING = "not_reliable_for_decision_making"


@dataclass(frozen=True, slots=True)
class TrustAssessment:
    """The dataset-level output of `calculate_trust_assessment`.

    Fields:
        label: one of the four fixed `TrustLabel` values.
        score: the underlying `[0, 100]` numeric score the label was
            derived from.
        finding_count: the number of findings the assessment was
            computed from.
        highest_priority_score: the maximum per-finding priority score
            among the assessed findings, or `None` when `finding_count`
            is `0`.
    """

    label: TrustLabel
    score: float
    finding_count: int
    highest_priority_score: float | None

    def __post_init__(self) -> None:
        if not (_SCORE_MIN <= self.score <= _SCORE_MAX):
            raise ValueError("TrustAssessment.score must be between 0 and 100")
        if self.finding_count < 0:
            raise ValueError("TrustAssessment.finding_count must not be negative")
        if self.finding_count == 0 and self.highest_priority_score is not None:
            raise ValueError(
                "TrustAssessment.highest_priority_score must be None when finding_count is 0"
            )
        if self.finding_count > 0 and self.highest_priority_score is None:
            raise ValueError(
                "TrustAssessment.highest_priority_score must not be None when finding_count > 0"
            )


def _row_percentage_bonus(finding: FindingCandidate, dataset_profile: DatasetProfile) -> float:
    population_size = dataset_profile.sampling.population_size
    if population_size <= 0:
        return 0.0
    ratio = len(finding.affected_row_references) / population_size
    return min(_ROW_PERCENTAGE_BONUS_MAX, ratio * _ROW_PERCENTAGE_BONUS_MAX)


def _column_role_bonus(finding: FindingCandidate, dataset_profile: DatasetProfile) -> float:
    if not finding.affected_columns:
        return 0.0

    profile_by_key = {
        profile.column.internal_key: profile for profile in dataset_profile.column_profiles
    }
    has_identifier_or_date = False
    has_monetary_name = False
    for column in finding.affected_columns:
        profile = profile_by_key.get(column.internal_key)
        if profile is not None and profile.inferred_type in (
            InferredColumnType.IDENTIFIER,
            InferredColumnType.DATE,
        ):
            has_identifier_or_date = True
        lowered_name = column.original_name.lower()
        if any(marker in lowered_name for marker in _MONETARY_NAME_MARKERS):
            has_monetary_name = True

    bonus = 0.0
    if has_identifier_or_date:
        bonus += _IDENTIFIER_DATE_BONUS
    if has_monetary_name:
        bonus += _MONETARY_NAME_BONUS
    return min(_COLUMN_ROLE_BONUS_MAX, bonus)


def calculate_finding_priority_score(
    finding: FindingCandidate, *, dataset_profile: DatasetProfile
) -> float:
    """Compute one finding's deterministic priority score in `[0, 100]`.

    `severity` selects a fixed base weight, scaled by `confidence`, then
    a capped affected-row-percentage bonus and a capped column-role bonus
    are added, and the result is clamped to `[0, 100]`.
    """
    base = _SEVERITY_BASE_WEIGHT[finding.severity] * finding.confidence
    bonus = _row_percentage_bonus(finding, dataset_profile) + _column_role_bonus(
        finding, dataset_profile
    )
    return max(_SCORE_MIN, min(_SCORE_MAX, base + bonus))


def calculate_finding_priority_scores(
    findings: tuple[FindingCandidate, ...], *, dataset_profile: DatasetProfile
) -> tuple[float, ...]:
    """Compute priority scores for every finding, order-preserving,
    1:1 with `findings`."""
    return tuple(
        calculate_finding_priority_score(finding, dataset_profile=dataset_profile)
        for finding in findings
    )


def _label_for_score(score: float) -> TrustLabel:
    if score >= _LABEL_HIGH_CONFIDENCE_MIN:
        return TrustLabel.HIGH_CONFIDENCE
    if score >= _LABEL_USABLE_WITH_CAUTION_MIN:
        return TrustLabel.USABLE_WITH_CAUTION
    if score >= _LABEL_MATERIAL_CONCERNS_MIN:
        return TrustLabel.MATERIAL_QUALITY_CONCERNS
    return TrustLabel.NOT_RELIABLE_FOR_DECISION_MAKING


def _is_reinforced(finding: FindingCandidate, column_finding_counts: dict[str, int]) -> bool:
    return any(
        column_finding_counts.get(column.internal_key, 0) >= 2
        for column in finding.affected_columns
    )


def calculate_trust_assessment(
    findings: tuple[FindingCandidate, ...],
    priority_scores: tuple[float, ...],
    *,
    security_exposure: SecurityExposureState,
) -> TrustAssessment:
    """Compute the dataset-level `TrustAssessment` from `findings` and
    their already-computed `priority_scores` (same order, same length,
    e.g. from `calculate_finding_priority_scores`).

    Starts at a perfect `100.0`. Each finding deducts
    `priority_score * _DATASET_DEDUCTION_FACTOR`, amplified by
    `_REINFORCEMENT_MULTIPLIER` when the finding shares an affected
    column with another finding in the set ("reinforcing findings").
    A further fixed `_AI_EXPOSURE_PENALTY` is deducted once when an
    `AI_PROCESSING_SECURITY`-category finding is present together with
    `security_exposure.sample_transmission_enabled=True`. The result is
    clamped to `[0, 100]` and mapped to a `TrustLabel` via fixed
    thresholds.
    """
    if len(findings) != len(priority_scores):
        raise ValueError(
            "calculate_trust_assessment: findings and priority_scores must have the same length"
        )

    if not findings:
        return TrustAssessment(
            label=TrustLabel.HIGH_CONFIDENCE,
            score=_DATASET_START_SCORE,
            finding_count=0,
            highest_priority_score=None,
        )

    column_finding_counts: dict[str, int] = {}
    for finding in findings:
        for column in {column.internal_key: column for column in finding.affected_columns}:
            column_finding_counts[column] = column_finding_counts.get(column, 0) + 1

    total_deduction = 0.0
    for finding, priority_score in zip(findings, priority_scores, strict=True):
        deduction = priority_score * _DATASET_DEDUCTION_FACTOR
        if _is_reinforced(finding, column_finding_counts):
            deduction *= _REINFORCEMENT_MULTIPLIER
        total_deduction += deduction

    ai_exposure_penalty = 0.0
    if security_exposure.sample_transmission_enabled and any(
        finding.category is DetectorCategory.AI_PROCESSING_SECURITY for finding in findings
    ):
        ai_exposure_penalty = _AI_EXPOSURE_PENALTY

    raw_score = _DATASET_START_SCORE - total_deduction - ai_exposure_penalty
    final_score = max(_SCORE_MIN, min(_SCORE_MAX, raw_score))

    return TrustAssessment(
        label=_label_for_score(final_score),
        score=final_score,
        finding_count=len(findings),
        highest_priority_score=max(priority_scores),
    )
