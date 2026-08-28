"""Profiling schemas (`PROF-01`), type inference (`PROF-02`), and core
profiling metrics (`PROF-03`).

Framework-independent: no FastAPI/SQLAlchemy/pydantic import.
"""

from __future__ import annotations

from .metrics import compute_dataset_profile
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
    "compute_dataset_profile",
    "infer_column_types",
]
