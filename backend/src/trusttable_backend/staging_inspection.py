"""Pre-run inspection of a staged file (`UX-02`, D-068).

Answers, before anything is analysed: can this file be read, what are its
basic facts, and is there anything the user should know? It is a bounded parse
using the same parsers and the same configured limits as the analysis pipeline
(`analysis.parse_limits`), so what inspection accepts is what the pipeline can
read. No cell value is retained or returned; every user-visible string is fixed
text (the only variable parts are numbers: counts and configured limits) and
the only file-derived strings are worksheet names, returned as data.

It also derives the grouped, business-language "what will be checked" summary
from the categories of the registered detectors, so the summary cannot describe
a check that does not exist (a test fails when a category has no group).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Final

from .analysis.parse_limits import csv_parse_limits, xlsx_parse_limits
from .config import get_settings
from .detectors.catalogue import DETECTORS
from .detectors.contract import DetectorCategory
from .domain.parsing import ParsingWarning
from .errors import AppError
from .ingestion import (
    CSV_EXTENSION,
    WORKBOOK_REJECTIONS,
    choose_worksheet,
    inspect_workbook,
    require_worksheet_applies,
)
from .parsers import XlsxParseError, XlsxWorksheetInfo, parse_csv, parse_xlsx
from .parsers.csv_parser import CsvParseError

_MAX_NOTICE_KINDS: Final[int] = 6


@dataclass(frozen=True, slots=True)
class InspectionProblem:
    """A blocking readability problem, in fixed text."""

    code: str
    message: str


@dataclass(frozen=True, slots=True)
class InspectionNotice:
    """A non-blocking observation about reading the file; counts only."""

    code: str
    message: str
    count: int


@dataclass(frozen=True, slots=True)
class FileShape:
    row_count: int
    column_count: int


@dataclass(frozen=True, slots=True)
class FileInspection:
    """The outcome of inspecting one file (and one worksheet of a workbook).

    `file_unreadable` is true when the file itself cannot be read at all, in
    which case it must not be stored; a worksheet-level problem leaves the
    workbook readable so another worksheet can be chosen.
    """

    worksheets: tuple[XlsxWorksheetInfo, ...] | None
    selected_worksheet: str | None
    shape: FileShape | None
    problems: tuple[InspectionProblem, ...]
    notices: tuple[InspectionNotice, ...]
    file_unreadable: bool

    @property
    def can_run(self) -> bool:
        if self.problems:
            return False
        return self.worksheets is None or self.selected_worksheet is not None


def _csv_problem_message(code: str) -> str:
    settings = get_settings()
    messages = {
        "FILE_NOT_UTF8": (
            "This file does not appear to use UTF-8 text encoding, so TrustTable cannot "
            "read it reliably. Save or export it as CSV UTF-8 and choose it again."
        ),
        "NO_HEADER_ROW": "The file has no header row with column names.",
        "ROW_LIMIT_EXCEEDED": (
            f"The file has more than {settings.max_rows:,} data rows, which is more than "
            "this installation is set up to analyze."
        ),
        "COLUMN_LIMIT_EXCEEDED": (
            f"The file has more than {settings.max_columns:,} columns, which is more than "
            "this installation is set up to analyze."
        ),
        "CSV_UNREADABLE": "The text in this file could not be read as a table.",
    }
    return messages.get(code, messages["CSV_UNREADABLE"])


_WORKSHEET_UNREADABLE_MESSAGE: Final[str] = (
    "This worksheet could not be read as a table with a header row. Choose another worksheet."
)


def _plural(count: int, singular: str, plural: str) -> str:
    return f"{count:,} {singular if count == 1 else plural}"


def _notice_message(code: str, count: int) -> str:
    if code == "parsing.ragged_row":
        return (
            f"{_plural(count, 'row has', 'rows have')} a different number of values than "
            "the header row."
        )
    if code == "parsing.empty_column_name":
        return f"{_plural(count, 'column has', 'columns have')} no name in the header row."
    if code == "parsing.duplicate_column_name":
        return f"{_plural(count, 'column name appears', 'column names appear')} more than once."
    if code == "parsing.column_name_truncated":
        return (
            f"{_plural(count, 'column name is', 'column names are')} very long and will be "
            "shortened for analysis."
        )
    if code == "parsing.field_value_truncated":
        return (
            f"{_plural(count, 'value is', 'values are')} very long and will be shortened "
            "for analysis."
        )
    if code == "parsing.xlsx_external_links_ignored":
        return "The workbook links to other files. TrustTable never follows those links."
    if code == "parsing.xlsx_non_worksheet_ignored":
        return (
            "The workbook contains sheets that are not worksheets, such as charts. "
            "They are ignored."
        )
    if code == "parsing.xlsx_formula_without_cached_value":
        return (
            f"{_plural(count, 'formula cell has', 'formula cells have')} no stored result and "
            "will be read as empty."
        )
    if code == "parsing.xlsx_error_value":
        return f"{_plural(count, 'cell contains', 'cells contain')} a spreadsheet error value."
    return "Some parts of the file needed adjustment while reading it."


def _notices(warnings: tuple[ParsingWarning, ...]) -> tuple[InspectionNotice, ...]:
    counts: Counter[str] = Counter(warning.code for warning in warnings)
    return tuple(
        InspectionNotice(code=code, message=_notice_message(code, count), count=count)
        for code, count in counts.most_common(_MAX_NOTICE_KINDS)
    )


def _workbook_problem(code: str) -> InspectionProblem:
    resolved = code if code in WORKBOOK_REJECTIONS else "MALFORMED_FILE"
    return InspectionProblem(code=resolved, message=WORKBOOK_REJECTIONS[resolved][1])


def _inspect_csv(content: bytes) -> FileInspection:
    try:
        result = parse_csv(content, limits=csv_parse_limits())
    except CsvParseError as exc:
        return FileInspection(
            worksheets=None,
            selected_worksheet=None,
            shape=None,
            problems=(InspectionProblem(exc.code, _csv_problem_message(exc.code)),),
            notices=(),
            file_unreadable=True,
        )
    dataset = result.parsed_dataset
    return FileInspection(
        worksheets=None,
        selected_worksheet=None,
        shape=FileShape(row_count=dataset.row_count, column_count=len(dataset.columns)),
        problems=(),
        notices=_notices(dataset.parsing_warnings),
        file_unreadable=False,
    )


def _inspect_xlsx(content: bytes, requested_worksheet: str | None) -> FileInspection:
    try:
        worksheets = inspect_workbook(content)
    except AppError as exc:
        return FileInspection(
            worksheets=None,
            selected_worksheet=None,
            shape=None,
            problems=(_workbook_problem(exc.code),),
            notices=(),
            file_unreadable=True,
        )
    if requested_worksheet is not None:
        selected: str | None = choose_worksheet(worksheets, requested_worksheet)
    else:
        visible = [sheet.name for sheet in worksheets if sheet.visible]
        selected = visible[0] if len(visible) == 1 else None
    if selected is None:
        return FileInspection(
            worksheets=worksheets,
            selected_worksheet=None,
            shape=None,
            problems=(),
            notices=(),
            file_unreadable=False,
        )
    try:
        result = parse_xlsx(content, worksheet=selected, limits=xlsx_parse_limits())
    except XlsxParseError as exc:
        if exc.code in {"CELL_LIMIT_EXCEEDED", "WORKBOOK_EXPANSION_LIMIT"}:
            problem = _workbook_problem(exc.code)
        else:
            problem = InspectionProblem("WORKSHEET_UNREADABLE", _WORKSHEET_UNREADABLE_MESSAGE)
        return FileInspection(
            worksheets=worksheets,
            selected_worksheet=selected,
            shape=None,
            problems=(problem,),
            notices=(),
            file_unreadable=False,
        )
    dataset = result.parsed_dataset
    return FileInspection(
        worksheets=worksheets,
        selected_worksheet=selected,
        shape=FileShape(row_count=dataset.row_count, column_count=len(dataset.columns)),
        problems=(),
        notices=_notices(dataset.parsing_warnings),
        file_unreadable=False,
    )


def inspect_content(
    content: bytes, extension: str, requested_worksheet: str | None = None
) -> FileInspection:
    """Inspect `content` (blocking; call from a worker thread).

    Raises `AppError` (`400 INVALID_REQUEST`) only for a request that cannot be
    answered at all: a worksheet requested for a CSV, or one that is not in the
    workbook. Everything about the file itself is reported as problems.
    """
    require_worksheet_applies(extension, requested_worksheet)
    if extension == CSV_EXTENSION:
        return _inspect_csv(content)
    return _inspect_xlsx(content, requested_worksheet)


#: One business-language group per detector category: `(title, description)`.
_CHECK_GROUPS: Final[dict[DetectorCategory, tuple[str, str]]] = {
    DetectorCategory.STRUCTURAL: (
        "File structure and duplicates",
        "Empty or unnamed columns, repeated column names, repeated rows, columns that "
        "mix different kinds of values, and files with many rows that could not be read.",
    ),
    DetectorCategory.COMPLETENESS: (
        "Missing and empty data",
        "Empty rows, values missing in large numbers or in clusters, and identifiers "
        "that are missing.",
    ),
    DetectorCategory.CONSISTENCY: (
        "Inconsistent formatting",
        "The same thing written in different ways (capitalization, extra spaces, "
        "near-identical categories, yes/no spellings, date formats) and numbers stored "
        "as text.",
    ),
    DetectorCategory.VALIDITY: (
        "Values that look wrong",
        "Dates in the future or implausibly old, malformed email addresses, percentages "
        "outside a sensible range, and negative amounts where they are unlikely.",
    ),
    DetectorCategory.STATISTICAL: (
        "Unusual values",
        "Extreme outliers and columns that hold almost a single value.",
    ),
    DetectorCategory.CROSS_FIELD: (
        "Relationships between columns",
        "Totals that do not match the values they should come from.",
    ),
    DetectorCategory.AI_PROCESSING_SECURITY: (
        "Text aimed at AI tools",
        "Content that looks like instructions to an AI model or a request for secrets, "
        "flagged as a possible risk.",
    ),
}


@dataclass(frozen=True, slots=True)
class CheckGroup:
    title: str
    description: str


def check_groups() -> tuple[CheckGroup, ...]:
    """The groups of checks the standard analysis runs, one per registered
    detector category, in the catalogue's category order. Never names a
    detector."""
    registered = {detector.metadata.category for detector in DETECTORS}
    groups: list[CheckGroup] = []
    for category in DetectorCategory:
        if category in registered:
            title, description = _CHECK_GROUPS[category]
            groups.append(CheckGroup(title=title, description=description))
    return tuple(groups)
