"""HTTP tests for staged uploads (`UX-02`, D-068, `docs/api-specification.md` §7).

The properties under test: choosing a file creates no analysis; the reference
is unguessable, single-use, bounded and absent from logs and errors; Run
analyses exactly the staged bytes; unreadable files are reported in fixed text
and not stored; direct upload is untouched.
"""

from __future__ import annotations

import hashlib
import logging
import sqlite3
from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text

from tests.api.test_xlsx_upload import workbook
from trusttable_backend.main import create_app
from trusttable_backend.persistence import build_session_factory
from trusttable_backend.persistence.models import AnalysisRecord, StagedUploadRecord

_CSV = b"id,name,amount\n1,Ada,10\n2,Grace,20\n3,Linus,30\n"
_XLSX_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_SENTINEL = "SENTINEL_q8Zr_do_not_echo"


@pytest.fixture
def make_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[Callable[..., TestClient]]:
    """Build an app with the given environment overrides; closes them all."""
    from trusttable_backend.config import get_settings

    opened: list[TestClient] = []

    def build(**env: str) -> TestClient:
        for name, value in env.items():
            monkeypatch.setenv(name, value)
        get_settings.cache_clear()
        test_client = TestClient(create_app())
        test_client.__enter__()
        opened.append(test_client)
        return test_client

    yield build
    for test_client in opened:
        test_client.__exit__(None, None, None)


def _stage(
    client: TestClient,
    content: bytes = _CSV,
    *,
    filename: str = "data.csv",
    content_type: str = "text/csv",
) -> Any:
    return client.post("/api/v1/staged-uploads", files={"file": (filename, content, content_type)})


def _inspect(client: TestClient, ref: str, worksheet: str | None = None) -> Any:
    return client.post(
        "/api/v1/staged-uploads/inspect", json={"staging_ref": ref, "worksheet": worksheet}
    )


def _run(client: TestClient, ref: str, worksheet: str | None = None) -> Any:
    return client.post(
        "/api/v1/staged-uploads/run", json={"staging_ref": ref, "worksheet": worksheet}
    )


def _discard(client: TestClient, ref: str) -> Any:
    return client.post("/api/v1/staged-uploads/discard", json={"staging_ref": ref})


def _analysis_count(client: TestClient) -> int:
    with build_session_factory(client.app.state.analysis_engine)() as session:  # type: ignore[attr-defined]
        return int(session.scalar(select(func.count()).select_from(AnalysisRecord)) or 0)


def _staged_count(client: TestClient) -> int:
    with build_session_factory(client.app.state.analysis_engine)() as session:  # type: ignore[attr-defined]
        return int(session.scalar(select(func.count()).select_from(StagedUploadRecord)) or 0)


# --- choosing a file starts nothing ------------------------------------------


def test_staging_a_csv_stores_it_and_creates_no_analysis(client: TestClient) -> None:
    response = _stage(client)

    assert response.status_code == 201
    body = response.json()
    assert response.headers["cache-control"] == "no-store"
    assert len(body["staging_ref"]) == 43
    assert body["filename"] == "data.csv"
    assert body["format"] == "csv"
    assert body["byte_size"] == len(_CSV)
    assert body["shape"] == {"row_count": 3, "column_count": 3}
    assert body["worksheets"] is None
    assert body["selected_worksheet"] is None
    assert body["problems"] == []
    assert body["can_run"] is True
    assert datetime.fromisoformat(body["expires_at"]) > datetime.now(UTC)
    assert _staged_count(client) == 1
    assert _analysis_count(client) == 0


def test_the_staging_response_never_carries_a_hash_or_the_file_content(
    client: TestClient,
) -> None:
    body = _stage(client).json()
    serialized = str(body).lower()

    assert hashlib.sha256(_CSV).hexdigest() not in serialized
    assert set(body) == {
        "staging_ref",
        "expires_at",
        "filename",
        "format",
        "byte_size",
        "worksheets",
        "selected_worksheet",
        "shape",
        "problems",
        "notices",
        "checks",
        "can_run",
    }
    assert "ada" not in serialized and "grace" not in serialized


def test_the_checks_summary_is_business_language_and_names_no_detector(
    client: TestClient,
) -> None:
    checks = _stage(client).json()["checks"]

    assert len(checks) >= 5
    for group in checks:
        assert group["title"] and group["description"]
        for text_value in (group["title"], group["description"]):
            assert "_" not in text_value
            assert "detector" not in text_value.lower()
    assert not any("structural." in str(group) for group in checks)


# --- unreadable files are reported before Run, in fixed text ---------------


def test_a_file_that_is_not_utf8_is_reported_and_not_stored(client: TestClient) -> None:
    response = _stage(client, b"\xff\xfeid,name\n1,\xe9\n")

    assert response.status_code == 200
    body = response.json()
    assert body["staging_ref"] is None
    assert body["expires_at"] is None
    assert body["can_run"] is False
    assert [problem["code"] for problem in body["problems"]] == ["FILE_NOT_UTF8"]
    assert "UTF-8" in body["problems"][0]["message"]
    assert _staged_count(client) == 0
    assert _analysis_count(client) == 0


@pytest.mark.parametrize(
    ("content", "env", "code"),
    [
        (b"\n", {}, "NO_HEADER_ROW"),
        (b"a,b\n1,2\n3,4\n5,6\n", {"MAX_ROWS": "2"}, "ROW_LIMIT_EXCEEDED"),
        (b"a,b,c\n1,2,3\n", {"MAX_COLUMNS": "2"}, "COLUMN_LIMIT_EXCEEDED"),
    ],
)
def test_other_unreadable_csv_files_are_reported_by_code_and_not_stored(
    make_client: Callable[..., TestClient], content: bytes, env: dict[str, str], code: str
) -> None:
    client = make_client(**env)

    response = _stage(client, content)

    assert response.status_code == 200
    body = response.json()
    assert body["staging_ref"] is None
    assert [problem["code"] for problem in body["problems"]] == [code]
    assert _staged_count(client) == 0


def test_problem_text_never_echoes_file_content(client: TestClient) -> None:
    header = f"{_SENTINEL},b\n".encode()
    unreadable = header + b"\xff\xfe\n"

    body = _stage(client, unreadable, filename="data.csv").json()

    assert _SENTINEL not in str(body)


def test_uneven_rows_are_a_non_blocking_notice_with_a_count(client: TestClient) -> None:
    body = _stage(client, b"a,b\n1\n2,3,4\n5,6\n").json()

    assert body["can_run"] is True
    notice = next(item for item in body["notices"] if item["code"] == "parsing.ragged_row")
    assert notice["count"] == 2
    assert "2 rows" in notice["message"]
    assert "5,6" not in str(body)


def test_a_macro_enabled_workbook_is_reported_and_not_stored(client: TestClient) -> None:
    content = workbook({"S": [["a", "b"], [1, 2]]}, extra_parts={"xl/vbaProject.bin": b"x"})

    response = _stage(client, content, filename="book.xlsx", content_type=_XLSX_TYPE)

    assert response.status_code == 200
    body = response.json()
    assert body["staging_ref"] is None
    assert [problem["code"] for problem in body["problems"]] == ["MACRO_ENABLED_FILE"]
    assert _staged_count(client) == 0


def test_a_file_that_is_not_a_workbook_is_reported_and_not_stored(client: TestClient) -> None:
    response = _stage(client, b"this is not a zip", filename="book.xlsx", content_type=_XLSX_TYPE)

    assert response.status_code == 200
    body = response.json()
    assert body["staging_ref"] is None
    assert [problem["code"] for problem in body["problems"]] == ["MALFORMED_FILE"]
    assert _staged_count(client) == 0


# --- request-level refusals use the direct-upload codes ---------------------


def test_an_unsupported_extension_is_415_and_nothing_is_stored(client: TestClient) -> None:
    response = _stage(client, b"x", filename="notes.txt")

    assert response.status_code == 415
    assert response.json()["error"]["code"] == "UNSUPPORTED_FILE_TYPE"
    assert _staged_count(client) == 0


def test_a_macro_extension_is_415(client: TestClient) -> None:
    response = _stage(client, b"x", filename="book.xlsm")

    assert response.status_code == 415
    assert _staged_count(client) == 0


def test_an_empty_file_is_400(client: TestClient) -> None:
    response = _stage(client, b"")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_REQUEST"
    assert _staged_count(client) == 0


def test_a_file_over_the_size_limit_is_413_and_nothing_is_stored(
    make_client: Callable[..., TestClient],
) -> None:
    client = make_client(MAX_FILE_SIZE_MB="1")

    response = _stage(client, b"a,b\n" + b"1,2\n" * (1024 * 1024 // 4 + 10))

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "FILE_TOO_LARGE"
    assert _staged_count(client) == 0


def test_a_filename_with_markup_is_returned_sanitized(client: TestClient) -> None:
    raw = "<script>alert(1)</script>.csv"
    staged = _stage(client, filename=raw).json()
    direct = client.post("/api/v1/analyses", files={"file": (raw, _CSV, "text/csv")}).json()

    # Staging shares direct upload's sanitizer, so both report the same name,
    # and the name is returned as JSON data (rendered as inert text).
    assert staged["filename"] == direct["analysis"]["dataset"]["original_filename"]
    assert "/" not in staged["filename"] and "<script" not in staged["filename"]
    assert staged["filename"].endswith(".csv")


# --- bounds -----------------------------------------------------------------


def test_staging_beyond_the_count_bound_is_409_with_the_wait_time(
    make_client: Callable[..., TestClient],
) -> None:
    client = make_client(STAGING_MAX_COUNT="1", STAGING_TTL_MINUTES="45")
    assert _stage(client).status_code == 201

    response = _stage(client, b"x,y\n1,2\n")

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "STAGING_FULL"
    assert error["details"] == {"ttl_minutes": 45}
    assert _staged_count(client) == 1


def test_staging_beyond_the_total_bytes_bound_is_409(
    make_client: Callable[..., TestClient],
) -> None:
    client = make_client(STAGING_MAX_TOTAL_MB="1")
    big = b"a,b\n" + b"1,2\n" * (700 * 1024 // 4)
    assert _stage(client, big).status_code == 201

    response = _stage(client, big)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "STAGING_FULL"


def test_a_discarded_file_frees_its_slot(make_client: Callable[..., TestClient]) -> None:
    client = make_client(STAGING_MAX_COUNT="1")
    ref = _stage(client).json()["staging_ref"]
    assert _stage(client).status_code == 409

    assert _discard(client, ref).status_code == 204

    assert _stage(client).status_code == 201


# --- inspect ----------------------------------------------------------------


def test_inspect_returns_the_same_facts_and_does_not_start_anything(
    client: TestClient,
) -> None:
    staged = _stage(client).json()

    inspected = _inspect(client, staged["staging_ref"])

    assert inspected.status_code == 200
    assert inspected.headers["cache-control"] == "no-store"
    body = inspected.json()
    assert body["shape"] == staged["shape"]
    assert body["expires_at"] == staged["expires_at"]
    assert body["staging_ref"] == staged["staging_ref"]
    assert _analysis_count(client) == 0


@pytest.mark.parametrize("bad", ["not-a-reference", "", "A" * 43, "a" * 42 + "!", "é" * 43])
def test_an_unknown_or_malformed_reference_is_410_everywhere(client: TestClient, bad: str) -> None:
    for response in (_inspect(client, bad), _run(client, bad)):
        assert response.status_code == 410
        assert response.json()["error"]["code"] == "STAGED_UPLOAD_UNAVAILABLE"
    assert _discard(client, bad).status_code == 204


def test_an_overlong_reference_is_a_validation_error_not_a_lookup(client: TestClient) -> None:
    response = _inspect(client, "a" * 1000)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


def test_a_reference_in_a_url_is_not_a_route(client: TestClient) -> None:
    ref = _stage(client).json()["staging_ref"]

    assert client.get(f"/api/v1/staged-uploads/{ref}").status_code in {404, 405}
    assert client.delete(f"/api/v1/staged-uploads/{ref}").status_code in {404, 405}
    assert client.post(f"/api/v1/staged-uploads/{ref}/run").status_code in {404, 405}
    # And the file is still there: none of those touched it.
    assert _inspect(client, ref).status_code == 200


# --- worksheets -------------------------------------------------------------


def _two_sheets() -> bytes:
    return workbook(
        {
            "Alpha": [["id", "name"], [1, "a"], [2, "b"]],
            "Beta": [["x", "y", "z"], [1, 2, 3]],
        }
    )


def test_a_workbook_with_several_visible_sheets_needs_a_choice(client: TestClient) -> None:
    response = _stage(client, _two_sheets(), filename="book.xlsx", content_type=_XLSX_TYPE)

    assert response.status_code == 201
    body = response.json()
    assert [sheet["name"] for sheet in body["worksheets"]] == ["Alpha", "Beta"]
    assert body["selected_worksheet"] is None
    assert body["shape"] is None
    assert body["problems"] == []
    assert body["can_run"] is False


def test_inspecting_a_chosen_worksheet_returns_its_shape(client: TestClient) -> None:
    ref = _stage(client, _two_sheets(), filename="book.xlsx", content_type=_XLSX_TYPE).json()[
        "staging_ref"
    ]

    body = _inspect(client, ref, "Beta").json()

    assert body["selected_worksheet"] == "Beta"
    assert body["shape"] == {"row_count": 1, "column_count": 3}
    assert body["can_run"] is True


def test_a_single_visible_sheet_is_preselected(client: TestClient) -> None:
    content = workbook({"Data": [["id"], [1]], "Hidden": [["z"], [9]]}, hidden=["Hidden"])

    body = _stage(client, content, filename="book.xlsx", content_type=_XLSX_TYPE).json()

    assert body["selected_worksheet"] == "Data"
    assert body["shape"] == {"row_count": 1, "column_count": 1}
    assert body["can_run"] is True


def test_inspecting_an_unknown_worksheet_is_400_with_the_names(client: TestClient) -> None:
    ref = _stage(client, _two_sheets(), filename="book.xlsx", content_type=_XLSX_TYPE).json()[
        "staging_ref"
    ]

    response = _inspect(client, ref, "Gamma")

    assert response.status_code == 400
    error = response.json()["error"]
    assert error["code"] == "INVALID_REQUEST"
    assert error["details"]["worksheets"] == ["Alpha", "Beta"]
    # A bad worksheet choice does not spend the reference.
    assert _inspect(client, ref, "Alpha").status_code == 200


def test_a_worksheet_for_a_csv_is_400(client: TestClient) -> None:
    ref = _stage(client).json()["staging_ref"]

    response = _inspect(client, ref, "Sheet1")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


def test_worksheet_names_with_markup_are_returned_as_inert_data(client: TestClient) -> None:
    hostile = "<img src=x onerror=alert(1)>"
    content = workbook({hostile: [["a"], [1]], "Other": [["b"], [2]]})

    response = _stage(client, content, filename="book.xlsx", content_type=_XLSX_TYPE)

    assert response.headers["content-type"].startswith("application/json")
    assert [sheet["name"] for sheet in response.json()["worksheets"]] == [hostile, "Other"]


def test_a_sheet_with_no_data_is_a_worksheet_problem_that_keeps_the_workbook(
    client: TestClient,
) -> None:
    content = workbook({"Data": [["id"], [1]], "Empty": []})
    staged = _stage(client, content, filename="book.xlsx", content_type=_XLSX_TYPE).json()
    ref = staged["staging_ref"]
    assert staged["staging_ref"] is not None

    body = _inspect(client, ref, "Empty").json()

    assert [problem["code"] for problem in body["problems"]] == ["WORKSHEET_UNREADABLE"]
    assert body["can_run"] is False
    assert _inspect(client, ref, "Data").json()["can_run"] is True


# --- run: exactly the staged bytes ------------------------------------------


def test_run_analyses_exactly_the_staged_bytes_and_spends_the_reference(
    client: TestClient,
) -> None:
    ref = _stage(client).json()["staging_ref"]
    assert _analysis_count(client) == 0

    response = _run(client, ref)

    assert response.status_code == 202
    assert response.headers["cache-control"] == "no-store"
    body = response.json()
    dataset = body["analysis"]["dataset"]
    assert dataset["content_hash"] == hashlib.sha256(_CSV).hexdigest()
    assert dataset["byte_size"] == len(_CSV)
    assert dataset["original_filename"] == "data.csv"
    assert dataset["format"] == "csv"
    assert dataset["selected_worksheet"] is None
    assert body["status_url"].endswith(f"/analyses/{body['analysis']['analysis_id']}/status")
    assert _analysis_count(client) == 1
    assert _staged_count(client) == 0


def test_run_of_a_workbook_uses_the_chosen_worksheet(client: TestClient) -> None:
    ref = _stage(client, _two_sheets(), filename="book.xlsx", content_type=_XLSX_TYPE).json()[
        "staging_ref"
    ]

    response = _run(client, ref, "Beta")

    assert response.status_code == 202
    dataset = response.json()["analysis"]["dataset"]
    assert dataset["selected_worksheet"] == "Beta"
    assert dataset["format"] == "xlsx"


def test_run_without_a_needed_worksheet_is_refused_and_does_not_spend_the_reference(
    client: TestClient,
) -> None:
    ref = _stage(client, _two_sheets(), filename="book.xlsx", content_type=_XLSX_TYPE).json()[
        "staging_ref"
    ]

    refused = _run(client, ref)

    assert refused.status_code == 400
    assert refused.json()["error"]["code"] == "WORKSHEET_REQUIRED"
    assert _analysis_count(client) == 0
    assert _staged_count(client) == 1
    assert _run(client, ref, "Alpha").status_code == 202


def test_run_of_a_worksheet_with_a_blocking_problem_is_refused_and_keeps_the_file(
    client: TestClient,
) -> None:
    content = workbook({"Data": [["id"], [1]], "Empty": []})
    ref = _stage(client, content, filename="book.xlsx", content_type=_XLSX_TYPE).json()[
        "staging_ref"
    ]

    refused = _run(client, ref, "Empty")

    assert refused.status_code == 400
    error = refused.json()["error"]
    assert error["code"] == "STAGED_UPLOAD_NOT_RUNNABLE"
    assert [problem["code"] for problem in error["details"]["problems"]] == ["WORKSHEET_UNREADABLE"]
    assert _analysis_count(client) == 0
    assert _run(client, ref, "Data").status_code == 202


def test_a_failure_after_the_file_is_consumed_spends_the_reference_and_creates_no_analysis(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The documented fail-closed behavior (`docs/decision-log.md` D-068 item 5):
    if creating the analysis fails after the row was consumed, the reference stays
    spent, nothing half-created is left behind, and a retry cannot run the file."""
    import trusttable_backend.api.v1.staged_uploads as routes

    def explode(*args: object, **kwargs: object) -> None:
        raise RuntimeError("simulated failure while creating the analysis")

    monkeypatch.setattr(routes, "start_analysis_from_content", explode)
    with TestClient(create_app(), raise_server_exceptions=False) as client:
        ref = _stage(client).json()["staging_ref"]

        failed = _run(client, ref)

        assert failed.status_code == 500
        assert failed.json()["error"]["code"] == "INTERNAL_ERROR"
        assert "simulated failure" not in failed.text  # no raw exception text
        assert _analysis_count(client) == 0
        assert _staged_count(client) == 0
        retry = _run(client, ref)
        assert retry.status_code == 410
        assert retry.json()["error"]["code"] == "STAGED_UPLOAD_UNAVAILABLE"
        assert _inspect(client, ref).status_code == 410


def test_a_second_run_of_the_same_reference_is_410_and_adds_no_analysis(
    client: TestClient,
) -> None:
    ref = _stage(client).json()["staging_ref"]
    assert _run(client, ref).status_code == 202

    second = _run(client, ref)

    assert second.status_code == 410
    assert second.json()["error"]["code"] == "STAGED_UPLOAD_UNAVAILABLE"
    assert _analysis_count(client) == 1
    assert _inspect(client, ref).status_code == 410


def test_concurrent_runs_of_one_reference_create_exactly_one_analysis(
    client: TestClient,
) -> None:
    ref = _stage(client).json()["staging_ref"]

    with ThreadPoolExecutor(max_workers=8) as pool:
        statuses = list(pool.map(lambda _: _run(client, ref).status_code, range(8)))

    assert statuses.count(202) == 1
    assert statuses.count(410) == 7
    assert _analysis_count(client) == 1


def test_discard_removes_the_file_and_is_idempotent(client: TestClient) -> None:
    ref = _stage(client).json()["staging_ref"]

    first = _discard(client, ref)
    second = _discard(client, ref)

    assert first.status_code == 204 and second.status_code == 204
    assert first.headers["cache-control"] == "no-store"
    assert _inspect(client, ref).status_code == 410
    assert _run(client, ref).status_code == 410
    assert _analysis_count(client) == 0


# --- expiry and cleanup -----------------------------------------------------


def test_an_expired_file_is_unavailable_to_inspect_and_run(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    ref = _stage(client).json()["staging_ref"]
    store = client.app.state.staging_store  # type: ignore[attr-defined]
    later = datetime.now(UTC) + store.ttl + timedelta(seconds=1)
    monkeypatch.setattr(store, "_clock", lambda: later)

    assert _inspect(client, ref).status_code == 410
    assert _run(client, ref).status_code == 410
    assert _analysis_count(client) == 0
    assert _staged_count(client) == 0


def test_startup_removes_files_that_expired_while_the_app_was_down(
    make_client: Callable[..., TestClient], tmp_path: Path
) -> None:
    first = make_client()
    ref = _stage(first).json()["staging_ref"]
    assert ref is not None
    database = tmp_path / "trusttable-test.db"
    past = (datetime.now(UTC) - timedelta(hours=1)).isoformat(timespec="microseconds")
    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE staged_uploads SET expires_at = ?", (past,))
    assert _staged_count(first) == 1

    second = make_client()

    assert _staged_count(second) == 0


# --- integrity --------------------------------------------------------------


def test_run_refuses_bytes_that_no_longer_match_the_recorded_digest(
    client: TestClient,
) -> None:
    ref = _stage(client).json()["staging_ref"]
    with build_session_factory(client.app.state.analysis_engine)() as session:  # type: ignore[attr-defined]
        session.execute(
            text("UPDATE staged_uploads SET content = :tampered"),
            {"tampered": b"id,name\n9,Mallory\n"},
        )
        session.commit()

    response = _run(client, ref)

    assert response.status_code == 410
    assert _analysis_count(client) == 0
    # The corrupted row is removed rather than kept.
    assert _staged_count(client) == 0


# --- the reference never leaks ---------------------------------------------


def test_the_reference_is_never_logged_or_echoed_in_errors(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level(logging.DEBUG)
    ref = _stage(client).json()["staging_ref"]
    responses = [
        _inspect(client, ref),
        _inspect(client, ref, "Nope"),
        _run(client, ref),
        _run(client, ref),
        _inspect(client, ref),
        _discard(client, ref),
    ]

    assert ref not in caplog.text
    for response in responses:
        assert ref not in str(response.headers)
        if response.status_code >= 400:
            # Error bodies never echo the reference the caller sent.
            assert ref not in response.text


# --- direct upload is untouched ---------------------------------------------


def test_direct_upload_still_works_and_does_not_touch_staging(client: TestClient) -> None:
    response = client.post("/api/v1/analyses", files={"file": ("data.csv", _CSV, "text/csv")})

    assert response.status_code == 202
    assert _analysis_count(client) == 1
    assert _staged_count(client) == 0
