"""Profiling schemas (`PROF-01`).

Framework-independent: no FastAPI/SQLAlchemy/pydantic import, no
computation. `PROF-02` (type inference) and `PROF-03` (core profiling)
are the future packages that populate real inferred types and metrics.
"""

from __future__ import annotations

from .schemas import (
    ColumnProfile,
    DatasetProfile,
    InferredColumnType,
    ProfilingTiming,
    ProfilingWarning,
)
from .type_inference import infer_column_types

__all__ = [
    "ColumnProfile",
    "DatasetProfile",
    "InferredColumnType",
    "ProfilingTiming",
    "ProfilingWarning",
    "infer_column_types",
]
