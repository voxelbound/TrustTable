"""Tests for `explanation.deterministic` (`AI-05`, `WP-061`).

Covers AC-02 (deterministic narrative/provenance/grounding), AC-03
(no `ai_boundary`/`ai_provider` import, no `eval`/`exec`), and a real
end-to-end check against the committed `demo-data/sales_demo.csv`
(AC-12, deterministic half).
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path

from trusttable_backend.detectors.catalogue import DETECTORS
from trusttable_backend.detectors.contract import (
    DetectorCategory,
    FindingCandidate,
    SecurityExposureState,
)
from trusttable_backend.detectors.engine import run_detectors
from trusttable_backend.domain.value_objects import ColumnReference, Provenance, Severity
from trusttable_backend.explanation.deterministic import build_deterministic_explanation
from trusttable_backend.parsers.csv_parser import parse_csv
from trusttable_backend.profiling.metrics import compute_dataset_profile

REPO_ROOT = Path(__file__).resolve().parents[3]
DEMO_CSV_PATH = REPO_ROOT / "demo-data" / "sales_demo.csv"
ANALYSIS_TIMESTAMP = datetime(2026, 8, 24, tzinfo=UTC)


def make_finding(**overrides: object) -> FindingCandidate:
    fields: dict[str, object] = {
        "detector_id": "structural.exact_duplicate_rows",
        "detector_version": "1",
        "category": DetectorCategory.STRUCTURAL,
        "severity": Severity.MEDIUM,
        "confidence": 1.0,
        "calculated_observation": "2 rows are exact duplicates",
        "affected_columns": (),
        "affected_row_references": (),
        "evidence_ids": ("ev-1",),
        "default_remediation_template_key": None,
        "default_validation_rule_template_key": None,
    }
    fields.update(overrides)
    return FindingCandidate(**fields)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# AC-02: narrative/provenance/grounding
# ---------------------------------------------------------------------------


def test_deterministic_explanation_includes_calculated_observation() -> None:
    finding = make_finding(calculated_observation="2 rows are exact duplicates")

    explanation = build_deterministic_explanation(finding)

    assert "2 rows are exact duplicates" in explanation.narrative
    assert finding.detector_id in explanation.narrative


def test_deterministic_explanation_provenance_is_deterministic_fallback() -> None:
    explanation = build_deterministic_explanation(make_finding())

    assert explanation.provenance is Provenance.DETERMINISTIC_FALLBACK


def test_deterministic_explanation_provider_fields_are_none() -> None:
    explanation = build_deterministic_explanation(make_finding())

    assert explanation.provider_name is None
    assert explanation.model_identifier is None


def test_deterministic_explanation_grounding_mirrors_finding_exactly() -> None:
    column = ColumnReference(original_name="order_id", internal_key="order_id", ordinal=0)
    finding = make_finding(affected_columns=(column,), evidence_ids=("ev-1", "ev-2"))

    explanation = build_deterministic_explanation(finding)

    assert explanation.referenced_evidence_ids == ("ev-1", "ev-2")
    assert explanation.referenced_columns == (column,)


def test_deterministic_explanation_non_empty_and_severity_framed_for_every_severity() -> None:
    for severity in Severity:
        explanation = build_deterministic_explanation(make_finding(severity=severity))
        assert explanation.narrative != ""
        assert severity.value in explanation.narrative.lower()


# ---------------------------------------------------------------------------
# AC-03: structural proofs
# ---------------------------------------------------------------------------


def test_no_ai_boundary_or_ai_provider_import_in_deterministic_module() -> None:
    module_path = (
        REPO_ROOT / "backend" / "src" / "trusttable_backend" / "explanation" / "deterministic.py"
    )
    source = module_path.read_text(encoding="utf-8")
    import_lines = [line for line in source.splitlines() if line.startswith(("import ", "from "))]
    assert not any("ai_boundary" in line or "ai_provider" in line for line in import_lines)


def test_no_eval_or_exec_in_deterministic_module() -> None:
    module_path = (
        REPO_ROOT / "backend" / "src" / "trusttable_backend" / "explanation" / "deterministic.py"
    )
    source = module_path.read_text(encoding="utf-8")
    assert "eval(" not in source
    assert "exec(" not in source


# ---------------------------------------------------------------------------
# AC-12 (deterministic half): real end-to-end check
# ---------------------------------------------------------------------------


def test_real_demo_csv_deterministic_explanation_is_grounded() -> None:
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
        analysis_timestamp=ANALYSIS_TIMESTAMP,
    )
    findings = tuple(finding for result in results for finding in result.findings)
    assert findings, "committed demo dataset is expected to produce at least one finding"
    finding = findings[0]

    explanation = build_deterministic_explanation(finding)

    assert explanation.narrative
    assert finding.calculated_observation in explanation.narrative
    assert explanation.referenced_evidence_ids == finding.evidence_ids
    assert explanation.referenced_columns == finding.affected_columns
