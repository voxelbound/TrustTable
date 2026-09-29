"""Creating an immutable report snapshot (`EXP-01` slice 3).

Framework-independent: no FastAPI/SQLAlchemy/pydantic import. The snapshot
is rendered exactly once, at creation, and the resulting bytes are what is
stored and served. Downloads never re-render from live analysis state, so a
later review or rule change cannot alter an existing report.

No `AiEnrichmentDisclosure` is supplied: the analysis aggregate does not
record per-request AI enrichment (`D-046`), so the rendered report says the
matter is not recorded instead of asserting an answer. Prompt version and
model name are likewise not recorded and are reported as such.
"""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from datetime import datetime
from typing import Protocol

from ..analysis.service import Analysis
from ..detectors.catalogue import DETECTORS
from .report_markdown import render_markdown
from .report_snapshot import REPORT_SCHEMA_VERSION, ReportOptions, ReportSnapshot, ReportVersions


class ReportStoreProtocol(Protocol):
    """The durable report interface the report routes call through."""

    def add(self, snapshot: ReportSnapshot) -> None: ...

    def get(self, analysis_id: str, report_id: str) -> ReportSnapshot | None: ...

    def list_for_analysis(self, analysis_id: str) -> Sequence[ReportSnapshot]: ...


def detector_versions() -> tuple[tuple[str, str], ...]:
    """`(detector_id, version)` for every detector in the catalogue."""
    return tuple(
        sorted((d.metadata.detector_id, d.metadata.version) for d in DETECTORS),
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
        ai_enrichment=None,
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
