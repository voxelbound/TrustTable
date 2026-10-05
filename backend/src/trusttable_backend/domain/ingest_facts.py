"""The in-memory ingest-facts projection (`DET-03` closure package 1,
`docs/decision-log.md` D-061 item 8a).

Parser warnings exist for CSV and XLSX but are dropped before detectors run.
This module projects exactly four of them into one immutable value that
reaches a detector only through an additive, optional input behind a
metadata flag (`DetectorMetadata.requires_ingest_facts`, default off):

- `parsing.empty_column_name`
- `parsing.ragged_row`
- `parsing.xlsx_formula_without_cached_value`
- `parsing.xlsx_error_value`

What the projection is **not**:

- It is not persisted and not exposed through any API, export or report; it
  lives for one analysis run and is rebuilt from the parse result.
- It never carries a parser `message`, a cell value or a row's content. A
  warning message may quote a parsed count or a name, and a detector must not
  be able to repeat it. Only structured counts and bounded references pass.
- It never carries the other parser warnings. Truncation caused by a
  TrustTable processing limit (`parsing.field_value_truncated`,
  `parsing.column_name_truncated`) is deliberately outside the four codes: it
  is not a defect in the user's data, so no detector can mistake it for one.

Stdlib only; framework-independent per `docs/architecture.md` §3.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from .parsing import ParsedDataset
from .value_objects import ColumnReference, RowReference

CODE_EMPTY_COLUMN_NAME: Final[str] = "parsing.empty_column_name"
CODE_RAGGED_ROW: Final[str] = "parsing.ragged_row"
CODE_XLSX_FORMULA_WITHOUT_CACHED_VALUE: Final[str] = "parsing.xlsx_formula_without_cached_value"
CODE_XLSX_ERROR_VALUE: Final[str] = "parsing.xlsx_error_value"

#: The complete, closed set of parser warning codes the projection reads.
INGEST_FACT_WARNING_CODES: Final[frozenset[str]] = frozenset(
    {
        CODE_EMPTY_COLUMN_NAME,
        CODE_RAGGED_ROW,
        CODE_XLSX_FORMULA_WITHOUT_CACHED_VALUE,
        CODE_XLSX_ERROR_VALUE,
    }
)

#: Upper bound on references of each kind kept in the projection. Counts are
#: always exact; only the example references are capped.
MAX_REFERENCES: Final[int] = 20


@dataclass(frozen=True, slots=True)
class IngestFacts:
    """Counts and bounded references observed while parsing one dataset.

    `row_count` and `column_count` are the denominators a detector needs to
    judge a count's size. `unnamed_columns` and `ragged_rows` hold at most
    `MAX_REFERENCES` example references each, in ascending order, while the
    matching `*_count` fields stay exact.
    """

    row_count: int
    column_count: int
    unnamed_column_count: int
    unnamed_columns: tuple[ColumnReference, ...]
    ragged_row_count: int
    ragged_rows: tuple[RowReference, ...]
    formula_without_cached_value_cell_count: int
    error_value_cell_count: int

    def __post_init__(self) -> None:
        for name in (
            "row_count",
            "column_count",
            "unnamed_column_count",
            "ragged_row_count",
            "formula_without_cached_value_cell_count",
            "error_value_cell_count",
        ):
            if getattr(self, name) < 0:
                raise ValueError(f"IngestFacts.{name} must not be negative")
        if len(self.unnamed_columns) > min(MAX_REFERENCES, self.unnamed_column_count):
            raise ValueError("IngestFacts.unnamed_columns exceeds its bound or its count")
        if len(self.ragged_rows) > min(MAX_REFERENCES, self.ragged_row_count):
            raise ValueError("IngestFacts.ragged_rows exceeds its bound or its count")


def project_ingest_facts(dataset: ParsedDataset) -> IngestFacts:
    """Project the four ingest-fact warnings of `dataset` into `IngestFacts`.

    Reads only each warning's `code`, `count`, `column` and `row`; never its
    `message`. References are rebuilt from their identifying fields only (a
    row reference drops any fingerprint and source line), de-duplicated,
    ordered and capped at `MAX_REFERENCES`. Pure and deterministic.
    """
    unnamed_count = 0
    ragged_count = 0
    formula_cells = 0
    error_cells = 0
    unnamed_by_ordinal: dict[int, ColumnReference] = {}
    ragged_by_number: dict[int, RowReference] = {}

    for warning in dataset.parsing_warnings:
        if warning.code == CODE_EMPTY_COLUMN_NAME:
            unnamed_count += warning.count
            if warning.column is not None:
                unnamed_by_ordinal.setdefault(warning.column.ordinal, warning.column)
        elif warning.code == CODE_RAGGED_ROW:
            ragged_count += warning.count
            if warning.row is not None:
                ragged_by_number.setdefault(
                    warning.row.row_number, RowReference(row_number=warning.row.row_number)
                )
        elif warning.code == CODE_XLSX_FORMULA_WITHOUT_CACHED_VALUE:
            formula_cells += warning.count
        elif warning.code == CODE_XLSX_ERROR_VALUE:
            error_cells += warning.count

    unnamed_columns = tuple(
        unnamed_by_ordinal[ordinal] for ordinal in sorted(unnamed_by_ordinal)[:MAX_REFERENCES]
    )
    ragged_rows = tuple(
        ragged_by_number[number] for number in sorted(ragged_by_number)[:MAX_REFERENCES]
    )
    return IngestFacts(
        row_count=dataset.row_count,
        column_count=len(dataset.columns),
        unnamed_column_count=unnamed_count,
        unnamed_columns=unnamed_columns,
        ragged_row_count=ragged_count,
        ragged_rows=ragged_rows,
        formula_without_cached_value_cell_count=formula_cells,
        error_value_cell_count=error_cells,
    )
