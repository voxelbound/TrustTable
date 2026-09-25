"""SQLAlchemy 2 + Alembic persistence for the `Analysis` aggregate
(`DB-01`, `WP-074`).

Public surface: `build_engine`/`build_session_factory`/`run_migrations`
(`database.py`), `SqlAnalysisStore` (`store.py`, structurally satisfies
`analysis.service.AnalysisStoreProtocol`), and
`reconcile_interrupted_analyses` (`reconciliation.py`). See each module's
own docstring for detail.
"""

from __future__ import annotations

from .database import (
    build_engine,
    build_session_factory,
    ensure_data_directory,
    is_schema_ready,
    run_migrations,
)
from .reconciliation import INTERRUPTED_BY_RESTART_CODE, reconcile_interrupted_analyses
from .store import SqlAnalysisStore

__all__ = [
    "INTERRUPTED_BY_RESTART_CODE",
    "SqlAnalysisStore",
    "build_engine",
    "build_session_factory",
    "ensure_data_directory",
    "is_schema_ready",
    "reconcile_interrupted_analyses",
    "run_migrations",
]
