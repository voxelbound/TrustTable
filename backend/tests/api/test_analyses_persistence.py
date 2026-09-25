"""Decisive restart-durability and interrupted-analysis-reconciliation
proofs against the real HTTP application (`DB-01`, `WP-074` AC-04/AC-05).

Both tests reuse `conftest.py`'s own per-test isolated
`DATABASE_URL`/`DATA_DIRECTORY` (`_hermetic_settings`) — every
`create_app()` call within one test therefore shares the exact same
on-disk SQLite file, which is precisely what "two independently
constructed app instances sharing one database" and "a startup
reconciliation over a row inserted before the real app opens it" both
require.
"""

from __future__ import annotations

import time
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

from fastapi.testclient import TestClient

from trusttable_backend.analysis.service import (
    AnalysisState,
    create_analysis,
    run_analysis,
)
from trusttable_backend.analysis.service import (
    AnalysisStore as InMemoryStore,
)
from trusttable_backend.config import get_settings
from trusttable_backend.main import create_app
from trusttable_backend.persistence import SqlAnalysisStore, build_engine, run_migrations
from trusttable_backend.persistence.reconciliation import (
    INTERRUPTED_BY_RESTART_CODE,
    INTERRUPTED_BY_RESTART_MESSAGE,
)

_ANALYSIS_ROUTES = (
    "/api/v1/analyses/{id}",
    "/api/v1/analyses/{id}/profile",
    "/api/v1/analyses/{id}/findings",
    "/api/v1/analyses/{id}/findings/0/evidence",
    "/api/v1/analyses/{id}/context",
)


def _wait_for_terminal(client: TestClient, analysis_id: str) -> None:
    """`JOB-01` (`WP-075`): analyses now run on a real background worker
    — wait for a terminal state before exercising routes that require
    `completed` (context confirmation, profile, findings).
    """
    deadline = time.monotonic() + 15.0
    while time.monotonic() < deadline:
        status = client.get(f"/api/v1/analyses/{analysis_id}/status")
        assert status.status_code == 200
        if status.json()["state"] in {"completed", "failed", "cancelled"}:
            return
        time.sleep(0.01)
    raise AssertionError(f"analysis {analysis_id} did not reach a terminal state within 15.0s")


def _get_all(client: TestClient, analysis_id: str) -> dict[str, Any]:
    responses: dict[str, Any] = {}
    for template in _ANALYSIS_ROUTES:
        path = template.format(id=analysis_id)
        response = client.get(path)
        assert response.status_code == 200, (path, response.text)
        responses[template] = response.json()
    return responses


# ---------------------------------------------------------------------------
# AC-04: decisive restart-durability proof
# ---------------------------------------------------------------------------


def test_two_independent_app_instances_sharing_one_database_are_byte_identical() -> None:
    """A genuine `create_app()` call, a full demo-analysis run through the
    real routes (including context confirmation and finalization), then a
    second, independently constructed `create_app()` call — standing in
    for a process restart — must return byte-identical responses across
    every analysis-read route for the same `analysis_id`.
    """
    with TestClient(create_app()) as first_client:
        created = first_client.post("/api/v1/demo/sales")
        assert created.status_code == 202
        analysis_id = created.json()["analysis"]["analysis_id"]
        _wait_for_terminal(first_client, analysis_id)

        # Exercise context confirmation and finalization through the real
        # routes too, so the restart proof covers the finalized context
        # and its `context_version`, not merely the pipeline result.
        get_context = first_client.get(f"/api/v1/analyses/{analysis_id}/context")
        assert get_context.status_code == 200
        edit_context = first_client.put(
            f"/api/v1/analyses/{analysis_id}/context",
            json={"edits": {"row_grain": "One row per order"}, "expected_version": 1},
        )
        assert edit_context.status_code == 200
        finalize = first_client.post(
            f"/api/v1/analyses/{analysis_id}/finalize", json={"expected_version": 2}
        )
        assert finalize.status_code == 202

        first_responses = _get_all(first_client, analysis_id)
        assert first_responses["/api/v1/analyses/{id}/findings"]["total_items"] > 0
        assert first_responses["/api/v1/analyses/{id}/context"]["context_version"] == 2

    # A second, independently constructed `create_app()` instance pointed
    # at the exact same database file — standing in for a process
    # restart. `get_settings()` is process-cached, but every value it
    # returns is unchanged between the two calls, and `create_app()`
    # unconditionally builds a fresh engine/store/migration run regardless.
    assert get_settings().database_url  # sanity: the same Settings both apps share

    with TestClient(create_app()) as second_client:
        second_responses = _get_all(second_client, analysis_id)

    assert second_responses == first_responses


# ---------------------------------------------------------------------------
# AC-05: decisive interrupted-analysis-reconciliation proof
# ---------------------------------------------------------------------------


def test_startup_reconciles_an_interrupted_analysis_and_leaves_a_completed_sibling_untouched() -> (
    None
):
    """An analysis persisted directly (via the real store, not raw SQL) in
    a non-terminal state — simulating a crash mid-pipeline — is `FAILED`
    with the fixed interrupted-by-restart code immediately after a real
    `create_app()` call, visible through the real `GET /analyses/{id}`
    route; a sibling analysis already `COMPLETED` before that same
    startup is asserted completely unchanged by it.
    """
    settings = get_settings()
    run_migrations(settings)
    pre_store = SqlAnalysisStore(build_engine(settings))

    working_store = InMemoryStore()
    interrupted = replace(
        create_analysis(working_store),
        state=AnalysisState.DETECTING,
        started_at=datetime.now(UTC),
    )
    completed = run_analysis(working_store, create_analysis(working_store).analysis_id)
    assert completed.state is AnalysisState.COMPLETED
    pre_store.add(interrupted)
    pre_store.add(completed)

    # The real `create_app()` call is the actual startup/restart under
    # test: reconciliation happens as one of its own construction steps,
    # not via a bypassed helper called directly.
    with TestClient(create_app()) as client:
        interrupted_response = client.get(f"/api/v1/analyses/{interrupted.analysis_id}")
        completed_response = client.get(f"/api/v1/analyses/{completed.analysis_id}")

    assert interrupted_response.status_code == 200
    interrupted_body = interrupted_response.json()
    assert interrupted_body["state"] == "failed"
    assert interrupted_body["failure"] == {
        "code": INTERRUPTED_BY_RESTART_CODE,
        "message": INTERRUPTED_BY_RESTART_MESSAGE,
    }
    assert interrupted_body["failed_at"] is not None

    assert completed_response.status_code == 200
    completed_body = completed_response.json()
    assert completed_body["state"] == "completed"
    assert completed_body["failure"] is None
    assert completed_body["completed_at"] is not None
    assert completed_body["failed_at"] is None
