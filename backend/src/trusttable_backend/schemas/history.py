"""API schemas for the recent-analyses list and the "analysed before" notice
(`UX-03`, D-069).

Nothing here carries a content hash, a cell value, a finding, a filesystem path
or exception text. The list is a bounded, content-free view of what is stored.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class AnalysisHistoryItem(BaseModel):
    analysis_id: str
    state: Literal[
        "queued",
        "validating",
        "parsing",
        "profiling",
        "detecting",
        "completed",
        "failed",
        "cancelled",
    ]
    original_filename: str
    format: Literal["csv", "xlsx"]
    byte_size: int
    selected_worksheet: str | None
    source: Literal["upload", "demo"]
    created_at: datetime
    completed_at: datetime | None
    trust_label: str | None
    finding_count: int | None


class AnalysisHistoryResponse(BaseModel):
    items: list[AnalysisHistoryItem]
    limit: int


class PreviousAnalysisNoticeResponse(BaseModel):
    """`same_file`: the staged bytes match a completed analysis exactly.
    `same_name`: only the file name matches; no diff is implied."""

    kind: Literal["same_file", "same_name"]
    count: int
    latest_analysis_id: str
    latest_analysed_at: datetime
    latest_filename: str
