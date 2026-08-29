"""In-memory analysis orchestration (`API-01`, enabling slice).

Framework-independent: no FastAPI/SQLAlchemy import. See `service.py` for
the full engine and `docs/architecture.md` §3 for this module's layer
placement ("Application services").
"""

from __future__ import annotations

from .service import (
    Analysis,
    AnalysisFailure,
    AnalysisNotFoundError,
    AnalysisState,
    AnalysisStore,
    cancel_analysis,
    create_analysis,
    get_findings,
    get_profile,
    get_status,
    run_analysis,
)

__all__ = [
    "Analysis",
    "AnalysisFailure",
    "AnalysisNotFoundError",
    "AnalysisState",
    "AnalysisStore",
    "cancel_analysis",
    "create_analysis",
    "get_findings",
    "get_profile",
    "get_status",
    "run_analysis",
]
