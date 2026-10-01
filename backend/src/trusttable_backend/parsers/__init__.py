"""Secure file-content parsers (`ING-02`, `ING-03`).

Framework-independent: no FastAPI/SQLAlchemy/pydantic import, no network
I/O. See `csv_parser.py` for the CSV parser and `xlsx_parser.py` for the
XLSX parser.
"""

from __future__ import annotations

from .csv_parser import CsvParseError, CsvParseLimits, CsvParseResult, parse_csv
from .xlsx_parser import XlsxParseError, XlsxParseLimits, XlsxParseResult, parse_xlsx

__all__ = [
    "CsvParseError",
    "CsvParseLimits",
    "CsvParseResult",
    "XlsxParseError",
    "XlsxParseLimits",
    "XlsxParseResult",
    "parse_csv",
    "parse_xlsx",
]
