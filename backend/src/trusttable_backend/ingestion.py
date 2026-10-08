"""The one shared ingestion path for an uploaded file (`UX-02`, D-068).

Direct upload (`POST /analyses`) and temporary staging (`POST
/staged-uploads`, then Run) apply exactly the same rules, which live here and
nowhere else: the filename and extension rules, the bounded read and size
limit, the empty-file rule, the workbook inspection with its fixed-text
rejections, and the worksheet-choice rules. Behavior is unchanged from the
direct-upload route they were lifted from (`docs/api-specification.md` §6, §14).

Every message is fixed text. Nothing from the file is echoed back except, for
worksheet selection, the worksheet names the caller must choose between, and
the configured limit numbers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from starlette.datastructures import UploadFile

from .analysis.parse_limits import xlsx_parse_limits
from .config import get_settings
from .domain.parsing import DatasetFormat
from .errors import AppError
from .parsers import XlsxParseError, XlsxWorksheetInfo, inspect_xlsx_worksheets
from .uploads import sanitize_filename

#: The formats accepted for upload (`ING-02` CSV, `ING-03` XLSX). `.xlsm` and
#: every other extension is `415 UNSUPPORTED_FILE_TYPE`.
CSV_EXTENSION: Final[str] = ".csv"
XLSX_EXTENSION: Final[str] = ".xlsx"
SUPPORTED_UPLOAD_EXTENSIONS: Final[list[str]] = [CSV_EXTENSION, XLSX_EXTENSION]

#: Fixed response for each workbook rejection class
#: (`docs/api-specification.md` §14): `(status, message)`.
WORKBOOK_REJECTIONS: Final[dict[str, tuple[int, str]]] = {
    "MACRO_ENABLED_FILE": (415, "The workbook contains macros and is not supported."),
    "WORKBOOK_EXPANSION_LIMIT": (413, "The workbook exceeds the size limits once unpacked."),
    "CELL_LIMIT_EXCEEDED": (413, "The workbook exceeds the row, column or cell limits."),
    "MALFORMED_FILE": (400, "The file could not be read as a valid .xlsx workbook."),
}


@dataclass(frozen=True, slots=True)
class IngestionPlan:
    """What a validated upload will be analysed as."""

    dataset_format: DatasetFormat
    selected_worksheet: str | None


def upload_extension(filename: str) -> str | None:
    """The supported extension of `filename` (case-insensitive), else `None`."""
    lowered = filename.lower()
    for extension in SUPPORTED_UPLOAD_EXTENSIONS:
        if lowered.endswith(extension):
            return extension
    return None


def max_upload_bytes() -> int:
    """The configured per-file size limit, in bytes."""
    return get_settings().max_file_size_mb * 1024 * 1024


def validate_upload_name(original_name: str | None) -> tuple[str, str]:
    """Return `(sanitized_filename, extension)` or raise the documented error.

    A request with no `file` part never reaches here (FastAPI's own validation
    refuses it first); this guards a blank or missing filename inside a present
    part and an unsupported type.
    """
    if not original_name:
        raise AppError(
            "INVALID_REQUEST",
            "A filename is required.",
            status_code=400,
            details={},
        )
    extension = upload_extension(original_name)
    if extension is None:
        raise AppError(
            "UNSUPPORTED_FILE_TYPE",
            "Only .csv and .xlsx files are currently supported.",
            status_code=415,
            details={
                "filename": sanitize_filename(original_name),
                "supported_extensions": SUPPORTED_UPLOAD_EXTENSIONS,
            },
        )
    return sanitize_filename(original_name), extension


async def read_upload_content(file: UploadFile) -> bytes:
    """Read an upload with the size bound applied to the read itself.

    An oversized upload never fully enters memory before being refused
    (`docs/security-threat-model.md` §3.1 "resource exhaustion"). An empty file
    is `400 INVALID_REQUEST`.
    """
    max_bytes = max_upload_bytes()
    content = await file.read(max_bytes + 1)
    if len(content) > max_bytes:
        raise AppError(
            "FILE_TOO_LARGE",
            "The uploaded file exceeds the maximum allowed size.",
            status_code=413,
            details={"max_bytes": max_bytes},
        )
    if not content:
        raise AppError(
            "INVALID_REQUEST",
            "The uploaded file is empty.",
            status_code=400,
            details={},
        )
    return content


def reject_for_workbook_error(exc: XlsxParseError) -> AppError:
    """The documented fixed-text `AppError` for a workbook parse failure."""
    code = exc.code if exc.code in WORKBOOK_REJECTIONS else "MALFORMED_FILE"
    status_code, message = WORKBOOK_REJECTIONS[code]
    return AppError(code, message, status_code=status_code, details={})


def inspect_workbook(content: bytes) -> tuple[XlsxWorksheetInfo, ...]:
    """List a workbook's worksheets, refusing unsafe or unreadable ones.

    Runs the parser's package validation (macros, encryption, traversal,
    DOCTYPE, decompression budget) without reading any worksheet's cells, so
    the cost is bounded by the package structure. A rejection becomes the
    documented fixed-text error for its class.
    """
    try:
        return inspect_xlsx_worksheets(content, limits=xlsx_parse_limits())
    except XlsxParseError as exc:
        raise reject_for_workbook_error(exc) from exc


def choose_worksheet(worksheets: tuple[XlsxWorksheetInfo, ...], requested: str | None) -> str:
    """Pick the worksheet to analyze, per `docs/api-specification.md` §6/§14.

    An explicit choice must name an existing worksheet. Without one, a workbook
    with exactly one visible worksheet uses it; anything else is
    `WORKSHEET_REQUIRED` — the service never guesses between worksheets.
    """
    names = [worksheet.name for worksheet in worksheets]
    if requested is not None:
        if requested not in names:
            raise AppError(
                "INVALID_REQUEST",
                "The requested worksheet does not exist in the workbook.",
                status_code=400,
                details={"worksheets": names},
            )
        return requested
    visible = [worksheet.name for worksheet in worksheets if worksheet.visible]
    if len(visible) == 1:
        return visible[0]
    raise AppError(
        "WORKSHEET_REQUIRED",
        "The workbook has several worksheets; choose one with the worksheet field.",
        status_code=400,
        details={"worksheets": names},
    )


def require_worksheet_applies(extension: str, requested_worksheet: str | None) -> None:
    """A worksheet can only be chosen for `.xlsx` files (`400 INVALID_REQUEST`).

    Cheap, so a route calls it before reading the body.
    """
    if extension == CSV_EXTENSION and requested_worksheet is not None:
        raise AppError(
            "INVALID_REQUEST",
            "A worksheet can only be chosen for .xlsx files.",
            status_code=400,
            details={},
        )


def plan_ingestion(
    content: bytes, extension: str, requested_worksheet: str | None
) -> IngestionPlan:
    """Validate `content` for analysis and decide how it will be read.

    Blocking (call from a worker thread for `.xlsx`). A workbook is inspected
    here, before any analysis exists, so a macro-enabled, malformed or
    over-limit workbook, or an ambiguous worksheet choice, is refused with a
    documented error rather than becoming a failed analysis.
    """
    require_worksheet_applies(extension, requested_worksheet)
    if extension == CSV_EXTENSION:
        return IngestionPlan(DatasetFormat.CSV, None)
    worksheets = inspect_workbook(content)
    return IngestionPlan(DatasetFormat.XLSX, choose_worksheet(worksheets, requested_worksheet))
