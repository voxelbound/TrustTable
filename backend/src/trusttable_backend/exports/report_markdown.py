"""Deterministic Markdown report renderer (`EXP-01` slice 2).

A pure function over an already-computed `Analysis` plus explicit options,
versions and an optional AI-enrichment disclosure. It reads no dataset row
content: it never touches `Analysis.content` or evidence payloads. Detector
observations can themselves quote dataset values (for example the differing
casings found), so by default a finding is described only by its detector
name, category, columns and counts. The bounded-examples option adds the
observation text and up to `MAX_EXAMPLE_ROWS` physical row numbers per
finding. Rule definitions/aggregates and recorded state are always allowed.

Every interpolated string is escaped so a hostile column name or note
cannot inject Markdown or HTML structure. There is no timestamp of the
render itself, so output is byte-identical for identical input.

The AI-processing security section states only what is recorded. It never
asserts that nothing was sent to a model, or that protections applied,
beyond `SecurityExposureState` and a caller-supplied
`AiEnrichmentDisclosure`.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from ..analysis.service import Analysis, AnalysisState
from ..detectors.catalogue import DETECTORS
from ..detectors.contract import DetectorCategory, FindingCandidate
from ..domain.context import ConfirmationState, ContextFieldValue
from ..domain.review import FindingReview, FindingReviewState
from ..domain.rules import ValidationRule
from ..risk.scoring import TrustLabel
from .report_snapshot import (
    MAX_EXAMPLE_ROWS,
    REPORT_SCHEMA_VERSION,
    AiEnrichmentDisclosure,
    ReportOptions,
    ReportVersions,
)
from .rules_export import is_validated


class ReportNotAvailableError(Exception):
    """The analysis is not `COMPLETED`, so there is nothing to report."""

    def __init__(self, analysis_id: str) -> None:
        super().__init__(f"analysis {analysis_id} is not completed; no report can be rendered")
        self.analysis_id = analysis_id


_TRUST_LABEL_TEXT = {
    TrustLabel.HIGH_CONFIDENCE: "High confidence",
    TrustLabel.USABLE_WITH_CAUTION: "Usable with caution",
    TrustLabel.MATERIAL_QUALITY_CONCERNS: "Material quality concerns",
    TrustLabel.NOT_RELIABLE_FOR_DECISION_MAKING: "Not reliable for decision-making",
}

_REVIEW_STATE_TEXT = {
    FindingReviewState.UNREVIEWED: "Unreviewed",
    FindingReviewState.CONFIRMED: "Confirmed",
    FindingReviewState.DISMISSED: "Dismissed",
    FindingReviewState.NEEDS_INVESTIGATION: "Needs investigation",
}

_DETECTOR_NAMES = {detector.metadata.detector_id: detector.metadata.name for detector in DETECTORS}

_ESCAPE = re.compile(r"([\\`*_{}\[\]<>#|!~&])")
_MAX_TEXT = 300


def _md(value: object, limit: int = _MAX_TEXT) -> str:
    """Escape untrusted text for inline Markdown and bound its length."""
    text = " ".join(str(value).split())
    if len(text) > limit:
        text = text[: limit - 1] + "…"
    return _ESCAPE.sub(r"\\\1", text)


def _columns(finding: FindingCandidate) -> str:
    if not finding.affected_columns:
        return "dataset-level"
    return ", ".join(_md(column.original_name, 80) for column in finding.affected_columns)


def _describe(finding: FindingCandidate, options: ReportOptions) -> str:
    """A finding's description. A detector observation can quote dataset
    values (for example the differing casings it found), so it is emitted
    only with the bounded-examples option; otherwise the value-free
    detector name is used."""
    name = _md(_DETECTOR_NAMES.get(finding.detector_id, finding.detector_id), 120)
    if options.include_bounded_examples:
        return f"{name}: {_md(finding.calculated_observation)}"
    return name


def _review(analysis: Analysis, index: int) -> FindingReview | None:
    return analysis.finding_reviews.get(str(index))


def _state(review: FindingReview | None) -> FindingReviewState:
    return review.state if review is not None else FindingReviewState.UNREVIEWED


def _ordered_findings(analysis: Analysis) -> list[int]:
    """Finding indexes by priority score descending, then original order."""
    return sorted(range(len(analysis.findings)), key=lambda i: (-analysis.priority_scores[i], i))


def _visible(analysis: Analysis, options: ReportOptions) -> list[int]:
    return [
        i
        for i in _ordered_findings(analysis)
        if options.include_dismissed or _state(_review(analysis, i)) != FindingReviewState.DISMISSED
    ]


def _dismissed_count(analysis: Analysis) -> int:
    return sum(
        1
        for i in range(len(analysis.findings))
        if _state(_review(analysis, i)) == FindingReviewState.DISMISSED
    )


def _title(analysis: Analysis) -> list[str]:
    return [f"# Data quality report: {_md(analysis.dataset.original_filename, 120)}", ""]


def _dataset_summary(analysis: Analysis) -> list[str]:
    profile = analysis.dataset_profile
    assert profile is not None
    sampling = profile.sampling
    coverage = (
        f"all {sampling.population_size} rows"
        if sampling.sample_size == sampling.population_size
        else f"a sample of {sampling.sample_size} of {sampling.population_size} rows"
    )
    dataset = analysis.dataset
    return [
        "## Dataset summary",
        "",
        f"- File: {_md(dataset.original_filename, 120)} ({dataset.format.value})",
        f"- Size: {dataset.byte_size} bytes",
        f"- Content hash (SHA-256): `{dataset.content_hash}`",
        f"- Rows: {sampling.population_size}",
        f"- Columns: {len(profile.column_profiles)}",
        f"- Calculations covered: {coverage}",
        f"- Analysis identifier: `{analysis.analysis_id}`",
        "",
    ]


def _trust_assessment(analysis: Analysis) -> list[str]:
    trust = analysis.trust_assessment
    assert trust is not None
    lines = [
        "## Trust assessment",
        "",
        f"- Assessment: **{_TRUST_LABEL_TEXT[trust.label]}**",
        f"- Score: {trust.score:.1f} / 100",
        f"- Findings considered: {trust.finding_count}",
    ]
    if trust.highest_priority_score is not None:
        lines.append(f"- Highest finding priority score: {trust.highest_priority_score:.1f}")
    lines.append("- The score is calculated deterministically; AI cannot alter it.")
    lines.append("")
    return lines


def _context_value(item: ContextFieldValue) -> str:
    if item.confirmation_state == ConfirmationState.UNKNOWN:
        return "Not determined"
    value = item.value
    if isinstance(value, (list, tuple)):
        text = ", ".join(str(part) for part in value) or "None"
    else:
        text = str(value)
    return f"{_md(text)} ({item.confirmation_state.value}, {item.inference_source.value})"


def _confirmed_context(analysis: Analysis) -> list[str]:
    lines = ["## Confirmed context", ""]
    context = analysis.context
    if context is None:
        lines.append("Context has not been inferred or confirmed for this analysis.")
        lines.append("")
        return lines
    state = "finalized" if analysis.context_finalized else "not finalized"
    lines.append(f"Context is {state}. Each value shows how it was established.")
    lines.append("")
    for label, item in (
        ("Probable domain", context.probable_domain),
        ("Row grain", context.row_grain),
        ("Primary entity", context.primary_entity),
        ("Candidate keys", context.candidate_keys),
        ("Business dates", context.business_dates),
        ("Measure roles", context.measure_roles),
        ("Dimensions", context.dimensions),
        ("Currency behaviour", context.currency_behavior),
        ("Expected business rules", context.expected_business_rules),
    ):
        lines.append(f"- {label}: {_context_value(item)}")
    lines.append("")
    return lines


def _finding_line(analysis: Analysis, index: int, options: ReportOptions) -> list[str]:
    finding = analysis.findings[index]
    state = _REVIEW_STATE_TEXT[_state(_review(analysis, index))]
    lines = [
        f"- **Finding {index}** ({finding.severity.value.title()}, "
        f"{_md(finding.category.value)}) in {_columns(finding)}: {_describe(finding, options)}",
        f"  - Priority score: {analysis.priority_scores[index]:.1f}; "
        f"affected rows: {len(finding.affected_row_references)}; review: {state}",
    ]
    if options.include_bounded_examples and finding.affected_row_references:
        rows = [ref.row_number for ref in finding.affected_row_references[:MAX_EXAMPLE_ROWS]]
        shown = ", ".join(str(row) for row in rows)
        lines.append(f"  - Example affected row numbers (bounded to {MAX_EXAMPLE_ROWS}): {shown}")
    return lines


def _priority_findings(analysis: Analysis, options: ReportOptions) -> list[str]:
    lines = ["## Priority findings", ""]
    visible = _visible(analysis, options)
    if not analysis.findings:
        lines.append("No findings were produced by the detectors that ran.")
    elif not visible:
        lines.append("All findings were dismissed by the reviewer and are omitted.")
    else:
        lines.append("Ordered by priority score, highest first.")
        if not options.include_bounded_examples:
            lines.append(
                "Detector observations and example rows are omitted because they can quote "
                "dataset values; request bounded examples to include them."
            )
        lines.append("")
        for index in visible:
            lines.extend(_finding_line(analysis, index, options))
    omitted = 0 if options.include_dismissed else _dismissed_count(analysis)
    if omitted:
        lines.append("")
        lines.append(f"{omitted} dismissed finding(s) are omitted from this report.")
    lines.append("")
    return lines


def _review_decisions(analysis: Analysis, options: ReportOptions) -> list[str]:
    lines = ["## Review decisions", ""]
    counts = {state: 0 for state in FindingReviewState}
    for index in range(len(analysis.findings)):
        counts[_state(_review(analysis, index))] += 1
    for state in FindingReviewState:
        lines.append(f"- {_REVIEW_STATE_TEXT[state]}: {counts[state]}")
    noted = False
    for index in _ordered_findings(analysis):
        review = _review(analysis, index)
        if review is None or review.state == FindingReviewState.UNREVIEWED:
            continue
        if review.state == FindingReviewState.DISMISSED and not options.include_dismissed:
            continue
        details = []
        if review.note:
            details.append(f"note: {_md(review.note)}")
        if review.dismissal_reason:
            details.append(f"dismissal reason: {_md(review.dismissal_reason)}")
        if not details:
            continue
        if not noted:
            lines.extend(["", "Reviewer notes:", ""])
            noted = True
        state_text = _REVIEW_STATE_TEXT[review.state]
        lines.append(f"- Finding {index} ({state_text}) {'; '.join(details)}")
    lines.append("")
    return lines


def _recommendations(analysis: Analysis, options: ReportOptions) -> list[str]:
    lines = ["## Recommendations", ""]
    confirmed: list[int] = []
    investigate: list[int] = []
    unreviewed: list[int] = []
    for index in _visible(analysis, options):
        state = _state(_review(analysis, index))
        if state == FindingReviewState.CONFIRMED:
            confirmed.append(index)
        elif state == FindingReviewState.NEEDS_INVESTIGATION:
            investigate.append(index)
        elif state == FindingReviewState.UNREVIEWED:
            unreviewed.append(index)
    if not (confirmed or investigate or unreviewed):
        lines.append("No open findings require action.")
        lines.append("")
        return lines
    if confirmed:
        lines.append("Correct at source (confirmed findings):")
        for index in confirmed:
            finding = analysis.findings[index]
            key = finding.default_remediation_template_key
            hint = f" (remediation template `{_md(key, 80)}`)" if key else ""
            lines.append(f"- Finding {index}: {_describe(finding, options)}{hint}")
    if investigate:
        lines.append("Investigate before relying on the data:")
        lines.extend(f"- Finding {index}" for index in investigate)
    if unreviewed:
        ids = ", ".join(str(index) for index in unreviewed)
        lines.append(f"Review still pending for {len(unreviewed)} finding(s): {ids}.")
    lines.append("")
    return lines


def _rule_line(rule: ValidationRule) -> str:
    result = rule.last_result
    assert result is not None
    columns = ", ".join(_md(column.original_name, 80) for column in rule.columns)
    return (
        f"- {_md(rule.name, 120)} ({rule.rule_type.value}, {rule.severity.value}) on {columns}: "
        f"{result.pass_count} passed, {result.fail_count} failed, {result.skipped_count} skipped"
    )


def _validation_rules(analysis: Analysis) -> list[str]:
    lines = ["## Validation rules", ""]
    validated = [rule for rule in analysis.rules if is_validated(rule)]
    withheld = len(analysis.rules) - len(validated)
    if not validated:
        lines.append("No validated rules are recorded for this analysis.")
    else:
        lines.append("Only enabled rules with a successful latest execution are listed.")
        lines.append("")
        lines.extend(_rule_line(rule) for rule in validated)
    if withheld:
        lines.append("")
        lines.append(
            f"{withheld} rule(s) are not listed (disabled, never run, or failed last run)."
        )
    lines.append("")
    return lines


def _plural(count: int, noun: str) -> str:
    return f"{count} {noun}" if count == 1 else f"{count} {noun}s"


def _ai_security(
    analysis: Analysis, disclosure: AiEnrichmentDisclosure | None, options: ReportOptions
) -> list[str]:
    exposure = analysis.security_exposure
    lines = ["## AI-processing security", ""]

    lines.append("Detection pipeline (deterministic):")
    if not exposure.model_provider_enabled:
        lines.append("- No model provider was enabled for the detection pipeline.")
    else:
        lines.append("- A model provider was enabled for the detection pipeline.")
    if exposure.sample_transmission_enabled:
        lines.append("- Dataset sample transmission to a model was enabled.")
    else:
        lines.append("- Dataset sample transmission to a model was not enabled.")

    suspicious = [
        i
        for i, finding in enumerate(analysis.findings)
        if finding.category == DetectorCategory.AI_PROCESSING_SECURITY
    ]
    dismissed = [
        i for i in suspicious if _state(_review(analysis, i)) == FindingReviewState.DISMISSED
    ]
    lines.extend(["", "Suspicious content:"])
    if not suspicious:
        lines.append("- The detectors that ran produced no suspicious-content findings.")
    else:
        lines.append(
            f"- {_plural(len(suspicious), 'possible prompt-injection finding')} "
            f"detected, {len(dismissed)} dismissed by the reviewer."
        )
        for index in suspicious:
            if not options.include_dismissed and index in dismissed:
                continue
            finding = analysis.findings[index]
            lines.append(f"  - Finding {index}: {_describe(finding, options)}")

    lines.extend(["", "Optional AI enrichment (explanations, context suggestions):"])
    if disclosure is None:
        lines.append("- Per-request AI enrichment is not recorded for this analysis.")
        lines.append("- This report makes no statement about whether it was used.")
    elif disclosure.attempt_count == 0:
        lines.append("- No AI enrichment call is recorded as attempted.")
        lines.append(f"- Model location: {disclosure.model_location.value}.")
    else:
        lines.append(f"- Calls attempted: {disclosure.attempt_count}.")
        lines.append(f"- Output accepted: {disclosure.accepted_count}.")
        lines.append(f"- Output rejected by validation: {disclosure.rejected_count}.")
        lines.append(f"- Provider errors: {disclosure.provider_error_count}.")
        evidence = "was" if disclosure.evidence_sent_to_model else "was not"
        context = "was" if disclosure.confirmed_context_sent_to_model else "was not"
        lines.append(f"- Bounded finding evidence {evidence} sent to a model.")
        lines.append(f"- Confirmed context {context} sent to a model.")
        lines.append(f"- Model location: {disclosure.model_location.value}.")
    if disclosure is not None:
        if disclosure.protections:
            lines.append("- Protections recorded as applied:")
            lines.extend(f"  - {_md(protection)}" for protection in disclosure.protections)
        else:
            lines.append("- No protections are recorded for AI enrichment.")
    lines.append("")
    return lines


def _methodology(analysis: Analysis) -> list[str]:
    profile = analysis.dataset_profile
    assert profile is not None
    sampling = profile.sampling
    lines = [
        "## Methodology and limitations",
        "",
        "- Findings come from deterministic detectors that calculate their own evidence.",
        "- The trust assessment and finding priority scores are calculated deterministically.",
        "- AI-generated text, where present, is advisory and never changes a finding or score.",
        "- Reviewer decisions are recorded by people and are shown as recorded.",
        "- Only the detectors in the catalogue were run; other quality problems can exist.",
    ]
    if sampling.sample_size != sampling.population_size:
        lines.append(
            f"- Calculations used a sample of {sampling.sample_size} of "
            f"{sampling.population_size} rows."
        )
    lines.append("")
    return lines


def _versions(versions: ReportVersions) -> list[str]:
    lines = [
        "## Versions",
        "",
        f"- Application: {_md(versions.application_version, 80)}",
        f"- Report schema: {REPORT_SCHEMA_VERSION}",
    ]
    if versions.detector_versions:
        lines.append("- Detectors:")
        lines.extend(
            f"  - {_md(detector_id, 80)}: {_md(version, 40)}"
            for detector_id, version in sorted(versions.detector_versions)
        )
    else:
        lines.append("- Detectors: not recorded")
    lines.append(f"- Prompt version: {_md(versions.prompt_version or 'not recorded')}")
    lines.append(f"- Model: {_md(versions.model_name or 'not recorded')}")
    lines.append("")
    return lines


def _appendix(analysis: Analysis, options: ReportOptions) -> list[str]:
    lines = ["## Technical appendix", ""]
    profile = analysis.dataset_profile
    assert profile is not None
    lines.append(f"- Profile schema version: {_md(profile.schema_version, 40)}")
    lines.append("")
    for index in _visible(analysis, options):
        finding = analysis.findings[index]
        keys = ", ".join(_md(column.internal_key, 80) for column in finding.affected_columns)
        evidence = ", ".join(_md(item, 80) for item in finding.evidence_ids) or "none"
        lines.append(
            f"- Finding {index}: detector {_md(finding.detector_id, 80)} "
            f"v{_md(finding.detector_version, 40)}, confidence {finding.confidence:.2f}, "
            f"columns [{keys or 'none'}], evidence [{evidence}]"
        )
    for rule in analysis.rules:
        if not is_validated(rule):
            continue
        lines.append(
            f"- Rule {_md(rule.rule_id, 80)}: provenance {rule.provenance.value}, "
            f"null handling {rule.null_handling.value}, "
            f"source findings [{', '.join(_md(f, 40) for f in rule.source_finding_ids) or 'none'}]"
        )
    lines.append("")
    return lines


def render_markdown(
    analysis: Analysis,
    *,
    options: ReportOptions,
    versions: ReportVersions,
    ai_enrichment: AiEnrichmentDisclosure | None,
) -> str:
    """Render the report. Raises `ReportNotAvailableError` unless `COMPLETED`."""
    if (
        analysis.state != AnalysisState.COMPLETED
        or analysis.dataset_profile is None
        or analysis.trust_assessment is None
    ):
        raise ReportNotAvailableError(analysis.analysis_id)
    sections: Sequence[list[str]] = [
        _title(analysis),
        _dataset_summary(analysis),
        _trust_assessment(analysis),
        _confirmed_context(analysis),
        _priority_findings(analysis, options),
        _review_decisions(analysis, options),
        _recommendations(analysis, options),
        _validation_rules(analysis),
        _ai_security(analysis, ai_enrichment, options),
        _methodology(analysis),
        _versions(versions),
    ]
    if options.include_technical_appendix:
        sections = [*sections, _appendix(analysis, options)]
    lines = [line for section in sections for line in section]
    return "\n".join(lines).rstrip("\n") + "\n"
