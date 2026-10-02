"""Operator-configured upload and workbook limits are enforced (`ING-03`).

Each documented limit variable is lowered below an otherwise valid file and
the API must react as `docs/api-specification.md` §6 and §14 document:
size and workbook-structure limits refuse the upload; row, column and cell
limits end the analysis as `failed`. Each test also proves the file is
accepted at the limit, so a refusal is the setting at work and not a
property of the fixture. Later pipeline stages re-parse the stored file, so
they must read the same configured limits.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient

import trusttable_backend.analysis.service as service_module
from tests.api.test_xlsx_upload import (
    _FLAWED_CSV,
    _FLAWED_ROWS,
    Cell,
    Rows,
    _upload,
    _wait_for_terminal,
    workbook,
)
from trusttable_backend.config import get_settings
from trusttable_backend.parsers import parse_csv, parse_xlsx

_MIB = 1024 * 1024
_CSV_TYPE = "text/csv"


def _configure(monkeypatch: pytest.MonkeyPatch, **variables: int) -> None:
    for name, value in variables.items():
        monkeypatch.setenv(name.upper(), str(value))
    get_settings.cache_clear()


def _upload_csv(client: TestClient, content: bytes) -> Any:
    return client.post("/api/v1/analyses", files={"file": ("data.csv", content, _CSV_TYPE)})


def _terminal_state(client: TestClient, response: Any) -> str:
    assert response.status_code == 202
    final = _wait_for_terminal(client, response.json()["analysis"]["analysis_id"])
    return str(final["state"])


# ---------------------------------------------------------------------------
# MAX_FILE_SIZE_MB
# ---------------------------------------------------------------------------


def test_max_file_size_refuses_an_oversized_csv(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    content = b"name,amount\n" + b"Alice,10\n" * 200_000  # about 1.7 MiB
    _configure(monkeypatch, max_file_size_mb=1)

    response = _upload_csv(client, content)

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "FILE_TOO_LARGE"


def test_max_file_size_refuses_an_oversized_workbook(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    content = workbook({"Data": _FLAWED_ROWS}, extra_parts={"docProps/blob.bin": os.urandom(_MIB)})
    assert len(content) > _MIB
    _configure(monkeypatch, max_file_size_mb=1)

    response = _upload(client, content)

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "FILE_TOO_LARGE"


def test_file_at_the_size_limit_is_accepted(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    _configure(monkeypatch, max_file_size_mb=1)

    assert _terminal_state(client, _upload_csv(client, _FLAWED_CSV)) == "completed"
    assert _terminal_state(client, _upload(client, workbook({"Data": _FLAWED_ROWS}))) == "completed"


# ---------------------------------------------------------------------------
# MAX_WORKSHEETS and MAX_UNCOMPRESSED_WORKBOOK_MB (refused at upload)
# ---------------------------------------------------------------------------


def test_max_worksheets_refuses_a_workbook_with_more_worksheets(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    two_sheets = workbook({"First": _FLAWED_ROWS, "Second": _FLAWED_ROWS})
    _configure(monkeypatch, max_worksheets=1)

    refused = _upload(client, two_sheets, worksheet="First")

    assert refused.status_code == 413
    assert refused.json()["error"]["code"] == "WORKBOOK_EXPANSION_LIMIT"

    _configure(monkeypatch, max_worksheets=2)

    accepted = _upload(client, two_sheets, worksheet="First")

    assert _terminal_state(client, accepted) == "completed"


def test_max_uncompressed_workbook_size_refuses_an_expanding_workbook(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Highly repetitive rows: tiny when compressed, several MiB unpacked.
    body: list[list[Cell]] = [["Alice", 10]] * 60_000
    rows: Rows = [["name", "amount"], *body]
    content = workbook({"Data": rows})
    assert len(content) < _MIB
    _configure(monkeypatch, max_uncompressed_workbook_mb=1)

    refused = _upload(client, content)

    assert refused.status_code == 413
    assert refused.json()["error"]["code"] == "WORKBOOK_EXPANSION_LIMIT"

    _configure(monkeypatch, max_uncompressed_workbook_mb=500)

    assert _terminal_state(client, _upload(client, content)) == "completed"


# ---------------------------------------------------------------------------
# MAX_ROWS, MAX_COLUMNS, MAX_CELL_COUNT (enforced as the pipeline reads the file)
# ---------------------------------------------------------------------------

_THREE_DATA_ROWS = _FLAWED_ROWS  # header plus three data rows, two columns


@pytest.mark.parametrize(
    ("variable", "limit_that_fits", "limit_that_refuses", "csv", "rows"),
    [
        ("max_rows", 3, 2, _FLAWED_CSV, _THREE_DATA_ROWS),
        ("max_columns", 2, 1, _FLAWED_CSV, _THREE_DATA_ROWS),
    ],
)
def test_row_and_column_limits_fail_an_over_limit_file_for_csv_and_xlsx(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    variable: str,
    limit_that_fits: int,
    limit_that_refuses: int,
    csv: bytes,
    rows: Any,
) -> None:
    content = workbook({"Data": rows})

    _configure(monkeypatch, **{variable: limit_that_fits})
    assert _terminal_state(client, _upload_csv(client, csv)) == "completed"
    assert _terminal_state(client, _upload(client, content)) == "completed"

    _configure(monkeypatch, **{variable: limit_that_refuses})
    assert _terminal_state(client, _upload_csv(client, csv)) == "failed"
    assert _terminal_state(client, _upload(client, content)) == "failed"


def test_max_cell_count_fails_an_over_limit_workbook(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    content = workbook({"Data": _FLAWED_ROWS})  # four rows by two columns = eight cells

    _configure(monkeypatch, max_cell_count=8)
    assert _terminal_state(client, _upload(client, content)) == "completed"

    _configure(monkeypatch, max_cell_count=7)
    assert _terminal_state(client, _upload(client, content)) == "failed"


# ---------------------------------------------------------------------------
# Later stages re-parse the stored file with the same configured limits
# ---------------------------------------------------------------------------


def _record_parser_limits(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, Any]]:
    calls: list[tuple[str, Any]] = []

    def spy(name: str, real: Callable[..., Any]) -> Callable[..., Any]:
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            calls.append((name, kwargs.get("limits")))
            return real(*args, **kwargs)

        return wrapper

    monkeypatch.setattr(service_module, "parse_csv", spy("csv", parse_csv))
    monkeypatch.setattr(service_module, "parse_xlsx", spy("xlsx", parse_xlsx))
    return calls


@pytest.mark.parametrize("file_format", ["csv", "xlsx"])
def test_every_stage_parses_with_the_configured_limits(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, file_format: str
) -> None:
    _configure(
        monkeypatch,
        max_rows=777,
        max_columns=44,
        max_file_size_mb=7,
        max_worksheets=9,
        max_uncompressed_workbook_mb=88,
        max_cell_count=999_999,
    )
    calls = _record_parser_limits(monkeypatch)
    if file_format == "csv":
        response = _upload_csv(client, _FLAWED_CSV)
    else:
        response = _upload(client, workbook({"Data": _FLAWED_ROWS}))
    assert _terminal_state(client, response) == "completed"
    analysis_id = response.json()["analysis"]["analysis_id"]
    findings = client.get(f"/api/v1/analyses/{analysis_id}/findings").json()["items"]
    finding = next(item for item in findings if item["affected_row_count"] > 0)
    detail = client.get(f"/api/v1/analyses/{analysis_id}/findings/{finding['finding_id']}").json()

    row_context = client.get(
        f"/api/v1/analyses/{analysis_id}/findings/{finding['finding_id']}/row-context",
        params={"anchor_row": detail["affected_row_numbers"][0]},
    )
    rule = client.post(
        f"/api/v1/analyses/{analysis_id}/rules",
        json={
            "name": "amount at least 15",
            "description": "amount should be at least 15",
            "severity": "medium",
            "rule_type": "numeric_range",
            "column_names": ["amount"],
            "minimum": 15.0,
        },
    )

    assert row_context.status_code == 200
    assert rule.status_code == 201
    assert len(calls) >= 3  # the run, the row context and the rule execution
    for name, limits in calls:
        assert name == file_format
        assert limits is not None
        assert (limits.max_rows, limits.max_columns, limits.max_bytes) == (777, 44, 7 * _MIB)
        if file_format == "xlsx":
            assert (limits.max_worksheets, limits.max_uncompressed_bytes, limits.max_cells) == (
                9,
                88 * _MIB,
                999_999,
            )
