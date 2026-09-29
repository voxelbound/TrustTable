"""Pydantic schemas for the report routes (`EXP-01` slice 3,
`docs/api-specification.md` §12)."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class ReportOptionsModel(BaseModel):
    """The three report options; each defaults to off."""

    model_config = ConfigDict(extra="forbid")

    include_dismissed: bool = False
    include_technical_appendix: bool = False
    include_bounded_examples: bool = False


class CreateReportRequest(BaseModel):
    """Body for `POST /analyses/{analysis_id}/reports`."""

    model_config = ConfigDict(extra="forbid")

    options: ReportOptionsModel = ReportOptionsModel()


class ReportResponse(BaseModel):
    """Metadata of one generated report snapshot."""

    report_id: str
    analysis_id: str
    generated_at: datetime
    options: ReportOptionsModel
    schema_version: str
    content_sha256: str


class ReportListResponse(BaseModel):
    """Body for `GET /analyses/{analysis_id}/reports`."""

    reports: list[ReportResponse]
