"""HTTP end-to-end proof that an XLSX upload is analyzed from the one
worksheet the caller chose (`ING-03`, slice 2), and that unsafe or ambiguous
workbooks are refused before any analysis exists.

Workbooks are built in memory with `zipfile`; no fixture files and no
spreadsheet library are used.
"""

from __future__ import annotations

import ast
import io
import json
import struct
import time
import zipfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

import trusttable_backend.analysis.service as service_module
from trusttable_backend.persistence.models import AnalysisRecord

_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

Cell = str | int | float | None
Rows = Sequence[Sequence[Cell]]

_TERMINAL = {"completed", "failed", "cancelled"}


def _letters(index: int) -> str:
    out = ""
    index += 1
    while index:
        index, rem = divmod(index - 1, 26)
        out = chr(ord("A") + rem) + out
    return out


def _sheet_xml(rows: Rows) -> str:
    parts = [f'<worksheet xmlns="{_MAIN}"><sheetData>']
    for r, row in enumerate(rows, start=1):
        cells = []
        for c, value in enumerate(row):
            ref = f"{_letters(c)}{r}"
            if value is None:
                continue
            if isinstance(value, str):
                cells.append(f'<c r="{ref}" t="inlineStr"><is><t>{escape(value)}</t></is></c>')
            else:
                cells.append(f'<c r="{ref}"><v>{value}</v></c>')
        parts.append(f'<row r="{r}">{"".join(cells)}</row>')
    parts.append("</sheetData></worksheet>")
    return "".join(parts)


def workbook(
    sheets: Mapping[str, Rows],
    *,
    hidden: Sequence[str] = (),
    extra_parts: Mapping[str, bytes] | None = None,
) -> bytes:
    sheet_tags = []
    rel_tags = []
    parts: dict[str, bytes | str] = {}
    for position, (name, rows) in enumerate(sheets.items(), start=1):
        state = ' state="hidden"' if name in hidden else ""
        sheet_tags.append(
            f'<sheet name="{escape(name)}" sheetId="{position}"{state} r:id="rId{position}"/>'
        )
        rel_tags.append(
            f'<Relationship Id="rId{position}" Type="{_REL}/worksheet" '
            f'Target="worksheets/sheet{position}.xml"/>'
        )
        parts[f"xl/worksheets/sheet{position}.xml"] = _sheet_xml(rows)
    parts["xl/workbook.xml"] = (
        f'<workbook xmlns="{_MAIN}" xmlns:r="{_REL}"><sheets>{"".join(sheet_tags)}</sheets>'
        "</workbook>"
    )
    parts["xl/_rels/workbook.xml.rels"] = (
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f"{''.join(rel_tags)}</Relationships>"
    )
    parts["[Content_Types].xml"] = (
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="xml" ContentType="application/xml"/></Types>'
    )
    parts.update(extra_parts or {})
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in parts.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def _upload(
    client: TestClient,
    content: bytes,
    *,
    filename: str = "book.xlsx",
    worksheet: str | None = None,
) -> Any:
    data = {"worksheet": worksheet} if worksheet is not None else None
    return client.post(
        "/api/v1/analyses",
        files={"file": (filename, content, _XLSX_TYPE)},
        data=data,
    )


def _wait_for_terminal(client: TestClient, analysis_id: str) -> dict[str, Any]:
    deadline = time.monotonic() + 20.0
    while time.monotonic() < deadline:
        status = client.get(f"/api/v1/analyses/{analysis_id}/status")
        assert status.status_code == 200
        if status.json()["state"] in _TERMINAL:
            final = client.get(f"/api/v1/analyses/{analysis_id}")
            assert final.status_code == 200
            return final.json()  # type: ignore[no-any-return]
        time.sleep(0.01)
    pytest.fail("analysis did not reach a terminal state")


def _analysis_count(client: TestClient) -> int:
    store = client.app.state.analysis_store  # type: ignore[attr-defined]
    with store._session_factory() as session:  # noqa: SLF001 - white-box, test-only
        return session.scalar(select(func.count()).select_from(AnalysisRecord)) or 0


_FLAWED_ROWS: Rows = [["name", "amount"], ["Alice", 10], ["Bob", 20], ["Alice", 10]]
_FLAWED_CSV = b"name,amount\nAlice,10\nBob,20\nAlice,10\n"


# ---------------------------------------------------------------------------
# Accepting a workbook
# ---------------------------------------------------------------------------


def test_single_sheet_workbook_completes_with_findings(client: TestClient) -> None:
    response = _upload(client, workbook({"Data": _FLAWED_ROWS}))

    assert response.status_code == 202
    final = _wait_for_terminal(client, response.json()["analysis"]["analysis_id"])
    assert final["state"] == "completed"
    assert final["dataset"]["format"] == "xlsx"
    assert final["dataset"]["selected_worksheet"] == "Data"
    assert final["finding_count"] > 0


def test_csv_upload_reports_no_selected_worksheet(client: TestClient) -> None:
    response = client.post("/api/v1/analyses", files={"file": ("a.csv", _FLAWED_CSV, "text/csv")})
    assert response.status_code == 202
    final = _wait_for_terminal(client, response.json()["analysis"]["analysis_id"])
    assert final["dataset"]["format"] == "csv"
    assert final["dataset"]["selected_worksheet"] is None


def test_same_table_as_csv_and_xlsx_gives_equivalent_findings(client: TestClient) -> None:
    csv_response = client.post(
        "/api/v1/analyses", files={"file": ("a.csv", _FLAWED_CSV, "text/csv")}
    )
    xlsx_response = _upload(client, workbook({"Data": _FLAWED_ROWS}))
    csv_id = csv_response.json()["analysis"]["analysis_id"]
    xlsx_id = xlsx_response.json()["analysis"]["analysis_id"]
    assert _wait_for_terminal(client, csv_id)["state"] == "completed"
    assert _wait_for_terminal(client, xlsx_id)["state"] == "completed"

    def shape(analysis_id: str) -> list[tuple[str, int]]:
        items = client.get(f"/api/v1/analyses/{analysis_id}/findings").json()["items"]
        return sorted((item["detector_id"], item["affected_row_count"]) for item in items)

    assert shape(xlsx_id) == shape(csv_id)
    assert shape(csv_id)  # the table really does produce findings


def test_hidden_helper_sheet_does_not_force_a_choice(client: TestClient) -> None:
    content = workbook({"Helper": [["x"], [1]], "Data": _FLAWED_ROWS}, hidden=["Helper"])
    response = _upload(client, content)

    assert response.status_code == 202
    final = _wait_for_terminal(client, response.json()["analysis"]["analysis_id"])
    assert final["dataset"]["selected_worksheet"] == "Data"


# ---------------------------------------------------------------------------
# Worksheet selection
# ---------------------------------------------------------------------------

_TWO_SHEETS: dict[str, Rows] = {
    "First": [["first_col", "n"], ["a", 1], ["b", 2]],
    "Second": [["second_col", "n"], ["x", 7], ["y", 8], ["x", 7]],
}


def test_several_worksheets_without_a_choice_is_refused(client: TestClient) -> None:
    before = _analysis_count(client)

    response = _upload(client, workbook(_TWO_SHEETS))

    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "WORKSHEET_REQUIRED"
    assert error["details"]["worksheets"] == ["First", "Second"]
    assert _analysis_count(client) == before


def test_chosen_worksheet_is_the_one_analyzed(client: TestClient) -> None:
    response = _upload(client, workbook(_TWO_SHEETS), worksheet="Second")

    assert response.status_code == 202
    analysis_id = response.json()["analysis"]["analysis_id"]
    final = _wait_for_terminal(client, analysis_id)
    assert final["state"] == "completed"
    assert final["dataset"]["selected_worksheet"] == "Second"
    profile = json.dumps(client.get(f"/api/v1/analyses/{analysis_id}/profile").json())
    assert "second_col" in profile
    assert "first_col" not in profile


def test_choosing_the_first_worksheet_explicitly_analyzes_it(client: TestClient) -> None:
    response = _upload(client, workbook(_TWO_SHEETS), worksheet="First")
    analysis_id = response.json()["analysis"]["analysis_id"]
    assert _wait_for_terminal(client, analysis_id)["state"] == "completed"
    profile = json.dumps(client.get(f"/api/v1/analyses/{analysis_id}/profile").json())
    assert "first_col" in profile
    assert "second_col" not in profile


def test_unknown_worksheet_is_refused(client: TestClient) -> None:
    before = _analysis_count(client)

    response = _upload(client, workbook(_TWO_SHEETS), worksheet="Third")

    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "INVALID_REQUEST"
    assert error["details"]["worksheets"] == ["First", "Second"]
    assert _analysis_count(client) == before


def test_worksheet_field_is_refused_for_csv(client: TestClient) -> None:
    response = client.post(
        "/api/v1/analyses",
        files={"file": ("a.csv", _FLAWED_CSV, "text/csv")},
        data={"worksheet": "Sheet1"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


# ---------------------------------------------------------------------------
# Refusing unsafe workbooks before an analysis exists
# ---------------------------------------------------------------------------


def test_macro_workbook_is_refused_and_creates_nothing(client: TestClient) -> None:
    before = _analysis_count(client)
    content = workbook({"Data": _FLAWED_ROWS}, extra_parts={"xl/vbaProject.bin": b"\x00"})

    response = _upload(client, content)

    assert response.status_code == 415
    assert response.json()["error"]["code"] == "MACRO_ENABLED_FILE"
    assert _analysis_count(client) == before


def test_xlsm_extension_is_unsupported(client: TestClient) -> None:
    response = _upload(client, workbook({"Data": _FLAWED_ROWS}), filename="book.xlsm")

    assert response.status_code == 415
    error = response.json()["error"]
    assert error["code"] == "UNSUPPORTED_FILE_TYPE"
    assert error["details"]["supported_extensions"] == [".csv", ".xlsx"]


def test_non_workbook_with_xlsx_name_is_malformed(client: TestClient) -> None:
    before = _analysis_count(client)

    response = _upload(client, _FLAWED_CSV)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "MALFORMED_FILE"
    assert _analysis_count(client) == before


def test_encrypted_style_ole_file_is_malformed(client: TestClient) -> None:
    ole = bytes.fromhex("D0CF11E0A1B11AE1") + b"\x00" * 512

    response = _upload(client, ole)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "MALFORMED_FILE"


def test_declared_expansion_bomb_is_refused_without_unpacking(client: TestClient) -> None:
    data = bytearray(workbook({"Data": _FLAWED_ROWS}))
    position = 0
    while (position := data.find(b"PK\x01\x02", position)) != -1:
        struct.pack_into("<I", data, position + 24, 2_000_000_000)  # claimed size
        position += 4
    before = _analysis_count(client)

    response = _upload(client, bytes(data))

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "WORKBOOK_EXPANSION_LIMIT"
    assert _analysis_count(client) == before


def test_doctype_in_workbook_is_refused(client: TestClient) -> None:
    hostile = (
        '<!DOCTYPE x [<!ENTITY a "b">]>'
        f'<workbook xmlns="{_MAIN}" xmlns:r="{_REL}"><sheets/></workbook>'
    )
    content = workbook({"Data": _FLAWED_ROWS}, extra_parts={"xl/workbook.xml": hostile.encode()})

    response = _upload(client, content)

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "MALFORMED_FILE"


def test_error_responses_do_not_echo_workbook_text(client: TestClient) -> None:
    content = workbook({"Data": _FLAWED_ROWS}, extra_parts={"xl/vbaProject.bin": b"SECRET-MARKER"})
    response = _upload(client, content)
    assert "SECRET-MARKER" not in response.text
    assert "vbaProject" not in response.text


# ---------------------------------------------------------------------------
# Every pipeline stage reads the same worksheet
# ---------------------------------------------------------------------------


def _completed_second_sheet(client: TestClient) -> str:
    response = _upload(client, workbook(_TWO_SHEETS), worksheet="Second")
    analysis_id: str = response.json()["analysis"]["analysis_id"]
    assert _wait_for_terminal(client, analysis_id)["state"] == "completed"
    return analysis_id


def test_row_context_reads_the_selected_worksheet(client: TestClient) -> None:
    analysis_id = _completed_second_sheet(client)
    items = client.get(f"/api/v1/analyses/{analysis_id}/findings").json()["items"]
    finding = next(item for item in items if item["affected_row_count"] > 0)
    detail = client.get(f"/api/v1/analyses/{analysis_id}/findings/{finding['finding_id']}").json()

    response = client.get(
        f"/api/v1/analyses/{analysis_id}/findings/{finding['finding_id']}/row-context",
        params={"anchor_row": detail["affected_row_numbers"][0]},
    )

    assert response.status_code == 200
    body = response.json()
    names = [column["original_name"] for column in body["columns"]]
    assert names == ["second_col", "n"]
    assert all(row["values"][0] in {"x", "y"} for row in body["rows"])


def test_rule_creation_executes_over_the_selected_worksheet(client: TestClient) -> None:
    analysis_id = _completed_second_sheet(client)

    response = client.post(
        f"/api/v1/analyses/{analysis_id}/rules",
        json={
            "name": "n must be positive",
            "description": "n should be positive",
            "severity": "medium",
            "rule_type": "numeric_range",
            "column_names": ["n"],
            "minimum": 8.0,
        },
    )

    assert response.status_code == 201
    result = response.json()["last_result"]
    assert result["error"] is None
    # Second sheet holds n = 7, 8, 7: two rows fall below 8. The first
    # sheet's n = 1, 2 would fail differently, so this proves the sheet.
    assert result["pass_count"] == 1
    assert result["fail_count"] == 2


def test_no_service_stage_parses_file_bytes_outside_the_format_dispatcher() -> None:
    """Every file-reading stage must go through `_parse_analysis_content`,
    the one place that dispatches on dataset format and selected worksheet.
    A stage calling `parse_csv` directly would parse a workbook as CSV.
    """
    package_dir = Path(service_module.__file__).parent
    offenders: list[str] = []
    dispatcher_calls = 0
    for path in sorted(package_dir.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for function in ast.walk(tree):
            if not isinstance(function, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            for node in ast.walk(function):
                if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                    continue
                if node.func.id in {"parse_csv", "parse_xlsx"}:
                    if function.name != "_parse_analysis_content":
                        offenders.append(f"{path.name}:{function.name}")
                elif node.func.id == "_parse_analysis_content":
                    dispatcher_calls += 1
    assert offenders == []
    assert dispatcher_calls >= 5  # run, row context, and the rule stages


# ---------------------------------------------------------------------------
# Retry keeps the format
# ---------------------------------------------------------------------------


def test_retry_of_a_failed_workbook_keeps_format_worksheet_and_extension(
    client: TestClient,
) -> None:
    # The only worksheet holds no data, so upload inspection passes but the
    # pipeline cannot find a header: a genuinely failed xlsx analysis.
    response = _upload(client, workbook({"Empty": []}))
    assert response.status_code == 202
    failed_id = response.json()["analysis"]["analysis_id"]
    assert _wait_for_terminal(client, failed_id)["state"] == "failed"

    retry = client.post(f"/api/v1/analyses/{failed_id}/retry")

    assert retry.status_code == 202
    retry_resource = retry.json()["analysis"]
    assert retry_resource["dataset"]["format"] == "xlsx"
    assert retry_resource["dataset"]["selected_worksheet"] == "Empty"
    stored = client.app.state.analysis_store.get(  # type: ignore[attr-defined]
        retry_resource["analysis_id"]
    )
    assert stored.dataset.stored_filename.endswith(".xlsx")
    assert stored.dataset.selected_worksheet == "Empty"
