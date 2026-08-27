"""Framework-independent domain contracts (ING-01).

No FastAPI/SQLAlchemy/pydantic import anywhere in this package — see
`docs/architecture.md` §3 "Backend layers": "domain modules do not import
SQLAlchemy models."
"""

from __future__ import annotations

from .parsing import (
    Dataset,
    DatasetFormat,
    DatasetSourceType,
    ParsedDataset,
    ParsingWarning,
    SampleMetadata,
    SamplingScope,
    WorksheetMetadata,
)
from .value_objects import ColumnReference, RowReference

__all__ = [
    "ColumnReference",
    "RowReference",
    "Dataset",
    "DatasetFormat",
    "DatasetSourceType",
    "ParsedDataset",
    "ParsingWarning",
    "SampleMetadata",
    "SamplingScope",
    "WorksheetMetadata",
]
