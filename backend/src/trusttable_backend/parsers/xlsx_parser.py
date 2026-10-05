"""Secure XLSX parser (ING-03).

Turns raw, untrusted XLSX bytes into a `ParsedDataset` (`domain.parsing`,
`ING-01`) plus the actual row values for one selected worksheet, while
enforcing the resource and content-execution limits named in
`docs/product-requirements.md` §7 and `docs/security-threat-model.md`
§3.1/§3.2.

Framework-independent: no FastAPI/SQLAlchemy/pydantic import, no network
I/O, no third-party dependency. Standard library only (`zipfile`,
`xml.parsers.expat`, `hashlib`, `re`, `posixpath`).

Security design:

* **Nothing is executed or evaluated.** Formula text (`<f>`) is discarded;
  only the cached result stored by the producing application (`<v>`) is
  read, and every value is kept as literal text. Formatting, styles,
  charts, drawings, defined names and external links are never read.
* **Macro-enabled workbooks are rejected**, by package content (a VBA
  project part, macro sheets, a macro-enabled content type) and not by file
  extension.
* **Encrypted workbooks are rejected** (an encrypted OOXML file is an OLE
  compound file, not a zip; zip-level encryption flags are rejected too).
* **Expansion is bounded by counting, not by trusting headers.** Declared
  zip sizes are checked early, but every byte actually decompressed is also
  counted against one shared budget while it is read.
* **XML is parsed with expat directly** and any DOCTYPE or entity
  declaration is rejected before it can be expanded, which removes entity
  expansion and external-entity attacks. Element nesting depth is capped.
* **Zip entries are never extracted.** Entry names are still validated
  (traversal, absolute paths, backslashes, NUL, duplicates) and relationship
  targets must resolve to an entry inside the package.

Reading a worksheet follows the CSV parser's conventions: the first row
holding data is the header, column naming and header warnings come from the
CSV parser's shared helper, and `ParsedDataset.sampling` is always
`SamplingScope.FULL`. A workbook exceeding a limit is rejected outright
rather than silently sampled. Every worksheet is scanned within the same
limits so `WorksheetMetadata` can report real row and column counts; only
the selected worksheet's values are returned. Numbers are returned as the
text stored in the file: dates stored as serial numbers are not interpreted
(formatting is ignored by design).
"""

from __future__ import annotations

import hashlib
import io
import posixpath
import re
import zipfile
import zlib
from dataclasses import dataclass
from typing import Any, Final
from xml.parsers import expat

from ..domain.parsing import (
    DatasetFormat,
    ParsedDataset,
    ParsingWarning,
    SampleMetadata,
    SamplingScope,
    WorksheetMetadata,
)
from ..domain.value_objects import RowReference
from .csv_parser import CsvParseLimits, _build_columns

_OLE_MAGIC: Final[bytes] = bytes.fromhex("D0CF11E0A1B11AE1")
_CHUNK_BYTES: Final[int] = 64 * 1024
_MAX_XML_DEPTH: Final[int] = 64
_MAX_EXCEL_ROW: Final[int] = 1_048_576
_MAX_SHEET_NAME_LENGTH: Final[int] = 255
_ALLOWED_COMPRESSION: Final[frozenset[int]] = frozenset({zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED})
_CELL_REF: Final[re.Pattern[str]] = re.compile(r"([A-Z]{1,3})([0-9]{1,7})")

_CONTENT_TYPES_PART: Final[str] = "[Content_Types].xml"
_WORKBOOK_PART: Final[str] = "xl/workbook.xml"
_WORKBOOK_RELS_PART: Final[str] = "xl/_rels/workbook.xml.rels"


class XlsxParseError(ValueError):
    """Raised when XLSX content cannot be safely parsed at all.

    Reserved for cases where reading the workbook would be unsafe or would
    silently misrepresent the source data: not a zip package, an encrypted
    or macro-enabled workbook, malformed or hostile package structure or
    XML, an unknown requested worksheet, a worksheet without any data, and
    any `XlsxParseLimits` field being exceeded. Every other recoverable
    condition (empty/duplicate/over-long headers, cells beyond the header,
    over-long values, formulas without a cached value) is recorded as a
    `ParsingWarning` on the returned `ParsedDataset`.

    `code` classifies the failure using the API's documented error codes
    (`docs/api-specification.md` §14) so a caller can map it without
    parsing message text: `MALFORMED_FILE` (the default),
    `MACRO_ENABLED_FILE`, `WORKBOOK_EXPANSION_LIMIT`,
    `CELL_LIMIT_EXCEEDED`, or `WORKSHEET_NOT_FOUND`.
    """

    code: str = "MALFORMED_FILE"


class XlsxMacroError(XlsxParseError):
    """The workbook carries macro content and is never read as data."""

    code = "MACRO_ENABLED_FILE"


class XlsxExpansionError(XlsxParseError):
    """A size, entry-count, worksheet-count or decompression limit was hit."""

    code = "WORKBOOK_EXPANSION_LIMIT"


class XlsxCellLimitError(XlsxParseError):
    """A row, column or cell limit was hit."""

    code = "CELL_LIMIT_EXCEEDED"


class XlsxWorksheetError(XlsxParseError):
    """The requested worksheet does not exist (or none can be defaulted)."""

    code = "WORKSHEET_NOT_FOUND"


@dataclass(frozen=True, slots=True)
class XlsxParseLimits:
    """Resource limits enforced while parsing (`docs/product-requirements.md`
    §7, `docs/security-threat-model.md` §3.1).

    Defaults mirror the documented local defaults. `max_bytes` is the
    compressed upload size, `max_uncompressed_bytes` the total decompressed
    size of every package part read, and `max_cells` the number of `<c>`
    elements in any one worksheet and the rows-by-columns grid kept for it.
    """

    max_bytes: int = 100 * 1024 * 1024
    max_uncompressed_bytes: int = 500 * 1024 * 1024
    max_entries: int = 10_000
    max_worksheets: int = 20
    max_rows: int = 1_000_000
    max_columns: int = 500
    max_cells: int = 50_000_000
    max_column_name_length: int = 256
    max_field_length: int = 10_000


@dataclass(frozen=True, slots=True)
class XlsxParseResult:
    """The result of successfully parsing XLSX content.

    `rows` follows `CsvParseResult.rows`: one tuple per data row of the
    selected worksheet, one `str | None` per column in header order.
    `selected_worksheet` is the name to record as
    `domain.parsing.Dataset.selected_worksheet`.
    """

    parsed_dataset: ParsedDataset
    rows: tuple[tuple[str | None, ...], ...]
    content_hash: str
    byte_size: int
    selected_worksheet: str


@dataclass(frozen=True, slots=True)
class XlsxWorksheetInfo:
    """One worksheet of a workbook: its name and whether it is visible."""

    name: str
    visible: bool


def inspect_xlsx_worksheets(
    content: bytes, *, limits: XlsxParseLimits | None = None
) -> tuple[XlsxWorksheetInfo, ...]:
    """List a workbook's worksheets without reading any worksheet's cells.

    Applies the same package validation as `parse_xlsx` (size, entry,
    macro, encryption, traversal, DOCTYPE and decompression-budget checks)
    but reads only the content-types, workbook and relationship parts, so
    its cost is bounded by the package structure and not by the amount of
    data in any worksheet. Raises `XlsxParseError` like `parse_xlsx`.
    """
    if limits is None:
        limits = XlsxParseLimits()
    with _open_package(content, limits) as archive:
        names = _validate_entries(archive.infolist(), limits)
        budget = _Budget(limits.max_uncompressed_bytes)
        _check_content_types(archive, names, budget)
        entries = _read_worksheet_entries(archive, names, limits, budget, [])
    return tuple(XlsxWorksheetInfo(name=entry.name, visible=entry.visible) for entry in entries)


def _open_package(content: bytes, limits: XlsxParseLimits) -> zipfile.ZipFile:
    if not content:
        raise XlsxParseError("XLSX content is empty")
    if len(content) > limits.max_bytes:
        raise XlsxExpansionError(
            f"XLSX content size ({len(content)} bytes) exceeds the {limits.max_bytes}-byte limit"
        )
    if content.startswith(_OLE_MAGIC):
        raise XlsxParseError(
            "XLSX content is an OLE compound file (an encrypted or legacy binary "
            "workbook), which is not supported"
        )
    try:
        return zipfile.ZipFile(io.BytesIO(content))
    except (zipfile.BadZipFile, zipfile.LargeZipFile, EOFError, OSError) as exc:
        raise XlsxParseError("XLSX content is not a valid zip package") from exc


def parse_xlsx(
    content: bytes,
    *,
    worksheet: str | None = None,
    limits: XlsxParseLimits | None = None,
) -> XlsxParseResult:
    """Parse raw XLSX bytes into an `XlsxParseResult`.

    `worksheet` selects a worksheet by exact name; when omitted the first
    visible worksheet is used. Raises `XlsxParseError` for the fatal cases
    documented on that exception.
    """
    if limits is None:
        limits = XlsxParseLimits()

    archive = _open_package(content, limits)
    content_hash = hashlib.sha256(content).hexdigest()
    byte_size = len(content)

    with archive:
        names = _validate_entries(archive.infolist(), limits)
        budget = _Budget(limits.max_uncompressed_bytes)
        warnings: list[ParsingWarning] = []

        _check_content_types(archive, names, budget)
        entries = _read_worksheet_entries(archive, names, limits, budget, warnings)
        shared_strings = _read_shared_strings(archive, names, limits, budget)

        selected = _select_worksheet(entries, worksheet)
        if any(name.startswith("xl/externallinks/") for name in (n.lower() for n in names)):
            warnings.append(
                ParsingWarning(
                    code="parsing.xlsx_external_links_ignored",
                    message="The workbook contains external links, which are never followed",
                )
            )

        results: list[_SheetResult] = []
        for entry in entries:
            results.append(
                _parse_sheet(
                    archive,
                    entry.path,
                    shared_strings,
                    limits,
                    budget,
                    collect=entry is selected,
                )
            )

    selected_result = results[entries.index(selected)]
    if selected_result.header is None:
        raise XlsxParseError(f"XLSX worksheet '{selected.name}' has no header row with data")

    csv_limits = CsvParseLimits(
        max_bytes=limits.max_bytes,
        max_rows=limits.max_rows,
        max_columns=limits.max_columns,
        max_column_name_length=limits.max_column_name_length,
        max_field_length=limits.max_field_length,
    )
    columns, header_warnings = _build_columns(
        [cell if cell is not None else "" for cell in selected_result.header], csv_limits
    )

    row_count = selected_result.row_total
    worksheets = tuple(
        WorksheetMetadata(
            name=entry.name,
            index=index,
            row_count=result.row_total,
            column_count=result.column_count,
            is_selected=entry is selected,
        )
        for index, (entry, result) in enumerate(zip(entries, results, strict=True))
    )
    parsed_dataset = ParsedDataset(
        columns=tuple(columns),
        row_count=row_count,
        format=DatasetFormat.XLSX,
        worksheets=worksheets,
        parsing_warnings=tuple(header_warnings + selected_result.warnings + warnings),
        sampling=SampleMetadata(
            scope=SamplingScope.FULL, population_size=row_count, sample_size=row_count
        ),
        row_references=tuple(RowReference(row_number=index) for index in range(row_count)),
    )
    return XlsxParseResult(
        parsed_dataset=parsed_dataset,
        rows=tuple(selected_result.rows),
        content_hash=content_hash,
        byte_size=byte_size,
        selected_worksheet=selected.name,
    )


# ---------------------------------------------------------------------------
# Package-level validation
# ---------------------------------------------------------------------------


class _Budget:
    """Shared count of decompressed bytes still allowed to be read."""

    def __init__(self, total: int) -> None:
        self._total = total
        self.remaining = total

    def consume(self, count: int) -> None:
        self.remaining -= count
        if self.remaining < 0:
            raise XlsxExpansionError(
                f"XLSX decompressed content exceeds the {self._total}-byte limit"
            )


def _validate_entries(infos: list[zipfile.ZipInfo], limits: XlsxParseLimits) -> set[str]:
    if len(infos) > limits.max_entries:
        raise XlsxExpansionError(
            f"XLSX package has {len(infos)} entries, exceeding the {limits.max_entries}-entry limit"
        )

    names: set[str] = set()
    declared_total = 0
    for info in infos:
        name = info.filename
        if not name or "\x00" in name or "\\" in name or name.startswith("/"):
            raise XlsxParseError("XLSX package contains an unsafe entry name")
        if ".." in name.split("/") or re.match(r"^[A-Za-z]:", name):
            raise XlsxParseError("XLSX package contains an entry name that escapes the package")
        if name in names:
            raise XlsxParseError("XLSX package contains duplicate entry names")
        names.add(name)

        if info.flag_bits & 0x1:
            raise XlsxParseError("XLSX package contains an encrypted entry")
        if info.compress_type not in _ALLOWED_COMPRESSION:
            raise XlsxParseError("XLSX package uses an unsupported compression method")

        lowered = name.lower()
        if "vbaproject" in lowered or "/macrosheets/" in lowered:
            raise XlsxMacroError(
                "XLSX package contains macro content; macro-enabled workbooks are rejected"
            )

        declared_total += info.file_size
        if declared_total > limits.max_uncompressed_bytes:
            raise XlsxExpansionError(
                f"XLSX package declares more than {limits.max_uncompressed_bytes} "
                "uncompressed bytes"
            )
    return names


def _check_content_types(archive: zipfile.ZipFile, names: set[str], budget: _Budget) -> None:
    if _CONTENT_TYPES_PART not in names:
        raise XlsxParseError("XLSX package has no [Content_Types].xml part")
    handler = _ContentTypesHandler()
    parser = _new_parser()
    handler.attach(parser)
    _feed_part(archive, _CONTENT_TYPES_PART, parser, budget)


def _read_worksheet_entries(
    archive: zipfile.ZipFile,
    names: set[str],
    limits: XlsxParseLimits,
    budget: _Budget,
    warnings: list[ParsingWarning],
) -> list[_SheetEntry]:
    if _WORKBOOK_PART not in names or _WORKBOOK_RELS_PART not in names:
        raise XlsxParseError("XLSX package has no workbook part")

    relationships = _RelationshipsHandler()
    parser = _new_parser()
    relationships.attach(parser)
    _feed_part(archive, _WORKBOOK_RELS_PART, parser, budget)
    relationships_by_id = relationships.relationships

    workbook = _WorkbookHandler()
    parser = _new_parser()
    workbook.attach(parser)
    _feed_part(archive, _WORKBOOK_PART, parser, budget)

    entries: list[_SheetEntry] = []
    ignored = 0
    seen_names: set[str] = set()
    for name, state, relationship_id in workbook.sheets:
        if not name or len(name) > _MAX_SHEET_NAME_LENGTH:
            raise XlsxParseError("XLSX workbook has a worksheet with an invalid name")
        relationship = relationships_by_id.get(relationship_id)
        if relationship is None:
            raise XlsxParseError(f"XLSX worksheet '{name}' has no matching relationship")
        kind, target, external = relationship
        if kind in {"macrosheet", "intlmacrosheet"}:
            raise XlsxMacroError("XLSX workbook contains a macro sheet; it is rejected")
        if kind != "worksheet":
            ignored += 1
            continue
        if external:
            raise XlsxParseError(f"XLSX worksheet '{name}' points outside the package")
        if name.casefold() in seen_names:
            raise XlsxParseError("XLSX workbook has duplicate worksheet names")
        seen_names.add(name.casefold())
        path = _resolve_target(target)
        if path not in names:
            raise XlsxParseError(f"XLSX worksheet '{name}' refers to a missing part")
        entries.append(_SheetEntry(name=name, path=path, visible=state in {"", "visible"}))
        if len(entries) > limits.max_worksheets:
            raise XlsxExpansionError(
                f"XLSX workbook has more than {limits.max_worksheets} worksheets"
            )

    if not entries:
        raise XlsxParseError("XLSX workbook has no worksheets")
    if ignored:
        warnings.append(
            ParsingWarning(
                code="parsing.xlsx_non_worksheet_ignored",
                message=f"{ignored} non-worksheet sheet(s) (for example chart sheets) were ignored",
            )
        )
    return entries


def _resolve_target(target: str) -> str:
    if target.startswith("/"):
        path = posixpath.normpath(target[1:])
    else:
        path = posixpath.normpath(posixpath.join("xl", target))
    if path.startswith("..") or path.startswith("/"):
        raise XlsxParseError("XLSX relationship target escapes the package")
    return path


def _read_shared_strings(
    archive: zipfile.ZipFile, names: set[str], limits: XlsxParseLimits, budget: _Budget
) -> list[str]:
    relationships = _RelationshipsHandler()
    parser = _new_parser()
    relationships.attach(parser)
    # The relationships part was validated by `_read_worksheet_entries`; it is
    # read again only to locate the shared-strings part, so its (small) size is
    # counted again against the budget like every other byte read.
    _feed_part(archive, _WORKBOOK_RELS_PART, parser, budget)

    path: str | None = None
    for kind, target, external in relationships.relationships.values():
        if kind == "sharedstrings" and not external:
            path = _resolve_target(target)
            break
    if path is None or path not in names:
        return []

    handler = _SharedStringsHandler(limits)
    parser = _new_parser()
    handler.attach(parser)
    _feed_part(archive, path, parser, budget)
    return handler.strings


@dataclass(frozen=True, slots=True)
class _SheetEntry:
    name: str
    path: str
    visible: bool


def _select_worksheet(entries: list[_SheetEntry], requested: str | None) -> _SheetEntry:
    if requested is not None:
        for entry in entries:
            if entry.name == requested:
                return entry
        available = ", ".join(repr(entry.name) for entry in entries)
        raise XlsxWorksheetError(
            f"XLSX worksheet {requested!r} was not found; available: {available}"
        )
    for entry in entries:
        if entry.visible:
            return entry
    raise XlsxWorksheetError("XLSX workbook has no visible worksheet; select one by name")


# ---------------------------------------------------------------------------
# Bounded, entity-free XML reading
# ---------------------------------------------------------------------------


def _reject_doctype(*_args: object) -> None:
    raise XlsxParseError("XLSX XML contains a DOCTYPE declaration, which is rejected")


def _reject_entity(*_args: object) -> None:
    raise XlsxParseError("XLSX XML contains an entity declaration, which is rejected")


def _new_parser() -> Any:
    parser = expat.ParserCreate(namespace_separator="|")
    parser.buffer_text = True
    parser.StartDoctypeDeclHandler = _reject_doctype
    parser.EntityDeclHandler = _reject_entity
    return parser


def _feed_part(archive: zipfile.ZipFile, name: str, parser: Any, budget: _Budget) -> None:
    """Stream one package part into `parser`, counting every decompressed byte."""
    try:
        with archive.open(name) as stream:
            while True:
                chunk = stream.read(_CHUNK_BYTES)
                if not chunk:
                    break
                budget.consume(len(chunk))
                parser.Parse(chunk, False)
        parser.Parse(b"", True)
    except expat.ExpatError as exc:
        raise XlsxParseError(f"XLSX part '{name}' is not well-formed XML") from exc
    except (zipfile.BadZipFile, zlib.error, EOFError, NotImplementedError, RuntimeError) as exc:
        raise XlsxParseError(f"XLSX part '{name}' could not be read") from exc


def _local(raw_name: str) -> str:
    return raw_name.rpartition("|")[2]


class _XmlHandler:
    """Expat handler base: local names, a depth cap, and no-op hooks."""

    def __init__(self) -> None:
        self._depth = 0

    def attach(self, parser: Any) -> None:
        parser.StartElementHandler = self._on_start
        parser.EndElementHandler = self._on_end
        parser.CharacterDataHandler = self.chars

    def _on_start(self, raw_name: str, attrs: dict[str, str]) -> None:
        self._depth += 1
        if self._depth > _MAX_XML_DEPTH:
            raise XlsxParseError(f"XLSX XML is nested deeper than {_MAX_XML_DEPTH} levels")
        self.start(_local(raw_name), attrs)

    def _on_end(self, raw_name: str) -> None:
        self.end(_local(raw_name))
        self._depth -= 1

    def start(self, name: str, attrs: dict[str, str]) -> None:
        pass

    def end(self, name: str) -> None:
        pass

    def chars(self, data: str) -> None:
        pass


class _ContentTypesHandler(_XmlHandler):
    def start(self, name: str, attrs: dict[str, str]) -> None:
        if name in {"Default", "Override"}:
            content_type = attrs.get("ContentType", "").lower()
            if "macroenabled" in content_type or "vbaproject" in content_type:
                raise XlsxMacroError(
                    "XLSX content types declare macro content; macro-enabled workbooks are rejected"
                )


class _RelationshipsHandler(_XmlHandler):
    def __init__(self) -> None:
        super().__init__()
        # id -> (lower-cased relationship kind, target, is_external)
        self.relationships: dict[str, tuple[str, str, bool]] = {}

    def start(self, name: str, attrs: dict[str, str]) -> None:
        if name != "Relationship":
            return
        relationship_id = attrs.get("Id", "")
        kind = attrs.get("Type", "").rpartition("/")[2].lower()
        external = attrs.get("TargetMode", "").lower() == "external"
        self.relationships[relationship_id] = (kind, attrs.get("Target", ""), external)


class _WorkbookHandler(_XmlHandler):
    def __init__(self) -> None:
        super().__init__()
        # (name, state, relationship id)
        self.sheets: list[tuple[str, str, str]] = []

    def start(self, name: str, attrs: dict[str, str]) -> None:
        if name != "sheet":
            return
        relationship_id = ""
        for key, value in attrs.items():
            namespace, _, local = key.rpartition("|")
            if local == "id" and namespace.endswith("relationships"):
                relationship_id = value
        self.sheets.append((attrs.get("name", ""), attrs.get("state", ""), relationship_id))


class _SharedStringsHandler(_XmlHandler):
    def __init__(self, limits: XlsxParseLimits) -> None:
        super().__init__()
        self._limits = limits
        self._cap = limits.max_field_length + 1
        self.strings: list[str] = []
        self._in_si = False
        self._in_t = False
        self._in_phonetic = False
        self._parts: list[str] = []
        self._length = 0

    def start(self, name: str, attrs: dict[str, str]) -> None:
        if name == "si":
            self._in_si = True
            self._parts = []
            self._length = 0
        elif name == "rPh":
            self._in_phonetic = True
        elif name == "t" and self._in_si and not self._in_phonetic:
            self._in_t = True

    def chars(self, data: str) -> None:
        if self._in_t and self._length < self._cap:
            self._parts.append(data)
            self._length += len(data)

    def end(self, name: str) -> None:
        if name == "t":
            self._in_t = False
        elif name == "rPh":
            self._in_phonetic = False
        elif name == "si":
            self._in_si = False
            self.strings.append("".join(self._parts)[: self._cap])
            if len(self.strings) > self._limits.max_cells:
                raise XlsxCellLimitError(
                    f"XLSX shared strings exceed the {self._limits.max_cells}-entry limit"
                )


# ---------------------------------------------------------------------------
# Worksheet reading
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class _SheetResult:
    header: list[str | None] | None
    rows: list[tuple[str | None, ...]]
    row_total: int
    column_count: int
    warnings: list[ParsingWarning]


def _parse_sheet(
    archive: zipfile.ZipFile,
    path: str,
    shared_strings: list[str],
    limits: XlsxParseLimits,
    budget: _Budget,
    *,
    collect: bool,
) -> _SheetResult:
    handler = _SheetHandler(shared_strings, limits, collect=collect)
    parser = _new_parser()
    handler.attach(parser)
    _feed_part(archive, path, parser, budget)
    return handler.result()


def _column_index(reference: str) -> int:
    match = _CELL_REF.fullmatch(reference.upper())
    if match is None:
        raise XlsxParseError("XLSX worksheet contains an invalid cell reference")
    index = 0
    for letter in match.group(1):
        index = index * 26 + (ord(letter) - ord("A") + 1)
    return index - 1


class _SheetHandler(_XmlHandler):
    """Streams one worksheet into a header plus (optionally) data rows.

    Rows are positioned by their `r` attribute: missing rows between data
    rows become blank rows, trailing blank rows are dropped. With
    `collect=False` (worksheets that are not selected) values are not kept,
    but every limit is still enforced and rows and columns are still counted.
    """

    def __init__(
        self, shared_strings: list[str], limits: XlsxParseLimits, *, collect: bool
    ) -> None:
        super().__init__()
        self._shared = shared_strings
        self._limits = limits
        self._collect = collect
        self._cap = limits.max_field_length + 1

        self._header: list[str | None] | None = None
        self._ncols = 0
        self._rows: list[tuple[str | None, ...]] = []
        self._row_total = 0
        self._warnings: list[ParsingWarning] = []
        self._cells_seen = 0
        self._last_row_index = 0
        self._pending_blank = 0
        self._formula_without_value = 0
        self._error_values = 0

        self._in_row = False
        self._row_cells: dict[int, str] = {}
        self._next_col = 0

        self._in_cell = False
        self._col = 0
        self._cell_type = "n"
        self._has_formula = False
        self._in_v = False
        self._seen_v = False
        self._v_parts: list[str] = []
        self._v_len = 0
        self._in_is = False
        self._in_is_t = False
        self._in_phonetic = False
        self._seen_is = False
        self._is_parts: list[str] = []
        self._is_len = 0

    # -- expat hooks ------------------------------------------------------

    def start(self, name: str, attrs: dict[str, str]) -> None:
        if name == "row":
            self._start_row(attrs)
        elif name == "c" and self._in_row:
            self._start_cell(attrs)
        elif not self._in_cell:
            return
        elif name == "v":
            self._in_v = True
            self._seen_v = True
        elif name == "is":
            self._in_is = True
            self._seen_is = True
        elif name == "rPh":
            self._in_phonetic = True
        elif name == "t" and self._in_is and not self._in_phonetic:
            self._in_is_t = True
        elif name == "f":
            self._has_formula = True

    def chars(self, data: str) -> None:
        if self._in_v and self._v_len < self._cap:
            self._v_parts.append(data)
            self._v_len += len(data)
        elif self._in_is_t and self._is_len < self._cap:
            self._is_parts.append(data)
            self._is_len += len(data)

    def end(self, name: str) -> None:
        if name == "v":
            self._in_v = False
        elif name == "t":
            self._in_is_t = False
        elif name == "rPh":
            self._in_phonetic = False
        elif name == "is":
            self._in_is = False
        elif name == "c" and self._in_cell:
            self._finish_cell()
        elif name == "row" and self._in_row:
            self._finish_row()

    # -- rows and cells ---------------------------------------------------

    def _start_row(self, attrs: dict[str, str]) -> None:
        raw_index = attrs.get("r")
        if raw_index is None:
            index = self._last_row_index + 1
        else:
            if not raw_index.isascii() or not raw_index.isdigit() or len(raw_index) > 7:
                raise XlsxParseError("XLSX worksheet contains an invalid row index")
            index = int(raw_index)
        if index <= self._last_row_index or index > _MAX_EXCEL_ROW:
            raise XlsxParseError("XLSX worksheet rows are out of order or out of range")
        self._in_row = True
        self._row_index = index
        self._row_cells = {}
        self._next_col = 0

    def _start_cell(self, attrs: dict[str, str]) -> None:
        self._cells_seen += 1
        if self._cells_seen > self._limits.max_cells:
            raise XlsxCellLimitError(f"XLSX worksheet has more than {self._limits.max_cells} cells")
        reference = attrs.get("r")
        self._col = _column_index(reference) if reference is not None else self._next_col
        self._next_col = self._col + 1
        self._cell_type = attrs.get("t", "n")
        self._in_cell = True
        self._has_formula = False
        self._in_v = self._seen_v = False
        self._v_parts = []
        self._v_len = 0
        self._in_is = self._in_is_t = self._in_phonetic = self._seen_is = False
        self._is_parts = []
        self._is_len = 0

    def _finish_cell(self) -> None:
        self._in_cell = False
        value: str | None = None
        if self._seen_is:
            value = "".join(self._is_parts)[: self._cap]
        elif self._seen_v:
            raw = "".join(self._v_parts)[: self._cap]
            value = self._decode_value(raw)
        elif self._has_formula:
            self._formula_without_value += 1

        if value is None or value == "":
            return
        if self._col >= self._limits.max_columns:
            raise XlsxCellLimitError(
                f"XLSX worksheet has more than {self._limits.max_columns} columns"
            )
        self._row_cells[self._col] = value

    def _decode_value(self, raw: str) -> str | None:
        kind = self._cell_type
        if kind == "s":
            if not raw.isascii() or not raw.isdigit():
                raise XlsxParseError("XLSX worksheet has an invalid shared string index")
            index = int(raw)
            if index >= len(self._shared):
                raise XlsxParseError("XLSX worksheet has an invalid shared string index")
            return self._shared[index]
        if kind == "b":
            return {"1": "TRUE", "0": "FALSE"}.get(raw, raw)
        if kind == "e":
            self._error_values += 1
        return raw if raw != "" else None

    def _finish_row(self) -> None:
        self._in_row = False
        index = self._row_index
        cells = self._row_cells

        if self._header is None:
            if cells:
                self._ncols = max(cells) + 1
                self._header = [cells.get(i) for i in range(self._ncols)]
            self._last_row_index = index
            return

        self._pending_blank += index - self._last_row_index - 1
        self._last_row_index = index
        if not cells:
            self._pending_blank += 1
            return

        if self._pending_blank:
            self._add_rows(self._pending_blank)
            if self._collect:
                self._rows.extend([(None,) * self._ncols] * self._pending_blank)
            self._pending_blank = 0

        row_number = self._row_total
        self._add_rows(1)
        if not self._collect:
            return

        row: list[str | None] = [None] * self._ncols
        extra = False
        truncated = False
        for col, value in cells.items():
            if col >= self._ncols:
                extra = True
                continue
            if len(value) > self._limits.max_field_length:
                value = value[: self._limits.max_field_length]
                truncated = True
            row[col] = value
        if extra:
            self._warnings.append(
                ParsingWarning(
                    code="parsing.ragged_row",
                    message=(
                        f"Row {row_number} had cells beyond the {self._ncols}-column header; "
                        "extra cells were dropped"
                    ),
                    row=RowReference(row_number=row_number),
                )
            )
        if truncated:
            self._warnings.append(
                ParsingWarning(
                    code="parsing.field_value_truncated",
                    message=(
                        f"Row {row_number} had a field value exceeding "
                        f"{self._limits.max_field_length} characters; truncated"
                    ),
                    row=RowReference(row_number=row_number),
                )
            )
        self._rows.append(tuple(row))

    def _add_rows(self, count: int) -> None:
        total = self._row_total + count
        if total > self._limits.max_rows:
            raise XlsxCellLimitError(
                f"XLSX worksheet has more than {self._limits.max_rows} data rows"
            )
        if total * max(self._ncols, 1) > self._limits.max_cells:
            raise XlsxCellLimitError(
                f"XLSX worksheet grid exceeds the {self._limits.max_cells}-cell limit"
            )
        self._row_total = total

    def result(self) -> _SheetResult:
        if self._collect:
            if self._formula_without_value:
                self._warnings.append(
                    ParsingWarning(
                        code="parsing.xlsx_formula_without_cached_value",
                        message=(
                            f"{self._formula_without_value} formula cell(s) had no stored "
                            "result and were read as empty; formulas are never evaluated"
                        ),
                        count=self._formula_without_value,
                    )
                )
            if self._error_values:
                self._warnings.append(
                    ParsingWarning(
                        code="parsing.xlsx_error_value",
                        message=(
                            f"{self._error_values} cell(s) held a spreadsheet error value "
                            "and were read as that literal text"
                        ),
                        count=self._error_values,
                    )
                )
        return _SheetResult(
            header=self._header,
            rows=self._rows,
            row_total=self._row_total,
            column_count=self._ncols,
            warnings=self._warnings,
        )
