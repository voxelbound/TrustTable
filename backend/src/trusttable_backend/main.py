"""FastAPI application factory.

Repository-foundation stage (FND-01): only operational endpoints are
registered. No product routes, persistence, or AI boundary exist yet.
"""

from __future__ import annotations

from fastapi import FastAPI

from trusttable_backend.api.v1.router import router as api_v1_router
from trusttable_backend.version_info import get_application_version


def create_app() -> FastAPI:
    """Build and return the FastAPI application instance."""
    app = FastAPI(
        title="TrustTable API",
        version=get_application_version(),
    )
    app.include_router(api_v1_router)
    return app


app = create_app()
