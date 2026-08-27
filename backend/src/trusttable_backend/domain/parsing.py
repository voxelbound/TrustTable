"""Typed parsing contracts (ING-01): dataset, worksheet, warning, and
sample metadata, matching `docs/domain-model.md` §4 (`Dataset`) and §6
(`ParsedDataset`).

Framework-independent: no FastAPI/SQLAlchemy/pydantic import, no I/O. These
types model the *shape* of parsed data. `ING-02` (secure CSV parser) and
`ING-03` (secure XLSX parser) are responsible for actually reading bytes
and constructing instances of `ParsedDataset`. Resource-limit enforcement
(row/column/byte caps) is `ING-02`'s job, not this module's.

Stdlib only (`dataclasses`, `datetime`, `enum`) — no pandas/NumPy/FastAPI/
SQLAlchemy/pydantic import.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from .value_objects import ColumnReference, RowReference


class DatasetFormat(StrEnum):
    """Closed set of source-file formats (`docs/domain-model.md` §4)."""

    CSV = "csv"
    XLSX = "xlsx"


class DatasetSourceType(StrEnum):
    """Closed set of dataset origins (`docs/domain-model.md` §4)."""

    UPLOAD = "upload"
    BUNDLED_DEMO = "bundled_demo"


@dataclass(frozen=True, slots=True)
class Dataset:
    """One uploaded or generated tabular data source (`docs/domain-model.md`
    §4). Fields follow §4's exact field list. This type carries only
    metadata about the source file — uploaded content is immutable and the
    original file is never overwritten, and neither is modeled here as
    file bytes.
    """

    dataset_id: str
    original_filename: str
    stored_filename: str
    format: DatasetFormat
    byte_size: int
    content_hash: str
    selected_worksheet: str | None
    created_at: datetime
    deleted_at: datetime | None
    storage_location: str
    source_type: DatasetSourceType

    def __post_init__(self) -> None:
        if not self.dataset_id:
            raise ValueError("Dataset.dataset_id must not be empty")
        if not self.original_filename:
            raise ValueError("Dataset.original_filename must not be empty")
        if not self.stored_filename:
            raise ValueError("Dataset.stored_filename must not be empty")
        if self.byte_size < 0:
            raise ValueError("Dataset.byte_size must not be negative")
        if not self.content_hash:
            raise ValueError("Dataset.content_hash must not be empty")
        if not self.storage_location:
            raise ValueError("Dataset.storage_location must not be empty")
        if self.deleted_at is not None and self.deleted_at < self.created_at:
            raise ValueError("Dataset.deleted_at must not precede Dataset.created_at")


@dataclass(frozen=True, slots=True)
class WorksheetMetadata:
    """Metadata about one worksheet within a multi-sheet workbook (e.g.
    XLSX).

    Not part of any single `docs/domain-model.md` field list — a new,
    minimal contract designed to satisfy `Dataset.selected_worksheet` (§4)
    and the future Excel worksheet-selection scenario, kept intentionally
    small (name, ordinal index, row/column counts, selected flag).
    """

    name: str
    index: int
    row_count: int
    column_count: int
    is_selected: bool

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("WorksheetMetadata.name must not be empty")
        if self.index < 0:
            raise ValueError("WorksheetMetadata.index must not be negative")
        if self.row_count < 0:
            raise ValueError("WorksheetMetadata.row_count must not be negative")
        if self.column_count < 0:
            raise ValueError("WorksheetMetadata.column_count must not be negative")


@dataclass(frozen=True, slots=True)
class ParsingWarning:
    """A non-fatal condition observed while parsing (`docs/domain-model.md`
    §6 "parsing warnings").

    `code` is a namespaced identifier following the same convention as
    `DetectorId` (`docs/domain-model.md` §3), e.g.
    `parsing.truncated_row`.
    """

    code: str
    message: str
    column: ColumnReference | None = None
    row: RowReference | None = None

    def __post_init__(self) -> None:
        if not self.message:
            raise ValueError("ParsingWarning.message must not be empty")
        if "." not in self.code:
            raise ValueError("ParsingWarning.code must be namespaced (contain '.')")


class SamplingScope(StrEnum):
    """Whether analysis metrics were computed from the full dataset or a
    sample (`docs/domain-model.md` §6 "sampling metadata", §7 "sampled
    metrics are labelled")."""

    FULL = "full"
    SAMPLED = "sampled"


@dataclass(frozen=True, slots=True)
class SampleMetadata:
    """Describes the calculation scope and, when sampled, the sampling
    method (`docs/domain-model.md` §6/§7).

    Invariants: `full` scope requires `sample_size == population_size` and
    no `method`; `sampled` scope requires a `method` and
    `sample_size <= population_size`; both scopes reject
    `sample_size > population_size`.
    """

    scope: SamplingScope
    population_size: int
    sample_size: int
    method: str | None = None

    def __post_init__(self) -> None:
        if self.population_size < 0:
            raise ValueError("SampleMetadata.population_size must not be negative")
        if self.sample_size < 0:
            raise ValueError("SampleMetadata.sample_size must not be negative")
        if self.sample_size > self.population_size:
            raise ValueError("SampleMetadata.sample_size must not exceed population_size")

        if self.scope is SamplingScope.FULL:
            if self.sample_size != self.population_size:
                raise ValueError(
                    "SampleMetadata: full scope requires sample_size == population_size"
                )
            if self.method is not None:
                raise ValueError("SampleMetadata: full scope must not declare a method")
        else:
            if self.method is None:
                raise ValueError("SampleMetadata: sampled scope requires a method")


@dataclass(frozen=True, slots=True)
class ParsedDataset:
    """In-memory representation used by profiling and detectors
    (`docs/domain-model.md` §6).

    `format` corresponds to §6's "source types" field: the source file
    format the dataset was parsed from. It drives this type's
    format-conditional worksheet invariant: `csv` datasets carry no
    `worksheets` entries, while `xlsx` datasets require at least one
    `WorksheetMetadata` with exactly one `is_selected`.
    """

    columns: tuple[ColumnReference, ...]
    row_count: int
    format: DatasetFormat
    worksheets: tuple[WorksheetMetadata, ...]
    parsing_warnings: tuple[ParsingWarning, ...]
    sampling: SampleMetadata
    row_references: tuple[RowReference, ...]

    def __post_init__(self) -> None:
        if self.row_count < 0:
            raise ValueError("ParsedDataset.row_count must not be negative")

        internal_keys = [column.internal_key for column in self.columns]
        if len(internal_keys) != len(set(internal_keys)):
            raise ValueError("ParsedDataset.columns must have unique internal_key values")

        ordinals = [column.ordinal for column in self.columns]
        if len(ordinals) != len(set(ordinals)):
            raise ValueError("ParsedDataset.columns must have unique ordinal values")

        if self.format is DatasetFormat.CSV:
            if self.worksheets:
                raise ValueError("ParsedDataset.worksheets must be empty for csv format")
        else:
            if not self.worksheets:
                raise ValueError("ParsedDataset.worksheets must be non-empty for xlsx format")
            selected_count = sum(1 for worksheet in self.worksheets if worksheet.is_selected)
            if selected_count != 1:
                raise ValueError(
                    "ParsedDataset.worksheets must have exactly one is_selected entry "
                    "for xlsx format"
                )

        if len(self.row_references) != self.sampling.sample_size:
            raise ValueError("ParsedDataset.row_references length must match sampling.sample_size")
