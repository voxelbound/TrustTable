"""Decisive retry-endpoint proof against the real HTTP application
(`JOB-01` slice 2, `WP-076`; `project-ops/decisions/
013-job01-retry-creates-new-analysis.md`, `DEC-013`: retry creates a
new, independent analysis, never a versioned attempt reusing the same
`analysis_id`).

Fault injection uses the same `analysis.service.parse_csv` monkeypatch
technique as `test_service.py`'s AC-10 test and `test_analyses_async.py`'s
cancellation tests, applied through the real `POST /demo/sales` route and
the real `JobPool` `main.create_app()` wires into `app.state.job_pool`, so
a real `FAILED` analysis exists to retry.
"""

from __future__ import annotations

import threading
import time

import pytest
from fastapi.testclient import TestClient

import trusttable_backend.analysis.service as service_module
from trusttable_backend.parsers.csv_parser import parse_csv as real_parse_csv

_TIMEOUT = 15.0
_TERMINAL_STATES = {"completed", "failed", "cancelled"}


def _wait_until(predicate, *, timeout: float = _TIMEOUT) -> None:  # type: ignore[no-untyped-def]
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError(f"condition not met within {timeout}s")


def _status(client: TestClient, analysis_id: str) -> dict[str, object]:
    response = client.get(f"/api/v1/analyses/{analysis_id}/status")
    assert response.status_code == 200
    return response.json()  # type: ignore[no-any-return]


def _wait_for_terminal_state(client: TestClient, analysis_id: str) -> str:
    _wait_until(lambda: _status(client, analysis_id)["state"] in _TERMINAL_STATES)
    state = _status(client, analysis_id)["state"]
    assert isinstance(state, str)
    return state


def _create_failed_analysis(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> str:
    """Create a real `FAILED` analysis, then restore `parse_csv` before
    returning — a subsequent retry (or any other analysis created in the
    same test) must run the real pipeline, not remain patched to fail.
    """

    def _boom(*args: object, **kwargs: object) -> object:
        raise RuntimeError("synthetic pipeline failure for retry tests")

    monkeypatch.setattr(service_module, "parse_csv", _boom)
    created = client.post("/api/v1/demo/sales")
    assert created.status_code == 202
    analysis_id = created.json()["analysis"]["analysis_id"]
    assert _wait_for_terminal_state(client, analysis_id) == "failed"
    monkeypatch.undo()
    return analysis_id  # type: ignore[no-any-return]


# ---------------------------------------------------------------------------
# AC-01/AC-02: retry creates a new analysis, genuinely submitted to the pool
# ---------------------------------------------------------------------------


def test_retry_creates_a_new_analysis_that_reaches_a_terminal_state(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_id = _create_failed_analysis(client, monkeypatch)

    response = client.post(f"/api/v1/analyses/{original_id}/retry")

    assert response.status_code == 202
    body = response.json()
    assert body["retry_source_analysis_id"] == original_id
    new_id = body["analysis"]["analysis_id"]
    assert new_id != original_id
    assert body["analysis"]["state"] == "queued"
    assert body["status_url"] == f"/api/v1/analyses/{new_id}/status"

    final_state = _wait_for_terminal_state(client, new_id)
    assert final_state == "completed"


# ---------------------------------------------------------------------------
# AC-03: the original FAILED analysis is unchanged after a retry
# ---------------------------------------------------------------------------


def test_retry_does_not_mutate_the_original_analysis(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    original_id = _create_failed_analysis(client, monkeypatch)
    before = client.get(f"/api/v1/analyses/{original_id}").json()

    retry_response = client.post(f"/api/v1/analyses/{original_id}/retry")
    assert retry_response.status_code == 202
    _wait_for_terminal_state(client, retry_response.json()["analysis"]["analysis_id"])

    after = client.get(f"/api/v1/analyses/{original_id}").json()
    assert after == before
    assert after["state"] == "failed"


# ---------------------------------------------------------------------------
# AC-04: negative cases (409 non-retryable, 404 unknown)
# ---------------------------------------------------------------------------


def test_retry_completed_analysis_returns_409_not_retryable(client: TestClient) -> None:
    created = client.post("/api/v1/demo/sales")
    analysis_id = created.json()["analysis"]["analysis_id"]
    assert _wait_for_terminal_state(client, analysis_id) == "completed"

    response = client.post(f"/api/v1/analyses/{analysis_id}/retry")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ANALYSIS_NOT_RETRYABLE"


def test_retry_cancelled_analysis_returns_409_not_retryable(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    entered = threading.Event()
    release = threading.Event()

    def _blocking_parse_csv(content: bytes, **kwargs):  # type: ignore[no-untyped-def]
        entered.set()
        release.wait(timeout=_TIMEOUT)
        return real_parse_csv(content, **kwargs)

    monkeypatch.setattr(service_module, "parse_csv", _blocking_parse_csv)

    created = client.post("/api/v1/demo/sales")
    analysis_id = created.json()["analysis"]["analysis_id"]
    _wait_until(entered.is_set)
    client.post(f"/api/v1/analyses/{analysis_id}/cancel")
    release.set()
    assert _wait_for_terminal_state(client, analysis_id) == "cancelled"

    response = client.post(f"/api/v1/analyses/{analysis_id}/retry")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ANALYSIS_NOT_RETRYABLE"


def test_retry_immediately_after_creation_returns_409_not_retryable(client: TestClient) -> None:
    """Retry is rejected immediately after creation regardless of exactly
    which non-`FAILED` state the analysis is in at that instant
    (`queued` or already a later in-flight stage) — `retryable` is only
    ever `true` for `FAILED`.
    """
    created = client.post("/api/v1/demo/sales")
    analysis_id = created.json()["analysis"]["analysis_id"]

    response = client.post(f"/api/v1/analyses/{analysis_id}/retry")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "ANALYSIS_NOT_RETRYABLE"
    _wait_for_terminal_state(client, analysis_id)  # drain before the test ends


def test_retry_unknown_analysis_returns_404(client: TestClient) -> None:
    response = client.post("/api/v1/analyses/unknown-id/retry")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ANALYSIS_NOT_FOUND"


# ---------------------------------------------------------------------------
# AC-05: GET /status's retryable field
# ---------------------------------------------------------------------------


def test_status_retryable_is_true_only_for_failed(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    failed_id = _create_failed_analysis(client, monkeypatch)
    assert _status(client, failed_id)["retryable"] is True

    completed = client.post("/api/v1/demo/sales")
    completed_id = completed.json()["analysis"]["analysis_id"]
    _wait_for_terminal_state(client, completed_id)
    assert _status(client, completed_id)["retryable"] is False
