"""Build an immutable `ReportSnapshot` from a completed `Analysis`
(`EXP-01` slice 2). Persistence and HTTP routes are a later slice."""

from __future__ import annotations

import hashlib
from datetime import datetime

from ..analysis.service import Analysis
from .report_markdown import render_markdown
from .report_snapshot import (
    REPORT_SCHEMA_VERSION,
    AiEnrichmentDisclosure,
    ReportOptions,
    ReportSnapshot,
    ReportVersions,
)


def build_report_snapshot(
    analysis: Analysis,
    *,
    report_id: str,
    generated_at: datetime,
    versions: ReportVersions,
    options: ReportOptions | None = None,
    ai_enrichment: AiEnrichmentDisclosure | None = None,
) -> ReportSnapshot:
    """Render and freeze a report.

    Raises `ReportNotAvailableError` unless the analysis is `COMPLETED`.
    `report_id` and `generated_at` are supplied by the caller so the
    rendered Markdown stays a pure function of the analysis and options.
    """
    resolved = options if options is not None else ReportOptions()
    markdown = render_markdown(
        analysis, options=resolved, versions=versions, ai_enrichment=ai_enrichment
    )
    return ReportSnapshot(
        report_id=report_id,
        analysis_id=analysis.analysis_id,
        generated_at=generated_at,
        options=resolved,
        schema_version=REPORT_SCHEMA_VERSION,
        markdown=markdown,
        content_sha256=hashlib.sha256(markdown.encode("utf-8")).hexdigest(),
    )
