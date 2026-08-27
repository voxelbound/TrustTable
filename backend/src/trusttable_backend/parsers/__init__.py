"""Secure file-content parsers (`ING-02`).

Framework-independent: no FastAPI/SQLAlchemy/pydantic import, no network
I/O. See `csv_parser.py` for the CSV parser; XLSX support (`ING-03`) is a
future package.
"""

from __future__ import annotations

from .csv_parser import CsvParseError, CsvParseLimits, CsvParseResult, parse_csv

__all__ = [
    "CsvParseError",
    "CsvParseLimits",
    "CsvParseResult",
    "parse_csv",
]
