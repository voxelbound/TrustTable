"""Aggregates all `/api/v1` routers."""

from __future__ import annotations

from fastapi import APIRouter

from trusttable_backend.api.v1 import analyses, health, version

router = APIRouter(prefix="/api/v1")
router.include_router(health.router)
router.include_router(version.router)
router.include_router(analyses.router)
