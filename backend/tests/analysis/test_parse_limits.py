"""The settings-to-parser-limits factory and its call-site audit (`ING-03`).

`Settings` documents eight resource limits; the parsers take them as plain
arguments. These tests pin that every setting reaches the matching parser
limit, that unset settings reproduce the parsers' built-in defaults, and
that no production call site parses an untrusted file without passing the
configured limits.
"""

from __future__ import annotations

import ast
from pathlib import Path

import trusttable_backend
from trusttable_backend.analysis.parse_limits import csv_parse_limits, xlsx_parse_limits
from trusttable_backend.config import Settings
from trusttable_backend.parsers import CsvParseLimits, XlsxParseLimits

_MIB = 1024 * 1024

_PARSER_ENTRY_POINTS = {"parse_csv", "parse_xlsx", "inspect_xlsx_worksheets"}


def _settings(**overrides: int) -> Settings:
    return Settings(_env_file=None, **overrides)  # type: ignore[arg-type]


def test_default_settings_reproduce_the_parsers_built_in_defaults() -> None:
    settings = _settings()

    assert csv_parse_limits(settings) == CsvParseLimits()
    assert xlsx_parse_limits(settings) == XlsxParseLimits()


def test_every_documented_limit_reaches_the_csv_parser_limits() -> None:
    limits = csv_parse_limits(
        _settings(
            max_file_size_mb=3,
            max_rows=11,
            max_columns=12,
            max_column_name_length=13,
            max_text_value_length_for_analysis=14,
        )
    )

    assert limits == CsvParseLimits(
        max_bytes=3 * _MIB,
        max_rows=11,
        max_columns=12,
        max_column_name_length=13,
        max_field_length=14,
    )


def test_every_documented_limit_reaches_the_xlsx_parser_limits() -> None:
    default_entries = XlsxParseLimits().max_entries

    limits = xlsx_parse_limits(
        _settings(
            max_file_size_mb=3,
            max_uncompressed_workbook_mb=4,
            max_worksheets=5,
            max_rows=11,
            max_columns=12,
            max_cell_count=15,
            max_column_name_length=13,
            max_text_value_length_for_analysis=14,
        )
    )

    assert limits == XlsxParseLimits(
        max_bytes=3 * _MIB,
        max_uncompressed_bytes=4 * _MIB,
        max_entries=default_entries,
        max_worksheets=5,
        max_rows=11,
        max_columns=12,
        max_cells=15,
        max_column_name_length=13,
        max_field_length=14,
    )


def _called_name(call: ast.Call) -> str | None:
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


def test_no_production_call_site_parses_without_the_configured_limits() -> None:
    """Every call to a parser entry point outside the parsers package must
    pass `limits=` built by the factory; an omitted argument would silently
    fall back to the parser's built-in default and ignore the operator's
    setting.
    """
    source_root = Path(trusttable_backend.__file__).parent
    offenders: list[str] = []
    audited_calls = 0
    for path in sorted(source_root.rglob("*.py")):
        if "parsers" in path.relative_to(source_root).parts:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or _called_name(node) not in _PARSER_ENTRY_POINTS:
                continue
            audited_calls += 1
            limits_argument = next((kw for kw in node.keywords if kw.arg == "limits"), None)
            factory_call = (
                limits_argument is not None
                and isinstance(limits_argument.value, ast.Call)
                and _called_name(limits_argument.value) in {"csv_parse_limits", "xlsx_parse_limits"}
            )
            if not factory_call:
                offenders.append(f"{path.relative_to(source_root)}:{node.lineno}")

    assert offenders == []
    # parse_csv + parse_xlsx in the stage dispatcher, inspect at upload.
    assert audited_calls >= 3
