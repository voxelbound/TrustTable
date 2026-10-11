"""Measure the cost of re-parsing stored content for one inspector window (`UX-06`, D-073).

The inspector reads a window of rows through the same path as the existing row-context
route: the stored file is parsed again on every request (`analysis.service.
get_finding_row_context` -> `_parse_analysis_content`). D-066 item 6 requires this to be
measured on the real product path, at representative sizes, before any window or paging
limit is set. This script builds synthetic files in memory, parses them with the real
parsers and the real configured limits, and prints a Markdown table of wall time and
peak Python memory.

Run from `backend/`:

    uv run python scripts/measure_inspector_parse.py            # standard cases
    uv run python scripts/measure_inspector_parse.py --quick    # small cases only

It is a measurement aid, not part of the test suite: figures depend on the machine, and
nothing here asserts a threshold. The synthetic data is generated here; no user data is
read and nothing is written to disk.
"""

from __future__ import annotations

import argparse
import csv
import io
import statistics
import time
import tracemalloc
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from xml.sax.saxutils import escape

from trusttable_backend.analysis.parse_limits import csv_parse_limits, xlsx_parse_limits
from trusttable_backend.parsers import parse_csv, parse_xlsx

_MIB = 1024 * 1024
_MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_REPEATS = 3


@dataclass(frozen=True, slots=True)
class Case:
    kind: str  # "csv" or "xlsx"
    rows: int
    columns: int


STANDARD_CASES = (
    Case("csv", 10_000, 10),
    Case("csv", 100_000, 10),
    Case("csv", 100_000, 50),
    Case("csv", 500_000, 10),
    Case("csv", 1_000, 500),
    Case("xlsx", 10_000, 10),
    Case("xlsx", 100_000, 10),
)
QUICK_CASES = (Case("csv", 10_000, 10), Case("xlsx", 2_000, 10))


def _value(row: int, column: int) -> str:
    """Deterministic mixed content: identifiers, amounts, names, dates and blanks."""
    pick = column % 5
    if pick == 0:
        return str(row * 7 + column)
    if pick == 1:
        return f"{(row * 31 + column) % 100000 / 100:.2f}"
    if pick == 2:
        return f"Customer {row % 977} Ltd"
    if pick == 3:
        return f"2025-{(row % 12) + 1:02d}-{(row % 28) + 1:02d}"
    return "" if row % 13 == 0 else f"note-{row % 31}"


def build_csv(case: Case) -> bytes:
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([f"column_{index}" for index in range(case.columns)])
    for row in range(case.rows):
        writer.writerow([_value(row, column) for column in range(case.columns)])
    return buffer.getvalue().encode("utf-8")


def _column_letters(index: int) -> str:
    letters = ""
    index += 1
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(ord("A") + remainder) + letters
    return letters


def build_xlsx(case: Case) -> bytes:
    letters = [_column_letters(index) for index in range(case.columns)]
    parts = [f'<worksheet xmlns="{_MAIN_NS}"><sheetData>']
    header = "".join(
        f'<c r="{letters[index]}1" t="inlineStr"><is><t>column_{index}</t></is></c>'
        for index in range(case.columns)
    )
    parts.append(f'<row r="1">{header}</row>')
    for row in range(case.rows):
        number = row + 2
        cells = "".join(
            f'<c r="{letters[column]}{number}" t="inlineStr"><is><t>'
            f"{escape(_value(row, column))}</t></is></c>"
            for column in range(case.columns)
        )
        parts.append(f'<row r="{number}">{cells}</row>')
    parts.append("</sheetData></worksheet>")
    files = {
        "xl/worksheets/sheet1.xml": "".join(parts),
        "xl/workbook.xml": (
            f'<workbook xmlns="{_MAIN_NS}" xmlns:r="{_REL_NS}"><sheets>'
            '<sheet name="Sheet1" sheetId="1" r:id="rId1"/></sheets></workbook>'
        ),
        "xl/_rels/workbook.xml.rels": (
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f'<Relationship Id="rId1" Type="{_PKG_REL}/worksheet" Target="worksheets/sheet1.xml"/>'
            "</Relationships>"
        ),
        "[Content_Types].xml": (
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-'
            'officedocument.spreadsheetml.sheet.main+xml"/></Types>'
        ),
    }
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def _parser_for(case: Case, content: bytes) -> Callable[[], int]:
    """The real parse call with the real configured limits; returns the row count."""
    if case.kind == "xlsx":
        xlsx_limits = xlsx_parse_limits()

        def parse_workbook() -> int:
            return len(parse_xlsx(content, worksheet="Sheet1", limits=xlsx_limits).rows)

        return parse_workbook
    csv_limits = csv_parse_limits()

    def parse_text() -> int:
        return len(parse_csv(content, limits=csv_limits).rows)

    return parse_text


def measure(case: Case) -> str:
    content = build_csv(case) if case.kind == "csv" else build_xlsx(case)
    size_mib = len(content) / _MIB
    limit = csv_parse_limits().max_bytes
    label = f"| {case.kind.upper()} | {case.rows:,} | {case.columns} | {size_mib:.1f} |"
    if len(content) > limit:
        return f"{label} over the {limit // _MIB} MiB upload limit | - | - |"
    parse = _parser_for(case, content)
    timings: list[float] = []
    parsed_rows = 0
    for _ in range(_REPEATS):
        started = time.perf_counter()
        parsed_rows = parse()
        timings.append(time.perf_counter() - started)
    tracemalloc.start()
    parse()
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    median = statistics.median(timings)
    return (
        f"{label} {median:.2f} (min {min(timings):.2f}, max {max(timings):.2f}) "
        f"| {peak / _MIB:.0f} | {parsed_rows:,} |"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0] if __doc__ else None)
    parser.add_argument("--quick", action="store_true", help="small cases only")
    arguments = parser.parse_args()
    cases = QUICK_CASES if arguments.quick else STANDARD_CASES
    print(
        "| Format | Rows | Columns | File MiB | Parse seconds (median of 3) "
        "| Peak MiB | Rows read |"
    )
    print("|---|---:|---:|---:|---|---:|---:|")
    for case in cases:
        print(measure(case), flush=True)


if __name__ == "__main__":
    main()
