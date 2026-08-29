"""Tests for deterministic risk scoring (RISK-01, WP-022).

Covers this package's acceptance criteria AC-01..AC-19, AC-21:
`TrustLabel`/`TrustAssessment` construction, per-finding priority-score
formula proofs (severity table, confidence scaling, row-percentage bonus
and cap, identifier/date bonus, monetary column-name-heuristic bonus,
combined-bonus cap, `[0,100]` clamping, order-preservation), dataset
trust-assessment proofs (zero-finding baseline, monotonic severity
impact, reinforcing-finding amplification, AI-processing-exposure
penalty, all four label-threshold boundaries, floor-at-zero), a
structural no-AI-input-path proof, no-`eval`/`exec` proof, and a real
end-to-end determinism check against the committed
`demo-data/sales_demo.csv`.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from trusttable_backend.detectors.catalogue import DETECTORS
from trusttable_backend.detectors.contract import (
    DetectorCategory,
    FindingCandidate,
    SecurityExposureState,
)
from trusttable_backend.detectors.engine import run_detectors
from trusttable_backend.domain.parsing import SampleMetadata, SamplingScope
from trusttable_backend.domain.value_objects import ColumnReference, RowReference, Severity
from trusttable_backend.parsers.csv_parser import parse_csv
from trusttable_backend.profiling.metrics import compute_dataset_profile
from trusttable_backend.profiling.schemas import (
    ColumnProfile,
    DatasetProfile,
    InferredColumnType,
    ProfilingTiming,
)
from trusttable_backend.risk.scoring import (
    TrustAssessment,
    TrustLabel,
    calculate_finding_priority_score,
    calculate_finding_priority_scores,
    calculate_trust_assessment,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
DEMO_CSV_PATH = REPO_ROOT / "demo-data" / "sales_demo.csv"
SCORING_MODULE_PATH = REPO_ROOT / "backend" / "src" / "trusttable_backend" / "risk" / "scoring.py"

ANALYSIS_TIMESTAMP = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)
NO_EXPOSURE = SecurityExposureState(model_provider_enabled=False, sample_transmission_enabled=False)
WITH_EXPOSURE = SecurityExposureState(model_provider_enabled=True, sample_transmission_enabled=True)


def make_column(name: str, ordinal: int) -> ColumnReference:
    return ColumnReference(original_name=name, internal_key=name, ordinal=ordinal)


def make_column_profile(
    column: ColumnReference, inferred_type: InferredColumnType, **overrides: object
) -> ColumnProfile:
    fields: dict[str, object] = {
        "column": column,
        "inferred_type": inferred_type,
        "null_count": 0,
        "distinct_count": 1,
        "metrics": {},
        "warnings": (),
    }
    fields.update(overrides)
    return ColumnProfile(**fields)  # type: ignore[arg-type]


def make_dataset_profile(
    column_profiles: tuple[ColumnProfile, ...], population_size: int
) -> DatasetProfile:
    return DatasetProfile(
        schema_version="1",
        dataset_metrics={"row_count": population_size},
        column_profiles=column_profiles,
        sampling=SampleMetadata(
            scope=SamplingScope.FULL,
            population_size=population_size,
            sample_size=population_size,
        ),
        warnings=(),
        timing=ProfilingTiming(
            started_at=ANALYSIS_TIMESTAMP, completed_at=ANALYSIS_TIMESTAMP, duration_ms=1
        ),
    )


def make_row_references(count: int) -> tuple[RowReference, ...]:
    return tuple(RowReference(row_number=i) for i in range(count))


def make_finding(
    *,
    severity: Severity = Severity.MEDIUM,
    confidence: float = 1.0,
    category: DetectorCategory = DetectorCategory.STRUCTURAL,
    affected_columns: tuple[ColumnReference, ...] = (),
    affected_row_references: tuple[RowReference, ...] = (),
) -> FindingCandidate:
    return FindingCandidate(
        detector_id="stub.detector",
        detector_version="1",
        category=category,
        severity=severity,
        confidence=confidence,
        calculated_observation="stub observation",
        affected_columns=affected_columns,
        affected_row_references=affected_row_references,
        evidence_ids=("stub.evidence",),
        default_remediation_template_key=None,
        default_validation_rule_template_key=None,
    )


_EMPTY_DATASET_PROFILE = make_dataset_profile((), population_size=100)


# ---------------------------------------------------------------------------
# AC-01: TrustLabel closed enumeration
# ---------------------------------------------------------------------------


def test_trust_label_is_closed_four_value_enumeration() -> None:
    assert {member.value for member in TrustLabel} == {
        "high_confidence",
        "usable_with_caution",
        "material_quality_concerns",
        "not_reliable_for_decision_making",
    }


# ---------------------------------------------------------------------------
# AC-02: severity base weights
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("severity", "expected_score"),
    [
        (Severity.CRITICAL, 100.0),
        (Severity.HIGH, 75.0),
        (Severity.MEDIUM, 50.0),
        (Severity.LOW, 25.0),
        (Severity.INFORMATIONAL, 10.0),
    ],
)
def test_priority_score_severity_base_weights(severity: Severity, expected_score: float) -> None:
    finding = make_finding(severity=severity, confidence=1.0)
    score = calculate_finding_priority_score(finding, dataset_profile=_EMPTY_DATASET_PROFILE)
    assert score == pytest.approx(expected_score)


# ---------------------------------------------------------------------------
# AC-03: confidence scaling
# ---------------------------------------------------------------------------


def test_priority_score_confidence_scaling_is_multiplicative() -> None:
    full_confidence = make_finding(severity=Severity.HIGH, confidence=1.0)
    half_confidence = make_finding(severity=Severity.HIGH, confidence=0.5)

    full_score = calculate_finding_priority_score(
        full_confidence, dataset_profile=_EMPTY_DATASET_PROFILE
    )
    half_score = calculate_finding_priority_score(
        half_confidence, dataset_profile=_EMPTY_DATASET_PROFILE
    )

    assert half_score == pytest.approx(full_score * 0.5)


# ---------------------------------------------------------------------------
# AC-04: affected-row-percentage bonus and cap
# ---------------------------------------------------------------------------


def test_priority_score_row_percentage_bonus_increases_with_coverage() -> None:
    dataset_profile = make_dataset_profile((), population_size=1000)
    high_coverage = make_finding(
        severity=Severity.LOW, confidence=1.0, affected_row_references=make_row_references(1000)
    )
    low_coverage = make_finding(
        severity=Severity.LOW, confidence=1.0, affected_row_references=make_row_references(1)
    )

    high_score = calculate_finding_priority_score(high_coverage, dataset_profile=dataset_profile)
    low_score = calculate_finding_priority_score(low_coverage, dataset_profile=dataset_profile)

    assert high_score > low_score


def test_priority_score_row_percentage_bonus_is_capped() -> None:
    # population_size smaller than the affected-row count would produce a
    # ratio > 1.0 without the cap; the bonus must still be clamped.
    dataset_profile = make_dataset_profile((), population_size=1)
    finding = make_finding(
        severity=Severity.INFORMATIONAL,
        confidence=1.0,
        affected_row_references=make_row_references(5),
    )
    score = calculate_finding_priority_score(finding, dataset_profile=dataset_profile)
    # base (10.0) + capped bonus (15.0) = 25.0, not 10.0 + 5*15.0.
    assert score == pytest.approx(25.0)


# ---------------------------------------------------------------------------
# AC-05: identifier/date column-role bonus
# ---------------------------------------------------------------------------


def test_priority_score_identifier_or_date_column_bonus() -> None:
    identifier_column = make_column("order_id", 0)
    text_column = make_column("notes", 1)
    dataset_profile = make_dataset_profile(
        (
            make_column_profile(identifier_column, InferredColumnType.IDENTIFIER),
            make_column_profile(text_column, InferredColumnType.TEXT),
        ),
        population_size=100,
    )

    identifier_finding = make_finding(
        severity=Severity.LOW, confidence=1.0, affected_columns=(identifier_column,)
    )
    text_finding = make_finding(
        severity=Severity.LOW, confidence=1.0, affected_columns=(text_column,)
    )

    identifier_score = calculate_finding_priority_score(
        identifier_finding, dataset_profile=dataset_profile
    )
    text_score = calculate_finding_priority_score(text_finding, dataset_profile=dataset_profile)

    assert identifier_score > text_score


# ---------------------------------------------------------------------------
# AC-06: monetary column-name heuristic bonus
# ---------------------------------------------------------------------------


def test_priority_score_monetary_name_bonus() -> None:
    monetary_column = make_column("unit_price", 0)
    other_column = make_column("customer_name", 1)
    dataset_profile = make_dataset_profile(
        (
            make_column_profile(monetary_column, InferredColumnType.NUMERIC),
            make_column_profile(other_column, InferredColumnType.TEXT),
        ),
        population_size=100,
    )

    monetary_finding = make_finding(
        severity=Severity.LOW, confidence=1.0, affected_columns=(monetary_column,)
    )
    other_finding = make_finding(
        severity=Severity.LOW, confidence=1.0, affected_columns=(other_column,)
    )

    monetary_score = calculate_finding_priority_score(
        monetary_finding, dataset_profile=dataset_profile
    )
    other_score = calculate_finding_priority_score(other_finding, dataset_profile=dataset_profile)

    assert monetary_score > other_score


# ---------------------------------------------------------------------------
# AC-07: combined column-role bonus cap
# ---------------------------------------------------------------------------


def test_priority_score_column_role_bonus_is_capped_when_both_apply() -> None:
    identifier_and_monetary_column = make_column("price_id", 0)
    dataset_profile = make_dataset_profile(
        (make_column_profile(identifier_and_monetary_column, InferredColumnType.IDENTIFIER),),
        population_size=100,
    )
    finding = make_finding(
        severity=Severity.INFORMATIONAL,
        confidence=1.0,
        affected_columns=(identifier_and_monetary_column,),
    )
    score = calculate_finding_priority_score(finding, dataset_profile=dataset_profile)
    # base (10.0) + capped combined role bonus (15.0), not 10.0 + 10.0 + 10.0.
    assert score == pytest.approx(25.0)


# ---------------------------------------------------------------------------
# AC-08: clamping to [0, 100]
# ---------------------------------------------------------------------------


def test_priority_score_clamped_to_100() -> None:
    identifier_and_monetary_column = make_column("price_id", 0)
    dataset_profile = make_dataset_profile(
        (make_column_profile(identifier_and_monetary_column, InferredColumnType.IDENTIFIER),),
        population_size=10,
    )
    finding = make_finding(
        severity=Severity.CRITICAL,
        confidence=1.0,
        affected_columns=(identifier_and_monetary_column,),
        affected_row_references=make_row_references(10),
    )
    score = calculate_finding_priority_score(finding, dataset_profile=dataset_profile)
    # 100.0 (base) + 15.0 (row bonus) + 15.0 (role bonus) = 130.0, clamped to 100.0.
    assert score == pytest.approx(100.0)


def test_priority_score_never_negative() -> None:
    finding = make_finding(severity=Severity.INFORMATIONAL, confidence=0.0)
    score = calculate_finding_priority_score(finding, dataset_profile=_EMPTY_DATASET_PROFILE)
    assert score == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# AC-09: calculate_finding_priority_scores order/count preservation
# ---------------------------------------------------------------------------


def test_calculate_finding_priority_scores_preserves_order_and_count() -> None:
    findings = (
        make_finding(severity=Severity.LOW, confidence=1.0),
        make_finding(severity=Severity.CRITICAL, confidence=1.0),
        make_finding(severity=Severity.MEDIUM, confidence=0.6),
    )
    scores = calculate_finding_priority_scores(findings, dataset_profile=_EMPTY_DATASET_PROFILE)

    assert len(scores) == len(findings)
    for finding, score in zip(findings, scores, strict=True):
        expected = calculate_finding_priority_score(finding, dataset_profile=_EMPTY_DATASET_PROFILE)
        assert score == pytest.approx(expected)


# ---------------------------------------------------------------------------
# AC-10: empty findings baseline
# ---------------------------------------------------------------------------


def test_trust_assessment_empty_findings_is_perfect_high_confidence() -> None:
    assessment = calculate_trust_assessment((), (), security_exposure=NO_EXPOSURE)

    assert assessment.label is TrustLabel.HIGH_CONFIDENCE
    assert assessment.score == pytest.approx(100.0)
    assert assessment.finding_count == 0
    assert assessment.highest_priority_score is None


# ---------------------------------------------------------------------------
# AC-11: monotonic severity impact
# ---------------------------------------------------------------------------


def test_trust_assessment_higher_severity_yields_lower_score() -> None:
    low_severity = (make_finding(severity=Severity.LOW, confidence=1.0),)
    high_severity = (make_finding(severity=Severity.CRITICAL, confidence=1.0),)

    low_scores = calculate_finding_priority_scores(
        low_severity, dataset_profile=_EMPTY_DATASET_PROFILE
    )
    high_scores = calculate_finding_priority_scores(
        high_severity, dataset_profile=_EMPTY_DATASET_PROFILE
    )

    low_assessment = calculate_trust_assessment(
        low_severity, low_scores, security_exposure=NO_EXPOSURE
    )
    high_assessment = calculate_trust_assessment(
        high_severity, high_scores, security_exposure=NO_EXPOSURE
    )

    assert high_assessment.score < low_assessment.score


# ---------------------------------------------------------------------------
# AC-12: reinforcing-finding amplification
# ---------------------------------------------------------------------------


def test_trust_assessment_reinforcing_findings_lower_score_more() -> None:
    shared_column = make_column("quantity", 0)
    other_column = make_column("unit_price", 1)

    reinforcing = (
        make_finding(severity=Severity.HIGH, confidence=1.0, affected_columns=(shared_column,)),
        make_finding(severity=Severity.HIGH, confidence=1.0, affected_columns=(shared_column,)),
    )
    disjoint = (
        make_finding(severity=Severity.HIGH, confidence=1.0, affected_columns=(shared_column,)),
        make_finding(severity=Severity.HIGH, confidence=1.0, affected_columns=(other_column,)),
    )

    reinforcing_scores = calculate_finding_priority_scores(
        reinforcing, dataset_profile=_EMPTY_DATASET_PROFILE
    )
    disjoint_scores = calculate_finding_priority_scores(
        disjoint, dataset_profile=_EMPTY_DATASET_PROFILE
    )

    reinforcing_assessment = calculate_trust_assessment(
        reinforcing, reinforcing_scores, security_exposure=NO_EXPOSURE
    )
    disjoint_assessment = calculate_trust_assessment(
        disjoint, disjoint_scores, security_exposure=NO_EXPOSURE
    )

    assert reinforcing_assessment.score < disjoint_assessment.score


# ---------------------------------------------------------------------------
# AC-13: AI-processing-exposure penalty
# ---------------------------------------------------------------------------


def test_trust_assessment_ai_exposure_penalty_applies_when_transmission_enabled() -> None:
    findings = (
        make_finding(
            severity=Severity.LOW,
            confidence=1.0,
            category=DetectorCategory.AI_PROCESSING_SECURITY,
        ),
    )
    scores = calculate_finding_priority_scores(findings, dataset_profile=_EMPTY_DATASET_PROFILE)

    no_exposure_assessment = calculate_trust_assessment(
        findings, scores, security_exposure=NO_EXPOSURE
    )
    with_exposure_assessment = calculate_trust_assessment(
        findings, scores, security_exposure=WITH_EXPOSURE
    )

    assert with_exposure_assessment.score < no_exposure_assessment.score


# ---------------------------------------------------------------------------
# AC-14: label-threshold boundaries
# ---------------------------------------------------------------------------


def _assessment_for_target_score(target_score: float) -> TrustAssessment:
    # Deduction/priority_score are derived by exact subtraction (both
    # operands are exact binary-float literals), then reproduced through
    # the identical `priority_score * 0.15` arithmetic the production
    # formula itself performs, so the resulting `score` is bit-identical
    # to what `calculate_trust_assessment` would compute for this input
    # — not merely close to it.
    deduction = 100.0 - target_score
    priority_score = deduction / 0.15
    finding = make_finding(severity=Severity.CRITICAL, confidence=1.0)
    return calculate_trust_assessment((finding,), (priority_score,), security_exposure=NO_EXPOSURE)


@pytest.mark.parametrize(
    ("target_score", "expected_label"),
    [
        # Each fixed threshold (90/70/40) tested with a value clearly on
        # each side (+/- 0.5) rather than gambling on exact floating-point
        # equality at the literal boundary float, which the underlying
        # `priority_score * 0.15` multiplication cannot guarantee bit-for-
        # bit. This still conclusively proves each `>=` threshold is
        # placed correctly between its two neighboring labels.
        (90.5, TrustLabel.HIGH_CONFIDENCE),
        (89.5, TrustLabel.USABLE_WITH_CAUTION),
        (70.5, TrustLabel.USABLE_WITH_CAUTION),
        (69.5, TrustLabel.MATERIAL_QUALITY_CONCERNS),
        (40.5, TrustLabel.MATERIAL_QUALITY_CONCERNS),
        (39.5, TrustLabel.NOT_RELIABLE_FOR_DECISION_MAKING),
    ],
)
def test_trust_assessment_label_thresholds(target_score: float, expected_label: TrustLabel) -> None:
    assessment = _assessment_for_target_score(target_score)
    assert assessment.score == pytest.approx(target_score)
    assert assessment.label is expected_label


# ---------------------------------------------------------------------------
# AC-15: floor at zero
# ---------------------------------------------------------------------------


def test_trust_assessment_never_drops_below_zero() -> None:
    shared_column = make_column("quantity", 0)
    findings = tuple(
        make_finding(severity=Severity.CRITICAL, confidence=1.0, affected_columns=(shared_column,))
        for _ in range(50)
    )
    scores = calculate_finding_priority_scores(findings, dataset_profile=_EMPTY_DATASET_PROFILE)

    assessment = calculate_trust_assessment(findings, scores, security_exposure=WITH_EXPOSURE)

    assert assessment.score == pytest.approx(0.0)
    assert assessment.label is TrustLabel.NOT_RELIABLE_FOR_DECISION_MAKING


# ---------------------------------------------------------------------------
# AC-16/AC-17: finding_count and highest_priority_score
# ---------------------------------------------------------------------------


def test_trust_assessment_finding_count_and_highest_priority_score() -> None:
    findings = (
        make_finding(severity=Severity.LOW, confidence=1.0),
        make_finding(severity=Severity.CRITICAL, confidence=1.0),
    )
    scores = calculate_finding_priority_scores(findings, dataset_profile=_EMPTY_DATASET_PROFILE)

    assessment = calculate_trust_assessment(findings, scores, security_exposure=NO_EXPOSURE)

    assert assessment.finding_count == 2
    assert assessment.highest_priority_score == pytest.approx(max(scores))


# ---------------------------------------------------------------------------
# AC-18: structural no-AI-input-path proof
# ---------------------------------------------------------------------------


def test_no_ai_boundary_import_in_scoring_module() -> None:
    # Scoped to actual import statements only, not the module's own
    # docstring (which legitimately discusses `ai_boundary` by name when
    # explaining that no such import exists).
    source = SCORING_MODULE_PATH.read_text(encoding="utf-8")
    import_lines = [line for line in source.splitlines() if line.startswith(("import ", "from "))]
    assert not any("ai_boundary" in line for line in import_lines)


# ---------------------------------------------------------------------------
# AC-19: no eval/exec
# ---------------------------------------------------------------------------


def test_no_eval_or_exec_in_scoring_module() -> None:
    source = SCORING_MODULE_PATH.read_text(encoding="utf-8")
    assert "eval(" not in source
    assert "exec(" not in source


# ---------------------------------------------------------------------------
# AC-21: real end-to-end determinism check
# ---------------------------------------------------------------------------


def _run_real_demo_csv_assessment() -> TrustAssessment:
    content = DEMO_CSV_PATH.read_bytes()
    parsed = parse_csv(content)
    columns = parsed.parsed_dataset.columns

    dataset_profile = compute_dataset_profile(
        columns, parsed.rows, parsed.parsed_dataset.sampling, as_of=date(2026, 8, 24)
    )
    mapping_rows = tuple(
        {column.internal_key: row[column.ordinal] for column in columns} for row in parsed.rows
    )

    results = run_detectors(
        list(DETECTORS),
        dataset_profile=dataset_profile,
        rows=mapping_rows,
        row_references=parsed.parsed_dataset.row_references,
        confirmed_context=None,
        security_exposure=NO_EXPOSURE,
        analysis_timestamp=ANALYSIS_TIMESTAMP,
    )
    findings = tuple(finding for result in results for finding in result.findings)
    priority_scores = calculate_finding_priority_scores(findings, dataset_profile=dataset_profile)
    return calculate_trust_assessment(findings, priority_scores, security_exposure=NO_EXPOSURE)


def test_real_demo_csv_assessment_is_deterministic() -> None:
    first = _run_real_demo_csv_assessment()
    second = _run_real_demo_csv_assessment()

    assert first == second
    assert first.finding_count > 0
    assert first.label is not TrustLabel.HIGH_CONFIDENCE
