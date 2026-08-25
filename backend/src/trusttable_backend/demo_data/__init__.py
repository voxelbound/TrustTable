"""Synthetic demo dataset generation (DEMO-01).

Framework-independent: no FastAPI/SQLAlchemy import. See `generator.py` for
the full generator and `demo-data/README.md` for the regeneration approach.
"""

from __future__ import annotations

from .generator import (
    COLUMN_NAMES,
    ISSUE_TYPES,
    SEED,
    GeneratedDataset,
    GeneratedIssue,
    generate,
)

__all__ = [
    "COLUMN_NAMES",
    "ISSUE_TYPES",
    "SEED",
    "GeneratedDataset",
    "GeneratedIssue",
    "generate",
]
