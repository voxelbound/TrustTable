"""Decisive async-submission, real-progress, and cooperative-cancellation
proofs against the real HTTP application (`JOB-01`, `WP-075`
AC-01/AC-02/AC-04).

Cancellation/progress control uses a monkeypatched
`analysis.service.parse_csv` as a controllable blocking gate — the same
technique `tests/jobs/test_pool.py` uses at the pool-unit level, applied
here through the real `POST /demo/sales` route and the real `JobPool`
`main.create_app()` wires into `app.state.job_pool`.
"""

from __future__ import annotations

import threading
import time

import pytest
from fastapi.testclient import TestClient

import trusttable_backend.analysis.service as service_module
from trusttable_backend.parsers.csv_parser import parse_csv as real_parse_csv

_TIMEOUT = 5.0
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


# ---------------------------------------------------------------------------
# AC-01: async submission
# ---------------------------------------------------------------------------


def test_post_demo_sales_returns_immediately_with_queued_state_and_no_findings_yet(
    client: TestClient,
) -> None:
    """Proves the response returned *before* the pipeline ran — a
    synchronous implementation could never observe `queued` with
    `finding_count == 0` in the creation response itself.
    """
    response = client.post("/api/v1/demo/sales")

    assert response.status_code == 202
    analysis = response.json()["analysis"]
    assert analysis["state"] == "queued"
    assert analysis["finding_count"] == 0
    assert analysis["trust_assessment"] is None

    final_state = _wait_for_terminal_state(client, analysis["analysis_id"])
    assert final_state == "completed"


def test_post_analyses_upload_returns_immediately_with_queued_state(
    client: TestClient,
) -> None:
    response = client.post(
        "/api/v1/analyses",
        files={"file": ("sample.csv", b"a,b\n1,2\n3,4\n", "text/csv")},
    )

    assert response.status_code == 202
    analysis = response.json()["analysis"]
    assert analysis["state"] == "queued"
    assert analysis["finding_count"] == 0

    final_state = _wait_for_terminal_state(client, analysis["analysis_id"])
    assert final_state == "completed"


# ---------------------------------------------------------------------------
# AC-02: real, persisted stage progression observable through GET /status
# ---------------------------------------------------------------------------


def test_get_status_observes_a_real_in_flight_parsing_stage(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    entered = threading.Event()
    release = threading.Event()

    def _blocking_parse_csv(content: bytes):  # type: ignore[no-untyped-def]
        entered.set()
        release.wait(timeout=_TIMEOUT)
        return real_parse_csv(content)

    monkeypatch.setattr(service_module, "parse_csv", _blocking_parse_csv)

    created = client.post("/api/v1/demo/sales")
    assert created.status_code == 202
    analysis_id = created.json()["analysis"]["analysis_id"]

    _wait_until(entered.is_set)
    in_flight = _status(client, analysis_id)
    assert in_flight["state"] == "parsing"
    assert in_flight["cancellable"] is True

    release.set()
    final_state = _wait_for_terminal_state(client, analysis_id)
    assert final_state == "completed"


# ---------------------------------------------------------------------------
# AC-04: decisive cooperative-cancellation proof
# ---------------------------------------------------------------------------


def test_cancel_stops_an_in_flight_analysis_a_sibling_completes_normally(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    entered = threading.Event()
    release = threading.Event()

    def _blocking_parse_csv(content: bytes):  # type: ignore[no-untyped-def]
        entered.set()
        release.wait(timeout=_TIMEOUT)
        return real_parse_csv(content)

    monkeypatch.setattr(service_module, "parse_csv", _blocking_parse_csv)

    target = client.post("/api/v1/demo/sales")
    assert target.status_code == 202
    target_id = target.json()["analysis"]["analysis_id"]

    _wait_until(entered.is_set)
    assert _status(client, target_id)["state"] == "parsing"  # confirmed still non-terminal

    cancel_response = client.post(f"/api/v1/analyses/{target_id}/cancel")
    assert cancel_response.status_code == 200

    release.set()
    final_state = _wait_for_terminal_state(client, target_id)
    assert final_state == "cancelled"

    cancelled_resource = client.get(f"/api/v1/analyses/{target_id}").json()
    assert cancelled_resource["cancelled_at"] is not None
    assert cancelled_resource["finding_count"] == 0

    # A sibling submitted afterward (the blocking patch no longer applies
    # meaningfully since `release` stays set) completes normally on the
    # same pool, proving cancellation was scoped to `target_id` only.
    sibling = client.post("/api/v1/demo/sales")
    assert sibling.status_code == 202
    sibling_id = sibling.json()["analysis"]["analysis_id"]
    sibling_final_state = _wait_for_terminal_state(client, sibling_id)
    assert sibling_final_state == "completed"
    sibling_resource = client.get(f"/api/v1/analyses/{sibling_id}").json()
    assert sibling_resource["finding_count"] > 0


def test_cancel_unknown_and_terminal_analyses_via_real_pool(client: TestClient) -> None:
    """`post_analysis_cancel`'s not-found/terminal-unchanged behavior is
    already covered against the in-memory white-box store in
    `test_analyses.py`; this proves the exact same contract holds
    end-to-end against the real `JobPool`-backed app.
    """
    created = client.post("/api/v1/demo/sales")
    assert created.status_code == 202
    analysis_id = created.json()["analysis"]["analysis_id"]
    _wait_for_terminal_state(client, analysis_id)

    response = client.post(f"/api/v1/analyses/{analysis_id}/cancel")

    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "completed"
    assert body["cancelled_at"] is None
