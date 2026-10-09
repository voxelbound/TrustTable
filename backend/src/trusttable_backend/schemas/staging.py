"""API schemas for staged uploads and the AI status route (`UX-02`, D-068).

Mirrors `docs/api-specification.md` §4 and §7. Nothing here carries a cell
value, a content hash, a filesystem path, a base URL or exception text.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from trusttable_backend.schemas.history import PreviousAnalysisNoticeResponse


class StagedWorksheet(BaseModel):
    name: str
    visible: bool


class StagedShape(BaseModel):
    row_count: int
    column_count: int


class StagedProblem(BaseModel):
    code: str
    message: str


class StagedNotice(BaseModel):
    code: str
    message: str
    count: int


class StagedCheckGroup(BaseModel):
    title: str
    description: str


class StagedUploadResponse(BaseModel):
    staging_ref: str | None
    expires_at: datetime | None
    filename: str
    format: Literal["csv", "xlsx"]
    byte_size: int
    worksheets: list[StagedWorksheet] | None
    selected_worksheet: str | None
    shape: StagedShape | None
    problems: list[StagedProblem]
    notices: list[StagedNotice]
    checks: list[StagedCheckGroup]
    can_run: bool
    #: Present only when a completed analysis that still exists matches this
    #: file (`UX-03`, D-069). Never carries a digest.
    previously_analysed: PreviousAnalysisNoticeResponse | None = None


class StagedUploadReference(BaseModel):
    """A request body naming one staged upload."""

    staging_ref: str = Field(max_length=256)


class StagedUploadInspectRequest(StagedUploadReference):
    worksheet: str | None = Field(default=None, max_length=1024)


class StagedUploadRunRequest(StagedUploadReference):
    worksheet: str | None = Field(default=None, max_length=1024)


class AiStatusResponse(BaseModel):
    assistance: Literal["off", "on"]
    state: Literal["disabled", "ready", "unavailable"]
    location: Literal["none", "local", "unknown"]
    provider_label: str
    runtime_label: str | None
    model_label: str | None
    sample_values_sent: bool
    summary: str
