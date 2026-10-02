"""The one place `Settings` become parser resource limits (`ING-03`).

The parsers (`parsers.csv_parser`, `parsers.xlsx_parser`) stay free of
`Settings`/pydantic and take limits as plain arguments; their built-in
defaults equal the documented defaults. Every production parse call site
(upload validation, analysis run, retry, context, rules, reports,
explanations) obtains its limits here, so an operator-configured limit is
the limit enforced on every parse of an untrusted file, not only on the
first one.
"""

from __future__ import annotations

from trusttable_backend.config import Settings, get_settings

from ..parsers.csv_parser import CsvParseLimits
from ..parsers.xlsx_parser import XlsxParseLimits

_MIB = 1024 * 1024


def csv_parse_limits(settings: Settings | None = None) -> CsvParseLimits:
    """Build `CsvParseLimits` from `settings` (the process settings by default)."""
    configured = settings if settings is not None else get_settings()
    return CsvParseLimits(
        max_bytes=configured.max_file_size_mb * _MIB,
        max_rows=configured.max_rows,
        max_columns=configured.max_columns,
        max_column_name_length=configured.max_column_name_length,
        max_field_length=configured.max_text_value_length_for_analysis,
    )


def xlsx_parse_limits(settings: Settings | None = None) -> XlsxParseLimits:
    """Build `XlsxParseLimits` from `settings` (the process settings by default).

    `max_entries` has no documented setting and keeps the parser's built-in
    value.
    """
    configured = settings if settings is not None else get_settings()
    return XlsxParseLimits(
        max_bytes=configured.max_file_size_mb * _MIB,
        max_uncompressed_bytes=configured.max_uncompressed_workbook_mb * _MIB,
        max_worksheets=configured.max_worksheets,
        max_rows=configured.max_rows,
        max_columns=configured.max_columns,
        max_cells=configured.max_cell_count,
        max_column_name_length=configured.max_column_name_length,
        max_field_length=configured.max_text_value_length_for_analysis,
    )
