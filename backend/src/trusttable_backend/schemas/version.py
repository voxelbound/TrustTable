"""Pydantic schema for `GET /api/v1/version`.

`schema_version` and `detector_catalogue_version` stay present and
nullable until `PROF-01` / `DET-02` populate them, so the response shape
never has to change (WP-001 "Specification gaps or conflicts" #2).
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

EnvironmentMode = Literal["development", "test", "production"]


class VersionResponse(BaseModel):
    """Body for `GET /api/v1/version`. Always returned with HTTP 200."""

    application_version: str
    api_version: str
    schema_version: str | None = None
    detector_catalogue_version: str | None = None
    build_commit: str | None = None
    environment_mode: EnvironmentMode
