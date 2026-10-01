"""Tests for the secure XLSX parser (ING-03).

Workbooks are built in memory with `zipfile`, so every case, including the
hostile ones, is deterministic and needs no fixture files or third-party
spreadsheet library.
"""

from __future__ import annotations

import hashlib
import io
import struct
import zipfile
from collections.abc import Mapping, Sequence
from typing import Any
from xml.sax.saxutils import escape

import pytest

from trusttable_backend.domain.parsing import DatasetFormat, SamplingScope
from trusttable_backend.parsers import parse_csv, parse_xlsx
from trusttable_backend.parsers.xlsx_parser import (
    XlsxParseError,
    XlsxParseLimits,
    _Budget,
    _feed_part,
    _new_parser,
)

MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"

Cell = str | int | float | bool | None | tuple[Any, ...]
Rows = Sequence[Sequence[Cell]]


def _column_letters(index: int) -> str:
    letters = ""
    index += 1
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(ord("A") + remainder) + letters
    return letters


def _cell_xml(row: int, col: int, value: Cell, shared: list[str] | None) -> str:
    ref = f"{_column_letters(col)}{row}"
    if value is None:
        return ""
    if isinstance(value, bool):
        return f'<c r="{ref}" t="b"><v>{int(value)}</v></c>'
    if isinstance(value, int | float):
        return f'<c r="{ref}"><v>{value}</v></c>'
    if isinstance(value, tuple):
        kind = value[0]
        if kind == "formula":  # ("formula", text, cached or None)
            cached = "" if value[2] is None else f"<v>{escape(str(value[2]))}</v>"
            kind_attr = ' t="str"' if isinstance(value[2], str) else ""
            return f'<c r="{ref}"{kind_attr}><f>{escape(value[1])}</f>{cached}</c>'
        if kind == "error":
            return f'<c r="{ref}" t="e"><v>{escape(value[1])}</v></c>'
        raise AssertionError(kind)
    if shared is not None:
        shared.append(value)
        return f'<c r="{ref}" t="s"><v>{len(shared) - 1}</v></c>'
    return f'<c r="{ref}" t="inlineStr"><is><t>{escape(value)}</t></is></c>'


def sheet_xml(rows: Rows, shared: list[str] | None = None, first_row: int = 1) -> str:
    parts = [f'<worksheet xmlns="{MAIN_NS}"><sheetData>']
    for offset, row in enumerate(rows):
        number = first_row + offset
        cells = "".join(_cell_xml(number, col, value, shared) for col, value in enumerate(row))
        parts.append(f'<row r="{number}">{cells}</row>')
    parts.append("</sheetData></worksheet>")
    return "".join(parts)


def build_xlsx(
    sheets: Mapping[str, Rows] | None = None,
    *,
    use_shared_strings: bool = False,
    states: Mapping[str, str] | None = None,
    extra_parts: Mapping[str, bytes | str] | None = None,
    content_types_extra: str = "",
    raw_sheet_xml: Mapping[str, str] | None = None,
    compress: int = zipfile.ZIP_DEFLATED,
) -> bytes:
    if sheets is None:
        sheets = {"Sheet1": [["name", "value"], ["alpha", 1], ["beta", 2]]}
    states = states or {}
    shared: list[str] | None = [] if use_shared_strings else None
    sheet_entries = []
    rel_entries = []
    parts: dict[str, bytes | str] = {}
    for position, (name, rows) in enumerate(sheets.items(), start=1):
        state = f' state="{states[name]}"' if name in states else ""
        sheet_entries.append(
            f'<sheet name="{escape(name)}" sheetId="{position}"{state} r:id="rId{position}"/>'
        )
        rel_entries.append(
            f'<Relationship Id="rId{position}" Type="{PKG_REL}/worksheet" '
            f'Target="worksheets/sheet{position}.xml"/>'
        )
        if raw_sheet_xml and name in raw_sheet_xml:
            parts[f"xl/worksheets/sheet{position}.xml"] = raw_sheet_xml[name]
        else:
            parts[f"xl/worksheets/sheet{position}.xml"] = sheet_xml(rows, shared)
    if shared is not None:
        rel_entries.append(
            f'<Relationship Id="rIdSS" Type="{PKG_REL}/sharedStrings" Target="sharedStrings.xml"/>'
        )
        items = "".join(f"<si><t>{escape(text)}</t></si>" for text in shared)
        parts["xl/sharedStrings.xml"] = f'<sst xmlns="{MAIN_NS}">{items}</sst>'
    parts["xl/workbook.xml"] = (
        f'<workbook xmlns="{MAIN_NS}" xmlns:r="{REL_NS}"><sheets>{"".join(sheet_entries)}'
        "</sheets></workbook>"
    )
    parts["xl/_rels/workbook.xml.rels"] = (
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f"{''.join(rel_entries)}</Relationships>"
    )
    parts["[Content_Types].xml"] = (
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-'
        'officedocument.spreadsheetml.sheet.main+xml"/>'
        f"{content_types_extra}</Types>"
    )
    parts.update(extra_parts or {})
    return zip_bytes(parts, compress=compress)


def zip_bytes(parts: Mapping[str, bytes | str], *, compress: int = zipfile.ZIP_DEFLATED) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=compress) as archive:
        for name, data in parts.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def codes(result: Any) -> list[str]:
    return [warning.code for warning in result.parsed_dataset.parsing_warnings]


# ---------------------------------------------------------------------------
# Happy path and conventions shared with the CSV parser
# ---------------------------------------------------------------------------


def test_parses_basic_workbook() -> None:
    content = build_xlsx()
    result = parse_xlsx(content)

    dataset = result.parsed_dataset
    assert dataset.format is DatasetFormat.XLSX
    assert [c.original_name for c in dataset.columns] == ["name", "value"]
    assert result.rows == (("alpha", "1"), ("beta", "2"))
    assert dataset.row_count == 2
    assert dataset.sampling.scope is SamplingScope.FULL
    assert dataset.sampling.population_size == dataset.sampling.sample_size == 2
    assert [r.row_number for r in dataset.row_references] == [0, 1]
    assert [(w.name, w.index, w.is_selected) for w in dataset.worksheets] == [("Sheet1", 0, True)]
    assert dataset.worksheets[0].row_count == 2
    assert dataset.worksheets[0].column_count == 2
    assert result.selected_worksheet == "Sheet1"
    assert result.content_hash == hashlib.sha256(content).hexdigest()
    assert result.byte_size == len(content)
    assert codes(result) == []


def test_shared_strings_match_inline_strings() -> None:
    sheets: dict[str, Rows] = {"S": [["a", "b"], ["x", "y"], ["z", 3]]}
    inline = parse_xlsx(build_xlsx(sheets))
    shared = parse_xlsx(build_xlsx(sheets, use_shared_strings=True))
    assert inline.rows == shared.rows == (("x", "y"), ("z", "3"))


def test_is_deterministic() -> None:
    content = build_xlsx()
    assert parse_xlsx(content) == parse_xlsx(content)


def test_same_table_matches_csv_parser() -> None:
    table = [["id", "city", "score"], ["1", "Oslo", "2.5"], ["2", "Lund", "7"]]
    csv_text = "\n".join(",".join(row) for row in table) + "\n"
    csv_result = parse_csv(csv_text.encode())
    xlsx_result = parse_xlsx(build_xlsx({"S": [[*table[0]], [1, "Oslo", 2.5], [2, "Lund", 7]]}))
    assert xlsx_result.parsed_dataset.columns == csv_result.parsed_dataset.columns
    assert xlsx_result.rows == csv_result.rows


def test_unicode_and_leading_equals_stay_literal_text() -> None:
    result = parse_xlsx(build_xlsx({"S": [["v"], ["=1+1"], ["Åre ✓"], ["@SUM(A1)"]]}))
    assert result.rows == (("=1+1",), ("Åre ✓",), ("@SUM(A1)",))


# ---------------------------------------------------------------------------
# Worksheet selection
# ---------------------------------------------------------------------------


def test_defaults_to_first_visible_worksheet_and_lists_all() -> None:
    content = build_xlsx(
        {
            "Hidden": [["h"], ["x"]],
            "Visible": [["a", "b"], [1, 2], [3, 4]],
            "Other": [["c"], [9]],
        },
        states={"Hidden": "hidden"},
    )
    result = parse_xlsx(content)
    sheets = {w.name: w for w in result.parsed_dataset.worksheets}
    assert result.selected_worksheet == "Visible"
    assert [w.name for w in result.parsed_dataset.worksheets] == ["Hidden", "Visible", "Other"]
    assert [w.is_selected for w in result.parsed_dataset.worksheets] == [False, True, False]
    assert (sheets["Hidden"].row_count, sheets["Hidden"].column_count) == (1, 1)
    assert (sheets["Visible"].row_count, sheets["Visible"].column_count) == (2, 2)
    assert (sheets["Other"].row_count, sheets["Other"].column_count) == (1, 1)
    assert result.rows == (("1", "2"), ("3", "4"))


def test_selects_worksheet_by_name_including_hidden() -> None:
    content = build_xlsx({"A": [["a"], [1]], "B": [["b"], [2]]}, states={"B": "veryHidden"})
    result = parse_xlsx(content, worksheet="B")
    assert result.selected_worksheet == "B"
    assert result.rows == (("2",),)
    assert [c.original_name for c in result.parsed_dataset.columns] == ["b"]


def test_unknown_worksheet_is_rejected() -> None:
    with pytest.raises(XlsxParseError, match="not found"):
        parse_xlsx(build_xlsx(), worksheet="Nope")


def test_all_hidden_without_explicit_choice_is_rejected() -> None:
    content = build_xlsx({"A": [["a"], [1]]}, states={"A": "hidden"})
    with pytest.raises(XlsxParseError, match="no visible worksheet"):
        parse_xlsx(content)
    assert parse_xlsx(content, worksheet="A").rows == (("1",),)


def test_duplicate_worksheet_names_are_rejected() -> None:
    content = build_xlsx({"A": [["a"]], "a": [["a"]]})
    with pytest.raises(XlsxParseError, match="duplicate worksheet"):
        parse_xlsx(content)


def test_selected_worksheet_without_data_is_rejected() -> None:
    with pytest.raises(XlsxParseError, match="no header row"):
        parse_xlsx(build_xlsx({"Empty": [], "Full": [["a"], [1]]}))


def test_empty_unselected_worksheet_is_listed_with_zero_counts() -> None:
    result = parse_xlsx(build_xlsx({"Full": [["a"], [1]], "Empty": []}))
    empty = next(w for w in result.parsed_dataset.worksheets if w.name == "Empty")
    assert (empty.row_count, empty.column_count) == (0, 0)


def test_chart_sheet_is_ignored_with_warning() -> None:
    content = build_xlsx(
        extra_parts={
            "xl/workbook.xml": (
                f'<workbook xmlns="{MAIN_NS}" xmlns:r="{REL_NS}"><sheets>'
                '<sheet name="Sheet1" sheetId="1" r:id="rId1"/>'
                '<sheet name="Chart" sheetId="2" r:id="rId2"/></sheets></workbook>'
            ),
            "xl/_rels/workbook.xml.rels": (
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/'
                'relationships">'
                f'<Relationship Id="rId1" Type="{PKG_REL}/worksheet" '
                'Target="worksheets/sheet1.xml"/>'
                f'<Relationship Id="rId2" Type="{PKG_REL}/chartsheet" '
                'Target="chartsheets/sheet1.xml"/></Relationships>'
            ),
        }
    )
    result = parse_xlsx(content)
    assert [w.name for w in result.parsed_dataset.worksheets] == ["Sheet1"]
    assert "parsing.xlsx_non_worksheet_ignored" in codes(result)


# ---------------------------------------------------------------------------
# Stored values, formulas and literal text
# ---------------------------------------------------------------------------


def test_formula_cells_yield_cached_result_only() -> None:
    hostile = "cmd|' /C calc'!A0"
    sheet: Rows = [
        ["calc", "text", "missing"],
        [("formula", "SUM(1,2)", 3), ("formula", hostile, "cached text"), ("formula", "1+1", None)],
    ]
    result = parse_xlsx(build_xlsx({"S": sheet}))
    assert result.rows == (("3", "cached text", None),)
    assert hostile not in repr(result)
    assert "SUM" not in repr(result.rows)
    assert "parsing.xlsx_formula_without_cached_value" in codes(result)


def test_booleans_errors_numbers_and_blanks() -> None:
    sheet: Rows = [
        ["b", "e", "n", "blank", "z"],
        [True, ("error", "#DIV/0!"), 0.1, None, "end"],
        [False, ("error", "#N/A"), 1e-7, None, "end"],
    ]
    result = parse_xlsx(build_xlsx({"S": sheet}))
    assert result.rows == (
        ("TRUE", "#DIV/0!", "0.1", None, "end"),
        ("FALSE", "#N/A", "1e-07", None, "end"),
    )
    assert "parsing.xlsx_error_value" in codes(result)


def test_rich_text_runs_are_concatenated_and_phonetic_text_ignored() -> None:
    sst = (
        f'<sst xmlns="{MAIN_NS}"><si><r><t>Hel</t></r><r><t>lo</t></r>'
        "<rPh><t>PHONETIC</t></rPh></si></sst>"
    )
    sheet = (
        f'<worksheet xmlns="{MAIN_NS}"><sheetData>'
        '<row r="1"><c r="A1" t="inlineStr"><is><t>h</t></is></c></row>'
        '<row r="2"><c r="A2" t="s"><v>0</v></c></row></sheetData></worksheet>'
    )
    content = build_xlsx(
        {"S": []},
        use_shared_strings=True,
        raw_sheet_xml={"S": sheet},
        extra_parts={"xl/sharedStrings.xml": sst},
    )
    assert parse_xlsx(content).rows == (("Hello",),)


def test_invalid_shared_string_index_is_rejected() -> None:
    sheet = (
        f'<worksheet xmlns="{MAIN_NS}"><sheetData>'
        '<row r="1"><c r="A1" t="inlineStr"><is><t>h</t></is></c></row>'
        '<row r="2"><c r="A2" t="s"><v>5</v></c></row></sheetData></worksheet>'
    )
    with pytest.raises(XlsxParseError, match="shared string index"):
        parse_xlsx(build_xlsx({"S": []}, raw_sheet_xml={"S": sheet}))


# ---------------------------------------------------------------------------
# Header, sparse rows and warnings
# ---------------------------------------------------------------------------


def test_header_warnings_follow_csv_conventions() -> None:
    result = parse_xlsx(build_xlsx({"S": [["a", None, "a"], [1, 2, 3]]}))
    assert [c.internal_key for c in result.parsed_dataset.columns] == ["a", "column_1", "a_2"]
    assert "parsing.empty_column_name" in codes(result)
    assert "parsing.duplicate_column_name" in codes(result)


def test_leading_blank_rows_before_header_are_skipped() -> None:
    sheet = sheet_xml([["a"], [1]], first_row=4)
    result = parse_xlsx(build_xlsx({"S": []}, raw_sheet_xml={"S": sheet}))
    assert result.rows == (("1",),)


def test_gap_rows_become_blank_rows_and_trailing_blanks_are_trimmed() -> None:
    sheet = (
        f'<worksheet xmlns="{MAIN_NS}"><sheetData>'
        '<row r="1"><c r="A1" t="inlineStr"><is><t>h</t></is></c></row>'
        '<row r="2"><c r="A2"><v>1</v></c></row>'
        '<row r="5"><c r="A5"><v>2</v></c></row>'
        '<row r="6"/><row r="9"/></sheetData></worksheet>'
    )
    result = parse_xlsx(build_xlsx({"S": []}, raw_sheet_xml={"S": sheet}))
    assert result.rows == (("1",), (None,), (None,), ("2",))
    assert result.parsed_dataset.row_count == 4


def test_cells_beyond_header_are_dropped_with_ragged_warning() -> None:
    result = parse_xlsx(build_xlsx({"S": [["a"], [1, 2]]}))
    assert result.rows == (("1",),)
    assert "parsing.ragged_row" in codes(result)


def test_over_long_value_is_truncated_with_warning() -> None:
    limits = XlsxParseLimits(max_field_length=5)
    result = parse_xlsx(build_xlsx({"S": [["a"], ["abcdefghij"]]}), limits=limits)
    assert result.rows == (("abcde",),)
    assert "parsing.field_value_truncated" in codes(result)


def test_over_long_column_name_is_truncated_with_warning() -> None:
    limits = XlsxParseLimits(max_column_name_length=4)
    result = parse_xlsx(build_xlsx({"S": [["abcdefgh"], [1]]}), limits=limits)
    assert result.parsed_dataset.columns[0].original_name == "abcd"
    assert "parsing.column_name_truncated" in codes(result)


# ---------------------------------------------------------------------------
# Structural rejections: non-zip, encrypted, macro, traversal
# ---------------------------------------------------------------------------


def test_rejects_empty_and_non_zip_content() -> None:
    with pytest.raises(XlsxParseError, match="empty"):
        parse_xlsx(b"")
    with pytest.raises(XlsxParseError, match="not a valid zip"):
        parse_xlsx(b"name,value\n1,2\n")


def test_rejects_ole_compound_file_as_encrypted_or_legacy() -> None:
    ole = bytes.fromhex("D0CF11E0A1B11AE1") + b"\x00" * 512
    with pytest.raises(XlsxParseError, match="OLE compound"):
        parse_xlsx(ole)


def test_rejects_zip_entry_with_encryption_flag() -> None:
    data = bytearray(build_xlsx())
    position = 0
    while (position := data.find(b"PK\x03\x04", position)) != -1:
        data[position + 6] |= 0x1  # general-purpose flag: encrypted
        position += 4
    position = 0
    while (position := data.find(b"PK\x01\x02", position)) != -1:
        data[position + 8] |= 0x1
        position += 4
    with pytest.raises(XlsxParseError, match="encrypted entry"):
        parse_xlsx(bytes(data))


def test_rejects_vba_project_part() -> None:
    content = build_xlsx(extra_parts={"xl/vbaProject.bin": b"\x00\x01"})
    with pytest.raises(XlsxParseError, match="macro"):
        parse_xlsx(content)


def test_rejects_macro_sheets_part() -> None:
    content = build_xlsx(extra_parts={"xl/macrosheets/sheet1.xml": "<x/>"})
    with pytest.raises(XlsxParseError, match="macro"):
        parse_xlsx(content)


def test_rejects_macro_enabled_content_type_even_with_xlsx_style_name() -> None:
    extra = (
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.ms-excel.sheet.'
        'macroEnabled.main+xml"/>'
    )
    with pytest.raises(XlsxParseError, match="macro"):
        parse_xlsx(build_xlsx(content_types_extra=extra))


def test_rejects_macro_relationship_sheet() -> None:
    content = build_xlsx(
        extra_parts={
            "xl/_rels/workbook.xml.rels": (
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/'
                'relationships">'
                f'<Relationship Id="rId1" Type="{PKG_REL}/macrosheet" '
                'Target="worksheets/sheet1.xml"/></Relationships>'
            )
        }
    )
    with pytest.raises(XlsxParseError, match="macro sheet"):
        parse_xlsx(content)


@pytest.mark.parametrize(
    "name",
    ["../evil.xml", "xl/../../evil.xml", "/abs.xml", "xl\\sheet.xml", "C:evil.xml", "a\x00b"],
)
def test_rejects_unsafe_entry_names(name: str) -> None:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(zipfile.ZipInfo("ok.txt"), b"ok")
        info = zipfile.ZipInfo("placeholder")
        info.filename = name
        archive.writestr(info, b"x")
    with pytest.raises(XlsxParseError):
        parse_xlsx(buffer.getvalue())


def test_rejects_relationship_target_escaping_the_package() -> None:
    content = build_xlsx(
        extra_parts={
            "xl/_rels/workbook.xml.rels": (
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/'
                'relationships">'
                f'<Relationship Id="rId1" Type="{PKG_REL}/worksheet" '
                'Target="../../outside.xml"/></Relationships>'
            )
        }
    )
    with pytest.raises(XlsxParseError, match="escapes the package"):
        parse_xlsx(content)


def test_rejects_external_worksheet_relationship() -> None:
    content = build_xlsx(
        extra_parts={
            "xl/_rels/workbook.xml.rels": (
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/'
                'relationships">'
                f'<Relationship Id="rId1" Type="{PKG_REL}/worksheet" '
                'Target="http://example.invalid/s.xml" TargetMode="External"/></Relationships>'
            )
        }
    )
    with pytest.raises(XlsxParseError, match="outside the package"):
        parse_xlsx(content)


def test_rejects_missing_workbook_parts() -> None:
    parts: dict[str, bytes | str] = {"[Content_Types].xml": "<Types/>", "other.txt": b"x"}
    with pytest.raises(XlsxParseError, match="no workbook part"):
        parse_xlsx(zip_bytes(parts))
    with pytest.raises(XlsxParseError, match="Content_Types"):
        parse_xlsx(zip_bytes({"other.txt": b"x"}))


def test_rejects_worksheet_relationship_to_missing_part() -> None:
    content = build_xlsx(
        extra_parts={
            "xl/_rels/workbook.xml.rels": (
                '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/'
                'relationships">'
                f'<Relationship Id="rId1" Type="{PKG_REL}/worksheet" '
                'Target="worksheets/missing.xml"/></Relationships>'
            )
        }
    )
    with pytest.raises(XlsxParseError, match="missing part"):
        parse_xlsx(content)


def test_external_links_are_ignored_with_warning() -> None:
    content = build_xlsx(extra_parts={"xl/externalLinks/externalLink1.xml": "<x/>"})
    result = parse_xlsx(content)
    assert "parsing.xlsx_external_links_ignored" in codes(result)


# ---------------------------------------------------------------------------
# Limits and expansion
# ---------------------------------------------------------------------------


def test_rejects_content_over_byte_limit() -> None:
    content = build_xlsx()
    with pytest.raises(XlsxParseError, match="byte limit"):
        parse_xlsx(content, limits=XlsxParseLimits(max_bytes=len(content) - 1))


def test_rejects_too_many_entries() -> None:
    content = build_xlsx(extra_parts={f"docProps/f{i}.txt": b"x" for i in range(5)})
    with pytest.raises(XlsxParseError, match="entry limit"):
        parse_xlsx(content, limits=XlsxParseLimits(max_entries=4))


def test_rejects_too_many_worksheets() -> None:
    content = build_xlsx({f"S{i}": [["a"], [1]] for i in range(3)})
    with pytest.raises(XlsxParseError, match="more than 2 worksheets"):
        parse_xlsx(content, limits=XlsxParseLimits(max_worksheets=2))


def test_rejects_too_many_rows() -> None:
    content = build_xlsx({"S": [["a"], [1], [2], [3]]})
    with pytest.raises(XlsxParseError, match="more than 2 data rows"):
        parse_xlsx(content, limits=XlsxParseLimits(max_rows=2))
    assert len(parse_xlsx(content, limits=XlsxParseLimits(max_rows=3)).rows) == 3


def test_rejects_too_many_columns_in_header_and_in_data_cells() -> None:
    wide = build_xlsx({"S": [["a", "b", "c"], [1, 2, 3]]})
    with pytest.raises(XlsxParseError, match="more than 2 columns"):
        parse_xlsx(wide, limits=XlsxParseLimits(max_columns=2))
    late = build_xlsx({"S": [["a"], [1, 2, 3]]})
    with pytest.raises(XlsxParseError, match="more than 2 columns"):
        parse_xlsx(late, limits=XlsxParseLimits(max_columns=2))


def test_rejects_too_many_cells() -> None:
    content = build_xlsx({"S": [["a", "b"], [1, 2], [3, 4]]})
    with pytest.raises(XlsxParseError, match="more than 5 cells"):
        parse_xlsx(content, limits=XlsxParseLimits(max_cells=5))


def test_rejects_huge_row_gap_before_materializing_it() -> None:
    sheet = (
        f'<worksheet xmlns="{MAIN_NS}"><sheetData>'
        '<row r="1"><c r="A1" t="inlineStr"><is><t>h</t></is></c></row>'
        '<row r="900000"><c r="A900000"><v>1</v></c></row></sheetData></worksheet>'
    )
    content = build_xlsx({"S": []}, raw_sheet_xml={"S": sheet})
    with pytest.raises(XlsxParseError, match="more than 1000 data rows"):
        parse_xlsx(content, limits=XlsxParseLimits(max_rows=1000))
    with pytest.raises(XlsxParseError, match="cell limit"):
        parse_xlsx(content, limits=XlsxParseLimits(max_cells=1000))


def test_limits_apply_to_unselected_worksheets_too() -> None:
    content = build_xlsx({"Small": [["a"], [1]], "Big": [["a"], [1], [2], [3]]})
    with pytest.raises(XlsxParseError, match="more than 2 data rows"):
        parse_xlsx(content, limits=XlsxParseLimits(max_rows=2))


def test_rejects_out_of_order_rows_and_bad_references() -> None:
    out_of_order = (
        f'<worksheet xmlns="{MAIN_NS}"><sheetData>'
        '<row r="2"><c r="A2"><v>1</v></c></row><row r="1"><c r="A1"><v>1</v></c></row>'
        "</sheetData></worksheet>"
    )
    with pytest.raises(XlsxParseError, match="out of order"):
        parse_xlsx(build_xlsx({"S": []}, raw_sheet_xml={"S": out_of_order}))
    bad_ref = (
        f'<worksheet xmlns="{MAIN_NS}"><sheetData>'
        '<row r="1"><c r="12"><v>1</v></c></row></sheetData></worksheet>'
    )
    with pytest.raises(XlsxParseError, match="invalid cell reference"):
        parse_xlsx(build_xlsx({"S": []}, raw_sheet_xml={"S": bad_ref}))


def test_rejects_zip_bomb_by_declared_uncompressed_size() -> None:
    bomb = zip_bytes({"xl/media/bomb.bin": b"\x00" * 2_000_000})
    assert len(bomb) < 10_000  # highly compressible: tiny upload, huge expansion
    content = build_xlsx(extra_parts={"xl/media/bomb.bin": b"\x00" * 2_000_000})
    with pytest.raises(XlsxParseError, match="uncompressed bytes"):
        parse_xlsx(content, limits=XlsxParseLimits(max_uncompressed_bytes=100_000))


def test_rejects_sheet_that_decompresses_beyond_budget() -> None:
    padding = " " * 300_000
    sheet = (
        f'<worksheet xmlns="{MAIN_NS}"><sheetData>{padding}'
        '<row r="1"><c r="A1"><v>1</v></c></row></sheetData></worksheet>'
    )
    content = build_xlsx({"S": []}, raw_sheet_xml={"S": sheet})
    with pytest.raises(XlsxParseError, match="uncompressed|decompressed"):
        parse_xlsx(content, limits=XlsxParseLimits(max_uncompressed_bytes=100_000))


def _patch_sizes(content: bytes, new_size: int) -> bytes:
    """Falsify the uncompressed size in every local and central zip header."""
    data = bytearray(content)
    position = 0
    while (position := data.find(b"PK\x03\x04", position)) != -1:
        struct.pack_into("<I", data, position + 22, new_size)
        position += 4
    position = 0
    while (position := data.find(b"PK\x01\x02", position)) != -1:
        struct.pack_into("<I", data, position + 24, new_size)
        position += 4
    return bytes(data)


def test_falsified_zip_header_sizes_do_not_bypass_limits() -> None:
    padding = " " * 400_000
    sheet = (
        f'<worksheet xmlns="{MAIN_NS}"><sheetData>{padding}'
        '<row r="1"><c r="A1"><v>1</v></c></row></sheetData></worksheet>'
    )
    honest = build_xlsx({"S": []}, raw_sheet_xml={"S": sheet})
    forged = _patch_sizes(honest, 10)
    # Headers now claim a tiny size, so the early declared-size check passes;
    # the workbook must still be rejected rather than expanded or misread.
    with pytest.raises(XlsxParseError):
        parse_xlsx(forged, limits=XlsxParseLimits(max_uncompressed_bytes=100_000))


def test_decompression_is_counted_while_reading() -> None:
    class _Stream(io.BytesIO):
        def __enter__(self) -> _Stream:
            return self

    fed = 0

    class _Archive:
        def open(self, name: str) -> _Stream:
            return _Stream(b" " * 10_000_000)

    class _CountingParser:
        def Parse(self, chunk: bytes, final: bool) -> None:  # noqa: N802
            nonlocal fed
            fed += len(chunk)

    archive: Any = _Archive()
    with pytest.raises(XlsxParseError, match="decompressed content exceeds"):
        _feed_part(archive, "any.xml", _CountingParser(), _Budget(200_000))
    assert fed <= 200_000


# ---------------------------------------------------------------------------
# XML safety
# ---------------------------------------------------------------------------

_BILLION_LAUGHS = (
    '<?xml version="1.0"?><!DOCTYPE lolz ['
    '<!ENTITY lol "lol">'
    '<!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">'
    '<!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;">'
    '<!ENTITY lol4 "&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;">'
    "]>"
    f'<sst xmlns="{MAIN_NS}"><si><t>&lol4;</t></si></sst>'
)


def test_rejects_entity_expansion_payload_in_shared_strings() -> None:
    sheet = (
        f'<worksheet xmlns="{MAIN_NS}"><sheetData>'
        '<row r="1"><c r="A1" t="s"><v>0</v></c></row></sheetData></worksheet>'
    )
    content = build_xlsx(
        {"S": []},
        use_shared_strings=True,
        raw_sheet_xml={"S": sheet},
        extra_parts={"xl/sharedStrings.xml": _BILLION_LAUGHS},
    )
    with pytest.raises(XlsxParseError, match="DOCTYPE"):
        parse_xlsx(content)


def test_rejects_external_entity_in_worksheet() -> None:
    sheet = (
        '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>'
        f'<worksheet xmlns="{MAIN_NS}"><sheetData><row r="1">'
        '<c r="A1" t="inlineStr"><is><t>&xxe;</t></is></c></row></sheetData></worksheet>'
    )
    with pytest.raises(XlsxParseError, match="DOCTYPE"):
        parse_xlsx(build_xlsx({"S": []}, raw_sheet_xml={"S": sheet}))


@pytest.mark.parametrize(
    "part",
    ["[Content_Types].xml", "xl/workbook.xml", "xl/_rels/workbook.xml.rels"],
)
def test_rejects_doctype_in_any_package_part(part: str) -> None:
    base = build_xlsx()
    with zipfile.ZipFile(io.BytesIO(base)) as source:
        original = source.read(part).decode()
    hostile = '<!DOCTYPE x [<!ENTITY a "b">]>' + original
    with pytest.raises(XlsxParseError, match="DOCTYPE"):
        parse_xlsx(build_xlsx(extra_parts={part: hostile}))


def test_rejects_malformed_xml() -> None:
    with pytest.raises(XlsxParseError, match="not well-formed"):
        parse_xlsx(build_xlsx({"S": []}, raw_sheet_xml={"S": "<worksheet><sheetData>"}))


def test_rejects_excessive_xml_nesting() -> None:
    nested = "<a>" * 200 + "</a>" * 200
    sheet = f'<worksheet xmlns="{MAIN_NS}">{nested}</worksheet>'
    with pytest.raises(XlsxParseError, match="nested deeper"):
        parse_xlsx(build_xlsx({"S": []}, raw_sheet_xml={"S": sheet}))


def test_parser_factory_rejects_entities_directly() -> None:
    parser = _new_parser()
    with pytest.raises(XlsxParseError):
        parser.Parse(b'<!DOCTYPE x [<!ENTITY a "b">]><x>&a;</x>', True)


def test_namespace_prefixes_and_stored_compression_are_accepted() -> None:
    sheet = (
        '<x:worksheet xmlns:x="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<x:sheetData><x:row r="1"><x:c r="A1" t="inlineStr"><x:is><x:t>h</x:t></x:is></x:c>'
        '</x:row><x:row r="2"><x:c r="A2"><x:v>7</x:v></x:c></x:row></x:sheetData></x:worksheet>'
    )
    content = build_xlsx({"S": []}, raw_sheet_xml={"S": sheet}, compress=zipfile.ZIP_STORED)
    assert parse_xlsx(content).rows == (("7",),)
