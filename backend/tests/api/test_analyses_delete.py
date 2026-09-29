"""HTTP proof for `DELETE /api/v1/analyses/{analysis_id}` (`DEL-01`) against
the real application, store, job pool and SQLite database file."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable, Iterator
from concurrent.futures import Future
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from trusttable_backend.analysis import service as analysis_service
from trusttable_backend.jobs import JobPool

_TERMINAL = {"completed", "failed", "cancelled"}
_MARKER = "ZZ-UNIQUE-UPLOAD-MARKER-7f3a91c2"


def _wait_state(client: TestClient, analysis_id: str, states: set[str]) -> str:
    deadline = time.monotonic() + 15.0
    while time.monotonic() < deadline:
        response = client.get(f"/api/v1/analyses/{analysis_id}/status")
        if response.status_code == 200 and response.json()["state"] in states:
            state: str = response.json()["state"]
            return state
        time.sleep(0.01)
    raise AssertionError(f"analysis never reached {states}")


def _completed(client: TestClient) -> str:
    analysis_id: str = client.post("/api/v1/demo/sales").json()["analysis"]["analysis_id"]
    assert _wait_state(client, analysis_id, _TERMINAL) == "completed"
    return analysis_id


def _report(client: TestClient, analysis_id: str, **options: bool) -> str:
    response = client.post(f"/api/v1/analyses/{analysis_id}/reports", json={"options": options})
    assert response.status_code == 201
    report_id: str = response.json()["report_id"]
    return report_id


def _row_count(client: TestClient, table: str, analysis_id: str) -> int:
    engine = client.app.state.analysis_engine  # type: ignore[attr-defined]
    with engine.connect() as connection:
        return int(
            connection.execute(
                text(f"SELECT COUNT(*) FROM {table} WHERE analysis_id = :id"),  # noqa: S608
                {"id": analysis_id},
            ).scalar_one()
        )


def _upload_with_marker(client: TestClient) -> str:
    csv = f"name,amount\n{_MARKER},10\nbeta,20\ngamma,30\n".encode()
    response = client.post("/api/v1/analyses", files={"file": ("marker.csv", csv, "text/csv")})
    assert response.status_code == 202
    analysis_id: str = response.json()["analysis"]["analysis_id"]
    assert _wait_state(client, analysis_id, _TERMINAL) == "completed"
    return analysis_id


def _database_bytes(client: TestClient) -> bytes:
    engine = client.app.state.analysis_engine  # type: ignore[attr-defined]
    path = Path(engine.url.database)
    data = b""
    for candidate in (path, Path(f"{path}-journal"), Path(f"{path}-wal")):
        if candidate.exists():
            data += candidate.read_bytes()
    return data


@pytest.fixture
def worker_futures(monkeypatch: pytest.MonkeyPatch) -> list[Future[None]]:
    futures: list[Future[None]] = []
    original = JobPool.submit

    def capture(self: JobPool, analysis_id: str) -> Future[None]:
        future = original(self, analysis_id)
        futures.append(future)
        return future

    monkeypatch.setattr(JobPool, "submit", capture)
    return futures


@pytest.fixture
def parse_gate(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[tuple[threading.Event, threading.Event]]:
    """Make `parse_csv` block until released, so an analysis can be deleted
    while its worker is genuinely mid-pipeline."""
    entered, release = threading.Event(), threading.Event()
    real: Callable[..., Any] = analysis_service.parse_csv  # type: ignore[attr-defined]

    def gated(*args: Any, **kwargs: Any) -> Any:
        entered.set()
        assert release.wait(timeout=15.0)
        return real(*args, **kwargs)

    monkeypatch.setattr(analysis_service, "parse_csv", gated)
    yield entered, release
    release.set()


def test_delete_returns_204_and_the_analysis_is_gone_everywhere(client: TestClient) -> None:
    analysis_id = _completed(client)
    report_id = _report(client, analysis_id)
    base = f"/api/v1/analyses/{analysis_id}"

    response = client.delete(base)

    assert response.status_code == 204
    assert response.content == b""
    for path in (
        base,
        f"{base}/status",
        f"{base}/profile",
        f"{base}/findings",
        f"{base}/findings/0",
        f"{base}/context",
        f"{base}/rules",
        f"{base}/reports",
        f"{base}/reports/{report_id}",
        f"{base}/reports/{report_id}/download",
        f"{base}/exports/rules.json",
        f"{base}/exports/rules.yaml",
    ):
        got = client.get(path)
        assert got.status_code == 404, path
        assert got.json()["error"]["code"] == "ANALYSIS_NOT_FOUND", path
    assert client.post(f"{base}/reports").status_code == 404
    assert client.post(f"{base}/cancel").status_code == 404


def test_deleting_an_unknown_or_already_deleted_analysis_is_404(client: TestClient) -> None:
    analysis_id = _completed(client)
    assert client.delete(f"/api/v1/analyses/{analysis_id}").status_code == 204

    for target in (analysis_id, "never-existed"):
        response = client.delete(f"/api/v1/analyses/{target}")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "ANALYSIS_NOT_FOUND"


def test_only_the_deleted_analysis_and_its_reports_are_removed(client: TestClient) -> None:
    doomed = _completed(client)
    kept = _completed(client)
    for _ in range(2):
        _report(client, doomed)
    kept_report = _report(client, kept, include_technical_appendix=True)
    assert _row_count(client, "reports", doomed) == 2

    assert client.delete(f"/api/v1/analyses/{doomed}").status_code == 204

    assert _row_count(client, "reports", doomed) == 0
    assert _row_count(client, "analyses", doomed) == 0
    assert client.get(f"/api/v1/analyses/{kept}").status_code == 200
    listed = client.get(f"/api/v1/analyses/{kept}/reports").json()["reports"]
    assert [r["report_id"] for r in listed] == [kept_report]
    download = client.get(f"/api/v1/analyses/{kept}/reports/{kept_report}/download")
    assert download.status_code == 200


def test_deleting_a_running_analysis_cancels_it_and_it_cannot_come_back(
    client: TestClient,
    parse_gate: tuple[threading.Event, threading.Event],
    worker_futures: list[Future[None]],
) -> None:
    entered, release = parse_gate
    analysis_id: str = client.post("/api/v1/demo/sales").json()["analysis"]["analysis_id"]
    assert entered.wait(timeout=15.0), "the worker never reached parsing"
    assert client.get(f"/api/v1/analyses/{analysis_id}/status").json()["state"] == "parsing"

    assert client.delete(f"/api/v1/analyses/{analysis_id}").status_code == 204
    release.set()
    for future in worker_futures:
        future.result(timeout=15.0)  # ends without an unhandled error

    assert client.get(f"/api/v1/analyses/{analysis_id}").status_code == 404
    assert client.get(f"/api/v1/analyses/{analysis_id}/findings").status_code == 404
    assert _row_count(client, "analyses", analysis_id) == 0


def test_a_worker_that_starts_after_deletion_ends_quietly(
    client: TestClient, worker_futures: list[Future[None]]
) -> None:
    pool: JobPool = client.app.state.job_pool  # type: ignore[attr-defined]

    future = pool.submit("never-existed")

    assert future.result(timeout=15.0) is None
    assert future in worker_futures


def test_a_report_created_while_its_analysis_is_being_deleted_is_not_stored(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    analysis_id = _completed(client)
    reports = client.app.state.report_store  # type: ignore[attr-defined]
    store = client.app.state.analysis_store  # type: ignore[attr-defined]
    real_add = reports.add

    def delete_then_add(snapshot: Any) -> bool:
        assert store.delete(snapshot.analysis_id)  # the deletion wins the race
        return bool(real_add(snapshot))

    monkeypatch.setattr(reports, "add", delete_then_add)

    response = client.post(f"/api/v1/analyses/{analysis_id}/reports")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ANALYSIS_NOT_FOUND"
    assert _row_count(client, "reports", analysis_id) == 0


def test_secure_delete_is_enabled_on_the_application_database(client: TestClient) -> None:
    engine = client.app.state.analysis_engine  # type: ignore[attr-defined]
    with engine.connect() as connection:
        assert connection.execute(text("PRAGMA secure_delete")).scalar_one() != 0


def test_the_uploaded_bytes_are_gone_from_the_database_file_after_deletion(
    client: TestClient,
) -> None:
    analysis_id = _upload_with_marker(client)
    _report(client, analysis_id, include_bounded_examples=True, include_technical_appendix=True)
    other = _completed(client)
    marker = _MARKER.encode()
    assert marker in _database_bytes(client), "the control must find the marker before deletion"

    assert client.delete(f"/api/v1/analyses/{analysis_id}").status_code == 204

    assert marker not in _database_bytes(client)
    assert client.get(f"/api/v1/analyses/{other}").status_code == 200
