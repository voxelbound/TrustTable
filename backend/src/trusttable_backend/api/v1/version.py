"""Operational endpoint: `GET /api/v1/version`."""

from __future__ import annotations

from fastapi import APIRouter

from trusttable_backend.schemas.version import VersionResponse
from trusttable_backend.version_info import (
    get_api_version,
    get_application_version,
    get_build_commit,
    get_environment_mode,
)

router = APIRouter(tags=["version"])


@router.get("/version", response_model=VersionResponse)
def get_version() -> VersionResponse:
    """Return version and build metadata. Always HTTP 200."""
    return VersionResponse(
        application_version=get_application_version(),
        api_version=get_api_version(),
        schema_version=None,
        detector_catalogue_version=None,
        build_commit=get_build_commit(),
        environment_mode=get_environment_mode(),
    )
