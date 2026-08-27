"""Secure CSV parser (ING-02).

Turns raw, untrusted CSV bytes into a `ParsedDataset` (`domain.parsing`,
`ING-01`) plus the actual row values, while enforcing the resource and
content-execution limits named in `docs/product-requirements.md` §7 and
`docs/security-threat-model.md` §3.1/§3.2.

Framework-independent: no FastAPI/SQLAlchemy/pydantic import, no network
I/O. Stdlib only (`csv`, `io`, `hashlib`, `re`, `dataclasses`). No cell
value is ever executed, evaluated, or treated as a formula, script, or
command — everything is read as literal text.

This module does not construct `domain.parsing.Dataset` (storage-layer
concerns such as `stored_filename`/`storage_location` are out of scope
here — see the work package's Provenance for the disclosed rationale) and
does not implement any sampling strategy: the returned
`ParsedDataset.sampling` is always `SamplingScope.FULL`. A file whose
data-row count exceeds `limits.max_rows` is rejected outright rather than
silently sampled.
"""

from __future__ import annotations

import csv
import hashlib
import io
import re
from dataclasses import dataclass
from typing import Final

from ..domain.parsing import (
    DatasetFormat,
    ParsedDataset,
    ParsingWarning,
    SampleMetadata,
    SamplingScope,
)
from ..domain.value_objects import ColumnReference, RowReference

_DELIMITER_CANDIDATES: Final[tuple[str, ...]] = (",", ";", "\t", "|")
_DELIMITER_SNIFF_PREFIX_CHARS: Final[int] = 8192
_INTERNAL_KEY_INVALID_CHARS: Final[re.Pattern[str]] = re.compile(r"[^a-z0-9]+")


class CsvParseError(ValueError):
    """Raised when CSV content cannot be safely parsed at all.

    Reserved for cases where producing a partial or truncated dataset
    would silently misrepresent the source data: empty content,
    undecodable bytes, a zero-column header, and any of
    `CsvParseLimits`' `max_bytes`/`max_rows`/`max_columns` being
    exceeded. Every other malformed-but-recoverable condition (ragged
    rows, duplicate/empty column names, over-long column names/field
    values) is instead recorded as a `ParsingWarning` on the returned
    `ParsedDataset`.
    """


@dataclass(frozen=True, slots=True)
class CsvParseLimits:
    """Resource limits enforced while parsing (`docs/product-requirements.md`
    §7, `docs/security-threat-model.md` §3.1).

    Field names and defaults mirror the existing `Settings` fields
    (`config.py`, `WP-002`: `max_file_size_mb`, `max_rows`, `max_columns`,
    `max_column_name_length`, `max_text_value_length_for_analysis`)
    without importing `Settings`/pydantic, so this module stays a pure,
    framework-independent, directly testable function. A caller
    constructs `CsvParseLimits` from `Settings` when wiring this parser
    into the application.
    """

    max_bytes: int = 100 * 1024 * 1024
    max_rows: int = 1_000_000
    max_columns: int = 500
    max_column_name_length: int = 256
    max_field_length: int = 10_000


@dataclass(frozen=True, slots=True)
class CsvParseResult:
    """The result of successfully parsing CSV content.

    `rows` is a plain tuple of tuples (one tuple per data row, one
    `str | None` per column, in header order) — a disclosed, reversible
    scoping decision: `docs/domain-model.md` §6's `ParsedDataset` field
    list (fixed by `ING-01`) has no field for actual cell values, and
    `PROF-01` ("versioned dataset, column, and evidence models") is
    chartered to define any more structured raw-data-access contract
    profiling/detectors actually need.

    `content_hash` (SHA-256 hex digest) and `byte_size` are intrinsic,
    deterministic facts about the supplied bytes, provided so a future
    ingestion/upload package can assemble a `domain.parsing.Dataset`
    without this module guessing at storage-layer values.
    """

    parsed_dataset: ParsedDataset
    rows: tuple[tuple[str | None, ...], ...]
    content_hash: str
    byte_size: int


def parse_csv(content: bytes, *, limits: CsvParseLimits | None = None) -> CsvParseResult:
    """Parse raw CSV bytes into a `CsvParseResult`.

    Raises `CsvParseError` for the fatal cases documented on that
    exception. All other malformed-but-recoverable input is handled by
    padding/truncating/renaming plus a namespaced `ParsingWarning` on the
    returned `ParsedDataset.parsing_warnings`.
    """
    if limits is None:
        limits = CsvParseLimits()

    if not content:
        raise CsvParseError("CSV content is empty")
    if len(content) > limits.max_bytes:
        raise CsvParseError(
            f"CSV content size ({len(content)} bytes) exceeds the {limits.max_bytes}-byte limit"
        )

    content_hash = hashlib.sha256(content).hexdigest()
    byte_size = len(content)

    try:
        text = content.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise CsvParseError("CSV content is not valid UTF-8") from exc

    delimiter = _detect_delimiter(text)

    # Keep well above the smallest configurable `max_field_length` (and
    # never below Python's own historical default) so a deliberately long
    # field is truncated by this module's own bounded logic below rather
    # than aborting the whole parse with a raw `_csv.Error`.
    csv.field_size_limit(max(limits.max_field_length * 4, 131_072))

    reader = csv.reader(io.StringIO(text), delimiter=delimiter)

    try:
        header_row = next(reader, None)
    except csv.Error as exc:
        raise CsvParseError(f"CSV header row could not be read: {exc}") from exc

    if header_row is None or len(header_row) == 0:
        raise CsvParseError("CSV content has no header row with at least one column")
    if len(header_row) > limits.max_columns:
        raise CsvParseError(
            f"CSV header has {len(header_row)} columns, exceeding the "
            f"{limits.max_columns}-column limit"
        )

    columns, warnings = _build_columns(header_row, limits)
    expected_field_count = len(header_row)

    data_rows: list[tuple[str | None, ...]] = []
    row_references: list[RowReference] = []

    try:
        for row_number, raw_row in enumerate(reader):
            if row_number >= limits.max_rows:
                raise CsvParseError(f"CSV content has more than {limits.max_rows} data rows")
            row, row_warnings = _normalize_row(raw_row, expected_field_count, row_number, limits)
            data_rows.append(row)
            row_references.append(RowReference(row_number=row_number))
            warnings.extend(row_warnings)
    except csv.Error as exc:
        raise CsvParseError(f"CSV data could not be read: {exc}") from exc

    row_count = len(data_rows)
    sampling = SampleMetadata(
        scope=SamplingScope.FULL, population_size=row_count, sample_size=row_count
    )

    parsed_dataset = ParsedDataset(
        columns=tuple(columns),
        row_count=row_count,
        format=DatasetFormat.CSV,
        worksheets=(),
        parsing_warnings=tuple(warnings),
        sampling=sampling,
        row_references=tuple(row_references),
    )

    return CsvParseResult(
        parsed_dataset=parsed_dataset,
        rows=tuple(data_rows),
        content_hash=content_hash,
        byte_size=byte_size,
    )


def _detect_delimiter(text: str) -> str:
    """Detect the delimiter from a bounded prefix of the content.

    Considers only the first line of the first `_DELIMITER_SNIFF_PREFIX_CHARS`
    characters and a small fixed candidate set, defaulting to comma when
    inconclusive. Deliberately not an unbounded `csv.Sniffer` scan of the
    whole file — avoids the "expensive regex/pattern" resource-exhaustion
    class named in `docs/security-threat-model.md` §3.1.
    """
    prefix = text[:_DELIMITER_SNIFF_PREFIX_CHARS]
    lines = prefix.splitlines()
    first_line = lines[0] if lines else ""

    best_delimiter = ","
    best_count = 0
    for candidate in _DELIMITER_CANDIDATES:
        count = first_line.count(candidate)
        if count > best_count:
            best_count = count
            best_delimiter = candidate
    return best_delimiter


def _normalize_internal_key(name: str) -> str:
    """Derive a normalized internal key from a display name.

    Lowercases, collapses any run of non-alphanumeric characters to a
    single underscore, and strips leading/trailing underscores. Falls
    back to `"column"` when nothing alphanumeric remains.
    """
    lowered = name.strip().lower()
    normalized = _INTERNAL_KEY_INVALID_CHARS.sub("_", lowered).strip("_")
    return normalized or "column"


def _build_columns(
    header_row: list[str], limits: CsvParseLimits
) -> tuple[list[ColumnReference], list[ParsingWarning]]:
    columns: list[ColumnReference] = []
    warnings: list[ParsingWarning] = []
    used_keys: set[str] = set()

    for ordinal, raw_name in enumerate(header_row):
        display_name = raw_name
        empty_name = not display_name
        if empty_name:
            display_name = f"column_{ordinal}"

        truncated_name = False
        if len(display_name) > limits.max_column_name_length:
            display_name = display_name[: limits.max_column_name_length]
            truncated_name = True

        base_key = _normalize_internal_key(display_name)
        internal_key = base_key
        duplicate = False
        suffix = 2
        while internal_key in used_keys:
            duplicate = True
            internal_key = f"{base_key}_{suffix}"
            suffix += 1
        used_keys.add(internal_key)

        column = ColumnReference(
            original_name=display_name, internal_key=internal_key, ordinal=ordinal
        )
        columns.append(column)

        if empty_name:
            warnings.append(
                ParsingWarning(
                    code="parsing.empty_column_name",
                    message=(
                        f"Column {ordinal} had an empty header cell; assigned '{display_name}'"
                    ),
                    column=column,
                )
            )
        if truncated_name:
            warnings.append(
                ParsingWarning(
                    code="parsing.column_name_truncated",
                    message=(
                        f"Column {ordinal} name exceeded "
                        f"{limits.max_column_name_length} characters and was truncated"
                    ),
                    column=column,
                )
            )
        if duplicate:
            warnings.append(
                ParsingWarning(
                    code="parsing.duplicate_column_name",
                    message=(
                        f"Column {ordinal} internal key collided with an earlier "
                        f"column; renamed to '{internal_key}'"
                    ),
                    column=column,
                )
            )

    return columns, warnings


def _normalize_row(
    raw_row: list[str],
    expected_field_count: int,
    row_number: int,
    limits: CsvParseLimits,
) -> tuple[tuple[str | None, ...], list[ParsingWarning]]:
    warnings: list[ParsingWarning] = []
    fields: list[str | None] = list(raw_row)

    if len(fields) != expected_field_count:
        warnings.append(
            ParsingWarning(
                code="parsing.ragged_row",
                message=(
                    f"Row {row_number} had {len(raw_row)} fields, expected {expected_field_count}"
                ),
                row=RowReference(row_number=row_number),
            )
        )
        if len(fields) < expected_field_count:
            fields.extend([None] * (expected_field_count - len(fields)))
        else:
            fields = fields[:expected_field_count]

    truncated = False
    normalized_fields: list[str | None] = []
    for value in fields:
        if value is not None and len(value) > limits.max_field_length:
            normalized_fields.append(value[: limits.max_field_length])
            truncated = True
        else:
            normalized_fields.append(value)

    if truncated:
        warnings.append(
            ParsingWarning(
                code="parsing.field_value_truncated",
                message=(
                    f"Row {row_number} had a field value exceeding "
                    f"{limits.max_field_length} characters; truncated"
                ),
                row=RowReference(row_number=row_number),
            )
        )

    return tuple(normalized_fields), warnings
