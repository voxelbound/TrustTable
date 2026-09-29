"""Creating an immutable report snapshot (`EXP-01` slice 3).

Framework-independent: no FastAPI/SQLAlchemy/pydantic import. The snapshot
is rendered exactly once, at creation, and the resulting bytes are what is
stored and served. Downloads never re-render from live analysis state, so a
later review or rule change cannot alter an existing report.

The AI-enrichment disclosure comes from `Analysis.ai_enrichment` (`EXP-01`
slice 4). When that record is `None` -- the analysis predates recording --
no disclosure is supplied and the rendered report says the matter is not
recorded instead of asserting an answer (`D-046`). Prompt version and model
name are not recorded and are reported as such.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from ..analysis.service import Analysis
from ..detectors.catalogue import DETECTORS
from .report_markdown import render_markdown
from .report_snapshot import (
    REPORT_SCHEMA_VERSION,
    AiEnrichmentDisclosure,
    ModelLocation,
    ReportOptions,
    ReportSnapshot,
    ReportVersions,
)

#: Protections that hold on every path that can reach a model: all three
#: enrichment routes build a `PromptEnvelope` and validate the model output
#: with a role-specific validator before using it. Attested in a report only
#: when at least one call is recorded.
ENRICHMENT_PROTECTIONS: tuple[str, ...] = (
    "Dataset-derived content is sent inside an untrusted-data prompt envelope.",
    "Model output is validated before use; output that fails validation is rejected.",
)


class ReportStoreProtocol(Protocol):
    """The durable report interface the report routes call through."""

    def add(self, snapshot: ReportSnapshot) -> bool:
        """Store the snapshot; `False` when its analysis no longer exists."""
        ...

    def get(self, analysis_id: str, report_id: str) -> ReportSnapshot | None: ...

    def list_for_analysis(self, analysis_id: str) -> Sequence[ReportSnapshot]: ...


def detector_versions() -> tuple[tuple[str, str], ...]:
    """`(detector_id, version)` for every detector in the catalogue."""
    return tuple(
        sorted((d.metadata.detector_id, d.metadata.version) for d in DETECTORS),
    )


def enrichment_disclosure(analysis: Analysis) -> AiEnrichmentDisclosure | None:
    """The report's AI-enrichment disclosure, or `None` (*not recorded*)
    when the analysis predates recording. A zero record yields a
    disclosure with no attempts, which the report states as such."""
    record = analysis.ai_enrichment
    if record is None:
        return None
    return AiEnrichmentDisclosure(
        accepted_count=record.accepted_count,
        rejected_count=record.rejected_count,
        provider_error_count=record.provider_error_count,
        evidence_sent_to_model=record.evidence_sent_to_model,
        confirmed_context_sent_to_model=record.confirmed_context_sent_to_model,
        model_location=(
            ModelLocation(record.model_location.value)
            if record.model_location is not None
            else ModelLocation.UNKNOWN
        ),
        protections=ENRICHMENT_PROTECTIONS if record.attempt_count > 0 else (),
    )


def create_report_snapshot(
    analysis: Analysis,
    *,
    options: ReportOptions,
    application_version: str,
    report_id: str,
    generated_at: datetime,
) -> ReportSnapshot:
    """Render and freeze a report. Raises
    `report_markdown.ReportNotAvailableError` unless the analysis is
    `COMPLETED`."""
    markdown = render_markdown(
        analysis,
        options=options,
        versions=ReportVersions(
            application_version=application_version,
            detector_versions=detector_versions(),
        ),
        ai_enrichment=enrichment_disclosure(analysis),
    )
    return ReportSnapshot(
        report_id=report_id,
        analysis_id=analysis.analysis_id,
        generated_at=generated_at,
        options=options,
        schema_version=REPORT_SCHEMA_VERSION,
        markdown=markdown,
        content_sha256=hashlib.sha256(markdown.encode("utf-8")).hexdigest(),
    )
