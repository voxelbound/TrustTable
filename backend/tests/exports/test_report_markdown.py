"""Behavioural proof for the Markdown report renderer (`EXP-01` slice 2).

The security-section tests vary each recorded input and assert the
wording changes with it: a fixed reassuring template would pass a
snapshot test but fail these.
"""

from __future__ import annotations

import ast
import re
from dataclasses import FrozenInstanceError, replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from trusttable_backend.analysis.service import (
    Analysis,
    AnalysisStore,
    create_analysis,
    run_analysis,
)
from trusttable_backend.detectors.contract import DetectorCategory, SecurityExposureState
from trusttable_backend.domain.explanation import ValidationRuleType
from trusttable_backend.domain.review import FindingReview, FindingReviewState
from trusttable_backend.domain.rules import RuleExecutionResult, ValidationRule
from trusttable_backend.domain.value_objects import ColumnReference, Severity
from trusttable_backend.exports.report_build import build_report_snapshot
from trusttable_backend.exports.report_markdown import ReportNotAvailableError, render_markdown
from trusttable_backend.exports.report_markdown import _md as _md_of
from trusttable_backend.exports.report_snapshot import (
    MAX_EXAMPLE_ROWS,
    AiEnrichmentDisclosure,
    ModelLocation,
    ReportOptions,
    ReportSnapshot,
    ReportVersions,
)

_NOW = datetime(2026, 9, 29, 12, 0, tzinfo=UTC)
_VERSIONS = ReportVersions(
    application_version="9.9.9",
    detector_versions=(("zeta.detector", "2"), ("alpha.detector", "1")),
    prompt_version="prompt-v7",
    model_name="local-model-x",
)
_GOLDEN = Path(__file__).parent / "golden" / "demo_report.md"
_EXPORTS = Path(__file__).parents[2] / "src" / "trusttable_backend" / "exports"
_REPORT_MODULES = ("report_snapshot.py", "report_markdown.py", "report_build.py")
_HEADINGS = [
    "# Data quality report",
    "## Dataset summary",
    "## Trust assessment",
    "## Confirmed context",
    "## Priority findings",
    "## Review decisions",
    "## Recommendations",
    "## Validation rules",
    "## AI-processing security",
    "## Methodology and limitations",
    "## Versions",
]


def _completed() -> Analysis:
    store = AnalysisStore()
    created = create_analysis(store)
    return run_analysis(store, created.analysis_id, now=_NOW)


def _render(
    analysis: Analysis,
    *,
    options: ReportOptions | None = None,
    disclosure: AiEnrichmentDisclosure | None = None,
) -> str:
    return render_markdown(
        analysis,
        options=options or ReportOptions(),
        versions=_VERSIONS,
        ai_enrichment=disclosure,
    )


def _section(markdown: str, heading: str) -> str:
    start = markdown.index(heading)
    following = re.search(r"^## ", markdown[start + len(heading) :], re.MULTILINE)
    end = start + len(heading) + following.start() if following else len(markdown)
    return markdown[start:end]


def _disclosure(**overrides: object) -> AiEnrichmentDisclosure:
    base = AiEnrichmentDisclosure(
        accepted_count=2,
        rejected_count=1,
        provider_error_count=0,
        evidence_sent_to_model=True,
        confirmed_context_sent_to_model=False,
        model_location=ModelLocation.LOCAL,
        protections=("Output validated against a fixed schema",),
    )
    return replace(base, **overrides)  # type: ignore[arg-type]


def _review(index: int, state: FindingReviewState, **kwargs: object) -> FindingReview:
    return FindingReview(
        finding_id=str(index),
        state=state,
        note=kwargs.get("note"),  # type: ignore[arg-type]
        dismissal_reason=kwargs.get("dismissal_reason"),  # type: ignore[arg-type]
        reviewed_at=_NOW,
    )


def test_every_section_is_rendered_in_fixed_order() -> None:
    markdown = _render(_completed())

    positions = [markdown.index(heading) for heading in _HEADINGS]
    assert positions == sorted(positions)
    assert "## Technical appendix" not in markdown


def test_output_matches_the_committed_golden_report_for_the_demo_analysis() -> None:
    analysis = replace(_completed(), analysis_id="demo-analysis")

    assert _render(analysis) == _GOLDEN.read_text(encoding="utf-8")


def test_findings_are_bullets_so_displayed_ids_match_finding_references() -> None:
    markdown = _render(_completed())

    assert not [line for line in markdown.splitlines() if re.match(r"^\d+\. ", line)]
    assert "- **Finding 15**" in markdown


def test_dataset_values_quoted_by_detector_observations_are_withheld_by_default() -> None:
    analysis = _completed()
    quoting = [
        finding.calculated_observation
        for finding in analysis.findings
        if "OFFICE SUPPLIES" in finding.calculated_observation
    ]
    assert quoting, "the demo dataset is expected to quote a raw value in an observation"

    default = _render(analysis)
    examples = _render(analysis, options=ReportOptions(include_bounded_examples=True))

    for finding in analysis.findings:
        assert finding.calculated_observation not in default
        assert _md_of(finding.calculated_observation) in examples
    assert "OFFICE SUPPLIES" not in default
    assert "OFFICE SUPPLIES" in examples
    assert "request bounded examples to include them" in default


def test_rendering_is_byte_identical_and_snapshot_is_immutable() -> None:
    analysis = _completed()

    first = build_report_snapshot(analysis, report_id="r1", generated_at=_NOW, versions=_VERSIONS)
    second = build_report_snapshot(
        analysis, report_id="r2", generated_at=datetime(2030, 1, 1, tzinfo=UTC), versions=_VERSIONS
    )

    assert first.markdown == second.markdown
    assert first.content_sha256 == second.content_sha256
    with pytest.raises(FrozenInstanceError):
        first.markdown = "tampered"  # type: ignore[misc]
    with pytest.raises(ValueError, match="content_sha256"):
        ReportSnapshot(
            report_id="r",
            analysis_id="a",
            generated_at=_NOW,
            options=ReportOptions(),
            schema_version="1",
            markdown="edited",
            content_sha256=first.content_sha256,
        )


def test_an_analysis_that_is_not_completed_cannot_be_reported() -> None:
    queued = create_analysis(AnalysisStore())

    with pytest.raises(ReportNotAvailableError):
        _render(queued)


def test_the_report_never_reads_raw_dataset_content() -> None:
    analysis = _completed()
    canary = replace(analysis, content=b"CANARY-RAW-CELL-VALUE,1,2\n")

    assert _render(canary) == _render(analysis)
    assert "CANARY-RAW-CELL-VALUE" not in _render(canary)


def test_hostile_text_is_escaped_and_cannot_inject_markup() -> None:
    analysis = _completed()
    hostile = replace(
        analysis.dataset, original_filename="<script>alert(1)</script> | `x` [l](http://e)"
    )
    markdown = _render(replace(analysis, dataset=hostile))

    title = markdown.splitlines()[0]
    assert "<script>" not in title
    assert "\\<script\\>" in title
    assert "\\`x\\`" in title


def test_no_recorded_ai_enrichment_is_stated_as_unrecorded_never_as_absent() -> None:
    section = _section(_render(_completed()), "## AI-processing security")

    assert "not recorded for this analysis" in section
    assert "makes no statement about whether it was used" in section
    assert "No protections" not in section
    assert "Protections recorded as applied" not in section
    assert "was not sent" not in section


def test_security_section_tracks_the_recorded_enrichment_disclosure() -> None:
    analysis = _completed()

    accepted = _section(_render(analysis, disclosure=_disclosure()), "## AI-processing security")
    remote = _section(
        _render(
            analysis,
            disclosure=_disclosure(
                model_location=ModelLocation.REMOTE,
                confirmed_context_sent_to_model=True,
                protections=(),
            ),
        ),
        "## AI-processing security",
    )
    none_attempted = _section(
        _render(
            analysis,
            disclosure=_disclosure(
                accepted_count=0,
                rejected_count=0,
                evidence_sent_to_model=False,
                model_location=ModelLocation.UNKNOWN,
            ),
        ),
        "## AI-processing security",
    )

    assert "Calls attempted: 3." in accepted
    assert "Output rejected by validation: 1." in accepted
    assert "Bounded finding evidence was sent to a model." in accepted
    assert "Confirmed context was not sent to a model." in accepted
    assert "Model location: local." in accepted
    assert "Output validated against a fixed schema" in accepted

    assert "Model location: remote." in remote
    assert "Confirmed context was sent to a model." in remote
    assert "No protections are recorded for AI enrichment." in remote
    assert "Output validated against a fixed schema" not in remote

    assert "No AI enrichment call is recorded as attempted." in none_attempted
    assert "Calls attempted" not in none_attempted
    assert "Model location: unknown." in none_attempted


def test_security_section_tracks_the_pipeline_exposure_state() -> None:
    analysis = _completed()
    off = _section(
        _render(replace(analysis, security_exposure=SecurityExposureState(False, False))),
        "## AI-processing security",
    )
    provider_only = _section(
        _render(replace(analysis, security_exposure=SecurityExposureState(True, False))),
        "## AI-processing security",
    )
    both = _section(
        _render(replace(analysis, security_exposure=SecurityExposureState(True, True))),
        "## AI-processing security",
    )

    assert "No model provider was enabled" in off
    assert "sample transmission to a model was not enabled" in off
    assert "A model provider was enabled" in provider_only
    assert "sample transmission to a model was not enabled" in provider_only
    assert "sample transmission to a model was enabled" in both
    assert off != provider_only != both


def test_suspicious_content_is_reported_only_when_such_findings_exist() -> None:
    analysis = _completed()
    security = [
        i
        for i, finding in enumerate(analysis.findings)
        if finding.category == DetectorCategory.AI_PROCESSING_SECURITY
    ]
    assert security, "the demo dataset is expected to contain a prompt-injection finding"
    other = [i for i in range(len(analysis.findings)) if i not in security]
    without = replace(
        analysis,
        findings=tuple(analysis.findings[i] for i in other),
        priority_scores=tuple(analysis.priority_scores[i] for i in other),
    )
    dismissed_analysis = replace(
        analysis,
        finding_reviews={
            str(i): _review(i, FindingReviewState.DISMISSED, dismissal_reason="expected")
            for i in security
        },
    )

    absent = _section(_render(without), "## AI-processing security")
    flagged = _section(_render(analysis), "## AI-processing security")
    dismissed = _section(_render(dismissed_analysis), "## AI-processing security")
    dismissed_shown = _section(
        _render(dismissed_analysis, options=ReportOptions(include_dismissed=True)),
        "## AI-processing security",
    )

    count = len(security)
    assert "The detectors that ran produced no suspicious-content findings." in absent
    assert "possible prompt-injection" not in absent
    assert f"{count} possible prompt-injection finding" in flagged
    assert "detected, 0 dismissed by the reviewer" in flagged
    assert "no suspicious-content findings" not in flagged
    assert f"detected, {count} dismissed by the reviewer" in dismissed
    assert f"Finding {security[0]}:" in flagged
    assert f"Finding {security[0]}:" not in dismissed
    assert f"Finding {security[0]}:" in dismissed_shown


def test_dismissed_findings_are_omitted_by_default_and_shown_when_requested() -> None:
    analysis = _completed()
    reviews = {
        "0": _review(
            0, FindingReviewState.DISMISSED, note="known", dismissal_reason="accepted risk"
        )
    }
    reviewed = replace(analysis, finding_reviews=reviews)

    default = _render(reviewed)
    included = _render(reviewed, options=ReportOptions(include_dismissed=True))

    assert "dismissed finding(s) are omitted" in _section(default, "## Priority findings")
    assert "accepted risk" not in default
    assert "dismissed finding(s) are omitted" not in included
    assert "accepted risk" in included
    assert "- **Finding 0**" not in default
    assert "- **Finding 0**" in included
    assert "Dismissed: 1" in default


def test_bounded_examples_are_row_numbers_only_and_capped() -> None:
    analysis = _completed()

    plain = _render(analysis)
    examples = _render(analysis, options=ReportOptions(include_bounded_examples=True))

    assert "Example affected row numbers" not in plain
    example_lines = [ln for ln in examples.splitlines() if "Example affected row numbers" in ln]
    assert example_lines
    for line in example_lines:
        numbers = line.split(": ", 1)[1].split(", ")
        assert 1 <= len(numbers) <= MAX_EXAMPLE_ROWS
        assert all(number.isdigit() for number in numbers)


def test_technical_appendix_appears_only_when_requested() -> None:
    analysis = _completed()

    appendix = _render(analysis, options=ReportOptions(include_technical_appendix=True))

    assert "## Technical appendix" in appendix
    assert "detector" in _section(appendix, "## Technical appendix")
    assert "## Technical appendix" not in _render(analysis)


def test_validated_rules_are_listed_and_withheld_ones_only_counted() -> None:
    analysis = _completed()
    column = ColumnReference(original_name="Quantity", internal_key="quantity", ordinal=0)
    result = RuleExecutionResult(
        rule_id="r",
        analysis_id=analysis.analysis_id,
        executed_at=_NOW,
        pass_count=8,
        fail_count=2,
        skipped_count=1,
        example_failures=(),
        duration_ms=1.0,
    )
    good = ValidationRule(
        rule_id="ok",
        schema_version="1",
        name="quantity range",
        description="d",
        severity=Severity.MEDIUM,
        rule_type=ValidationRuleType.NUMERIC_RANGE,
        columns=(column,),
        minimum=0.0,
        last_result=result,
    )
    withheld = replace(good, rule_id="off", name="disabled rule", enabled=False)

    section = _section(_render(replace(analysis, rules=(good, withheld))), "## Validation rules")

    assert "quantity range" in section
    assert "8 passed, 2 failed, 1 skipped" in section
    assert "disabled rule" not in section
    assert "1 rule(s) are not listed" in section
    assert "No validated rules" in _section(_render(analysis), "## Validation rules")


def test_versions_are_disclosed_and_unrecorded_ones_are_labelled() -> None:
    analysis = _completed()

    full = _section(_render(analysis), "## Versions")
    bare = _section(
        render_markdown(
            analysis,
            options=ReportOptions(),
            versions=ReportVersions(application_version="1.0.0"),
            ai_enrichment=None,
        ),
        "## Versions",
    )

    assert "Application: 9.9.9" in full
    assert full.index("alpha.detector") < full.index("zeta.detector")
    assert "Prompt version: prompt-v7" in full
    assert "Model: local-model-x" in full
    assert "Detectors: not recorded" in bare
    assert "Prompt version: not recorded" in bare
    assert "Model: not recorded" in bare


def test_disclosure_rejects_impossible_records() -> None:
    with pytest.raises(ValueError, match="negative"):
        _disclosure(accepted_count=-1)
    with pytest.raises(ValueError, match="no attempts"):
        _disclosure(accepted_count=0, rejected_count=0, provider_error_count=0)
    with pytest.raises(ValueError, match="application_version"):
        ReportVersions(application_version="")


def test_report_modules_have_no_framework_or_ai_provider_import_and_no_eval() -> None:
    forbidden = ("fastapi", "sqlalchemy", "pydantic", "ai_provider", "ai_boundary")
    for path in (_EXPORTS / name for name in _REPORT_MODULES):
        assert path.is_file(), path.name
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                names = [node.module or ""]
            for name in names:
                assert not any(part in name.split(".") for part in forbidden), (path.name, name)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                assert node.func.id not in {"eval", "exec"}, path.name
