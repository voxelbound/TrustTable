"""Tests for the deterministic built-in guidance (`AI-08`,
`docs/decision-log.md` D-040).

The guidance is what makes the four Finding Detail sections useful with AI
disabled or rejected, so it is tested for coverage of the *whole* detector
catalogue, for honesty (never a fact, never an active rule), and against the
real committed demo dataset.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from trusttable_backend.ai_boundary.claim_screen import screen_narrative
from trusttable_backend.detectors.catalogue import DETECTORS
from trusttable_backend.detectors.contract import (
    DetectorCategory,
    FindingCandidate,
    SecurityExposureState,
)
from trusttable_backend.detectors.engine import run_detectors
from trusttable_backend.domain.explanation import ImpactBasis, ValidationRuleType
from trusttable_backend.domain.value_objects import ColumnReference, Severity
from trusttable_backend.explanation.guidance import (
    GUIDED_DETECTOR_IDS,
    build_deterministic_guidance,
)
from trusttable_backend.parsers.csv_parser import parse_csv
from trusttable_backend.profiling.metrics import compute_dataset_profile

REPO_ROOT = Path(__file__).resolve().parents[3]
DEMO_CSV_PATH = REPO_ROOT / "demo-data" / "sales_demo.csv"


def col(name: str, ordinal: int = 0) -> ColumnReference:
    return ColumnReference(original_name=name, internal_key=name, ordinal=ordinal)


def finding_for(detector_id: str, columns: tuple[ColumnReference, ...] = ()) -> FindingCandidate:
    return FindingCandidate(
        detector_id=detector_id,
        detector_version="1",
        category=DetectorCategory.STRUCTURAL,
        severity=Severity.MEDIUM,
        confidence=1.0,
        calculated_observation="observation",
        affected_columns=columns,
        affected_row_references=(),
        evidence_ids=("ev-1", "ev-2"),
        default_remediation_template_key=None,
        default_validation_rule_template_key=None,
    )


ALL_DETECTOR_IDS = sorted(
    detector.metadata.detector_id for detector in DETECTORS
)  # the real registered catalogue


def test_the_table_covers_every_registered_detector_exactly() -> None:
    assert len(ALL_DETECTOR_IDS) == 13
    assert frozenset(ALL_DETECTOR_IDS) == GUIDED_DETECTOR_IDS


@pytest.mark.parametrize("detector_id", ALL_DETECTOR_IDS)
def test_every_detector_gets_non_empty_conditional_impact_remediation_and_a_proposed_rule(
    detector_id: str,
) -> None:
    columns = (col("quantity", 0), col("price", 1))
    guidance = build_deterministic_guidance(finding_for(detector_id, columns))

    assert guidance.business_impact
    for statement in guidance.business_impact:
        assert statement.statement
        # A template can never know a dataset's business use: every impact
        # statement is a conditional assumption, never a fact.
        assert statement.basis is ImpactBasis.ASSUMPTION
        assert statement.assumption
        assert statement.context_fields == ()
        assert statement.evidence_ids == ("ev-1", "ev-2")
    assert len(guidance.remediation) >= 1
    assert all(step.strip() for step in guidance.remediation)
    rule = guidance.validation_rule
    assert rule.rule_type in set(ValidationRuleType)
    assert rule.description
    assert rule.status == "proposed"
    assert set(rule.columns) <= set(columns)


@pytest.mark.parametrize("detector_id", ALL_DETECTOR_IDS)
def test_guidance_text_never_claims_data_was_changed_or_a_rule_is_active(
    detector_id: str,
) -> None:
    guidance = build_deterministic_guidance(finding_for(detector_id, (col("quantity"),)))
    texts = [*guidance.remediation, guidance.validation_rule.description]
    forbidden = re.compile(
        r"\b(?:has|have|was|were)\s+been\b|\bautomatically\b|\bis\s+(?:now\s+)?active\b|"
        r"\bwe\s+(?:fixed|removed|corrected)\b|\btrusttable\s+(?:will|has)\b",
        re.IGNORECASE,
    )
    for text in texts:
        assert not forbidden.search(text), text


@pytest.mark.parametrize("detector_id", ALL_DETECTOR_IDS)
def test_guidance_never_asserts_whole_dataset_quality_or_disregard_of_findings(
    detector_id: str,
) -> None:
    guidance = build_deterministic_guidance(finding_for(detector_id, (col("quantity"),)))
    texts = [
        *(item.statement for item in guidance.business_impact),
        *(item.assumption or "" for item in guidance.business_impact),
    ]
    for text in texts:
        assert not screen_narrative(text), text


def test_remediation_states_that_changes_belong_in_the_source_system() -> None:
    guidance = build_deterministic_guidance(finding_for("structural.exact_duplicate_rows"))
    assert any("source system" in step for step in guidance.remediation)
    assert any("never edits your file" in step for step in guidance.remediation)


def test_columns_are_named_from_the_finding_and_bounded() -> None:
    columns = tuple(col(f"c{i}", i) for i in range(6))
    guidance = build_deterministic_guidance(
        finding_for("completeness.excessive_missing_values", columns)
    )
    text = " ".join(guidance.remediation) + guidance.validation_rule.description
    assert "'c0'" in text and "'c1'" in text and "'c2'" in text
    assert "'c3'" not in text
    assert "other columns" in text
    assert guidance.validation_rule.columns == columns


def test_a_finding_without_columns_uses_a_neutral_phrase() -> None:
    guidance = build_deterministic_guidance(finding_for("structural.empty_column"))
    assert "the affected columns" in guidance.remediation[0]
    assert guidance.validation_rule.columns == ()


def test_untrusted_column_names_are_bounded_and_cannot_break_the_templates() -> None:
    hostile = col("{columns} {0} " + "x" * 500 + "}{", 0)
    guidance = build_deterministic_guidance(finding_for("structural.empty_column", (hostile,)))
    text = guidance.validation_rule.description
    assert "{columns}" in text  # substituted verbatim, never re-interpreted
    assert len(text) < 200


def test_an_unknown_detector_still_gets_honest_generic_guidance() -> None:
    guidance = build_deterministic_guidance(finding_for("future.new_detector", (col("qty"),)))
    assert guidance.business_impact[0].basis is ImpactBasis.ASSUMPTION
    assert guidance.remediation
    assert guidance.validation_rule.rule_type is ValidationRuleType.CONDITIONAL_RULE
    assert "'qty'" in guidance.validation_rule.description


def test_guidance_is_deterministic() -> None:
    finding = finding_for("validity.future_dates", (col("order_date"),))
    assert build_deterministic_guidance(finding) == build_deterministic_guidance(finding)


def test_the_module_imports_no_ai_boundary_provider_or_framework() -> None:
    source = (
        REPO_ROOT / "backend" / "src" / "trusttable_backend" / "explanation" / "guidance.py"
    ).read_text(encoding="utf-8")
    imports = [line for line in source.splitlines() if line.startswith(("import ", "from "))]
    joined = "\n".join(imports)
    for forbidden in ("ai_boundary", "ai_provider", "fastapi", "httpx", "pydantic", "sqlalchemy"):
        assert forbidden not in joined
    assert "eval(" not in source and "exec(" not in source


def test_every_real_demo_finding_gets_guidance_grounded_in_its_own_columns() -> None:
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
        security_exposure=SecurityExposureState(
            model_provider_enabled=False, sample_transmission_enabled=False
        ),
        analysis_timestamp=datetime(2026, 8, 24, tzinfo=UTC),
    )
    findings = [finding for result in results for finding in result.findings]
    assert len(findings) >= 10
    seen_detectors = {finding.detector_id for finding in findings}
    assert seen_detectors <= GUIDED_DETECTOR_IDS
    for finding in findings:
        guidance = build_deterministic_guidance(finding)
        assert guidance.business_impact and guidance.remediation
        assert set(guidance.validation_rule.columns) == set(finding.affected_columns)
