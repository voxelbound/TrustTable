"""Aggregates all `/api/v1` routers."""

from __future__ import annotations

from fastapi import APIRouter

from trusttable_backend.api.v1 import (
    ai_status,
    analyses,
    confirmed_relationships,
    exports,
    health,
    reports,
    staged_uploads,
    version,
)

router = APIRouter(prefix="/api/v1")
router.include_router(health.router)
router.include_router(version.router)
router.include_router(ai_status.router)
router.include_router(analyses.router)
router.include_router(staged_uploads.router)
router.include_router(confirmed_relationships.router)
router.include_router(exports.router)
router.include_router(reports.router)
