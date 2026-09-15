"""Fixed, versioned benchmark task fixtures (`AI-06`).

`build_fixture_tasks()` builds one `BenchmarkTask` per `AIOperation`
(six total), each grounded in real `Evidence` drawn from a demo-dataset
analysis run at a fixed reference instant — the same
`analysis.service.create_analysis`/`run_analysis` pipeline `RISK-01`/
`API-01` already exercise, reused here rather than hand-authoring
synthetic `Evidence` objects (`docs/decision-log.md` D-032: "fixed,
versioned, TrustTable-specific task fixtures ... built from the real
`ai_boundary` contract and the committed demo dataset").

Findings are looked up by their stable `detector_id` string, not by
list index, so this module stays correct even if detector ordering
changes. Fixtures never enable dataset-sample transmission
(`sample_sending_enabled=False`, `docs/product-requirements.md` §12's
"disabled by default").

Not framework-independent in the strict `ai_boundary`/`ai_provider`
sense — this is an application-layer package that imports
`analysis.service` to build real fixtures. Still no FastAPI/
SQLAlchemy/pydantic import.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from ..ai_boundary.envelope import PromptEnvelope
from ..ai_provider.contract import AIOperation, ProviderRequest
from ..analysis.service import Analysis, AnalysisStore, create_analysis, run_analysis
from ..detectors.contract import FindingCandidate
from ..domain.evidence import Evidence

#: Bumped whenever the fixture set's tasks/grounding evidence change in
#: a way a future consumer (e.g. a report comparing two benchmark runs)
#: needs to distinguish.
FIXTURE_SET_VERSION = "1"

#: Fixed reference instant fixtures are built at, matching the demo
#: dataset's own `REFERENCE_DATE` (`demo_data.generator`) so the same
#: findings/evidence — and therefore the same fixtures — are reproduced
#: byte-identically across runs and machines.
_FIXTURE_REFERENCE_INSTANT = datetime(2026, 8, 24, tzinfo=UTC)

#: Top-N findings by priority score used to ground the aggregate
#: `report_summary` task.
_REPORT_SUMMARY_TOP_N = 3


@dataclass(frozen=True, slots=True)
class BenchmarkTask:
    """One fixed benchmark task: a real, already-built `ProviderRequest`
    plus metadata identifying and describing it.
    """

    task_id: str
    operation: AIOperation
    description: str
    request: ProviderRequest

    def __post_init__(self) -> None:
        if not self.task_id:
            raise ValueError("BenchmarkTask.task_id must not be empty")
        if not self.description:
            raise ValueError("BenchmarkTask.description must not be empty")


class FixtureGroundingError(LookupError):
    """Raised when the reference demo analysis does not contain the
    finding/evidence a fixture task expects — a genuine fixture-
    construction defect, not a normal runtime condition.
    """


def _build_reference_analysis() -> Analysis:
    """Run the bundled demo dataset through the real analysis pipeline
    at the fixed reference instant, returning the completed `Analysis`
    fixtures are built from.
    """
    store = AnalysisStore()
    created = create_analysis(store)
    return run_analysis(store, created.analysis_id, now=_FIXTURE_REFERENCE_INSTANT)


def _finding_by_detector_id(analysis: Analysis, detector_id: str) -> FindingCandidate:
    for finding in analysis.findings:
        if finding.detector_id == detector_id:
            return finding
    raise FixtureGroundingError(
        f"no finding for detector_id={detector_id!r} in the reference demo analysis"
    )


def _evidence_for_ids(analysis: Analysis, evidence_ids: tuple[str, ...]) -> tuple[Evidence, ...]:
    by_id = {item.evidence_id: item for item in analysis.evidence}
    missing = [eid for eid in evidence_ids if eid not in by_id]
    if missing:
        raise FixtureGroundingError(
            f"evidence id(s) {missing!r} not found in the reference demo analysis"
        )
    return tuple(by_id[eid] for eid in evidence_ids)


def _known_numeric_facts_from_evidence(evidence: tuple[Evidence, ...]) -> dict[str, float]:
    """Derive a flat `known_numeric_facts` allow-list from the numeric
    fields of each included `Evidence.structured_payload`, aggregated by
    original field name.

    Only numeric scalar values (`int`/`float`, excluding `bool` — `bool`
    is a subclass of `int` in Python) participate; non-numeric fields
    (e.g. `validity.future_dates`' own `reference_date` string) are
    skipped. The flat `numeric_claims`/`known_numeric_facts` key contract
    is unchanged — keys are never namespaced by `evidence_id`.

    Collision rule (fixed, not caller-configurable):
    - A field name present in exactly one place is exposed as that flat
      key/value.
    - A field name present in multiple places with the *same* numeric
      value is exposed once, deterministically — independent of
      encounter order, never last-write-wins.
    - A field name present in multiple places with *different* numeric
      values is ambiguous and is **omitted** entirely (fails closed): a
      model claim using that key then correctly resolves to
      `unknown_numeric_claim` through `validate_model_output`, rather
      than silently asserting one of the conflicting values.
    """
    values: dict[str, float] = {}
    ambiguous: set[str] = set()
    for item in evidence:
        for key, raw_value in item.structured_payload.items():
            if isinstance(raw_value, bool) or not isinstance(raw_value, int | float):
                continue
            if key in ambiguous:
                continue
            numeric_value = float(raw_value)
            if key not in values:
                values[key] = numeric_value
            elif values[key] != numeric_value:
                ambiguous.add(key)
                del values[key]
    return values


def _make_task(
    *,
    task_id: str,
    operation: AIOperation,
    description: str,
    evidence: tuple[Evidence, ...],
) -> BenchmarkTask:
    envelope = PromptEnvelope(
        task=description,
        computed_evidence=evidence,
        confirmed_context={},
        untrusted_dataset_samples=(),
        sample_sending_enabled=False,
    )
    return BenchmarkTask(
        task_id=task_id,
        operation=operation,
        description=description,
        request=ProviderRequest(
            operation=operation,
            envelope=envelope,
            known_numeric_facts=_known_numeric_facts_from_evidence(evidence),
        ),
    )


def _build_single_finding_task(
    analysis: Analysis,
    *,
    task_id: str,
    operation: AIOperation,
    description: str,
    detector_id: str,
) -> BenchmarkTask:
    finding = _finding_by_detector_id(analysis, detector_id)
    evidence = _evidence_for_ids(analysis, finding.evidence_ids)
    return _make_task(
        task_id=task_id, operation=operation, description=description, evidence=evidence
    )


def _build_report_summary_task(analysis: Analysis) -> BenchmarkTask:
    if not analysis.findings:
        raise FixtureGroundingError("reference demo analysis has no findings to summarize")
    ranked = sorted(
        range(len(analysis.findings)),
        key=lambda i: analysis.priority_scores[i],
        reverse=True,
    )
    top_findings = [analysis.findings[i] for i in ranked[:_REPORT_SUMMARY_TOP_N]]
    evidence_ids = tuple(dict.fromkeys(eid for f in top_findings for eid in f.evidence_ids))
    evidence = _evidence_for_ids(analysis, evidence_ids)
    return _make_task(
        task_id="report_summary",
        operation=AIOperation.REPORT_SUMMARY,
        description=(
            "Summarize the overall trust assessment and top findings for "
            "this dataset, grounded only in the following deterministic "
            "evidence."
        ),
        evidence=evidence,
    )


def build_fixture_tasks() -> tuple[BenchmarkTask, ...]:
    """Build the fixed, versioned fixture set — one `BenchmarkTask` per
    `AIOperation` (six total). Deterministic: two calls return the same
    task IDs, operations, and evidence content, every time.
    """
    analysis = _build_reference_analysis()
    return (
        _build_single_finding_task(
            analysis,
            task_id="context_inference",
            operation=AIOperation.CONTEXT_INFERENCE,
            description=(
                "Infer likely business context for this dataset from its "
                "structure, grounded only in the following deterministic "
                "evidence."
            ),
            detector_id="structural.empty_column",
        ),
        _build_single_finding_task(
            analysis,
            task_id="guided_questions",
            operation=AIOperation.GUIDED_QUESTIONS,
            description=(
                "Propose up to three clarifying questions a business "
                "analyst should confirm about this dataset, grounded only "
                "in the following deterministic evidence."
            ),
            detector_id="completeness.missing_likely_identifier",
        ),
        _build_single_finding_task(
            analysis,
            task_id="finding_explanation",
            operation=AIOperation.FINDING_EXPLANATION,
            description="Explain the following deterministic finding in plain business language.",
            detector_id="validity.future_dates",
        ),
        _build_single_finding_task(
            analysis,
            task_id="remediation",
            operation=AIOperation.REMEDIATION,
            description="Recommend a remediation for the following deterministic finding.",
            detector_id="validity.negative_likely_non_negative_values",
        ),
        _build_single_finding_task(
            analysis,
            task_id="rule_description",
            operation=AIOperation.RULE_DESCRIPTION,
            description=(
                "Describe, for a non-technical audience, the data-quality "
                "rule the following deterministic finding represents."
            ),
            detector_id="validity.invalid_percentages",
        ),
        _build_report_summary_task(analysis),
    )


__all__ = ["FIXTURE_SET_VERSION", "BenchmarkTask", "FixtureGroundingError", "build_fixture_tasks"]
