"""HTTP proof for the confirmed-relationship routes (`DET-03`) against the
real FastAPI application and a real demo analysis."""

from __future__ import annotations

import time
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import text

from trusttable_backend.analysis.service import create_analysis
from trusttable_backend.domain.confirmed_relationship import (
    MAX_ACTIVE_RELATIONSHIPS,
    MAX_VERSIONS_PER_RELATIONSHIP,
)

_TERMINAL = {"completed", "failed", "cancelled"}


def _completed_analysis(client: TestClient) -> str:
    created = client.post("/api/v1/demo/sales")
    assert created.status_code == 202
    analysis_id: str = created.json()["analysis"]["analysis_id"]
    deadline = time.monotonic() + 15.0
    while time.monotonic() < deadline:
        state = client.get(f"/api/v1/analyses/{analysis_id}/status").json()["state"]
        if state in _TERMINAL:
            assert state == "completed"
            return analysis_id
        time.sleep(0.01)
    raise AssertionError("analysis did not finish")


def _keys(client: TestClient, analysis_id: str) -> list[str]:
    profile = client.get(f"/api/v1/analyses/{analysis_id}/profile").json()
    return [entry["column"]["internal_key"] for entry in profile["column_profiles"]]


def _url(analysis_id: str) -> str:
    return f"/api/v1/analyses/{analysis_id}/confirmed-relationships"


def _confirm(client: TestClient, analysis_id: str, start: str, end: str) -> Any:
    return client.post(
        _url(analysis_id),
        json={"transition": "confirm", "kind": "start_end_date", "start": start, "end": end},
    )


def _replace(
    client: TestClient, analysis_id: str, relationship_id: str, version: int, start: str, end: str
) -> Any:
    return client.post(
        _url(analysis_id),
        json={
            "transition": "replace",
            "kind": "start_end_date",
            "relationship_id": relationship_id,
            "expected_version": version,
            "start": start,
            "end": end,
        },
    )


def _withdraw(client: TestClient, analysis_id: str, relationship_id: str, version: int) -> Any:
    return client.post(
        _url(analysis_id),
        json={
            "transition": "withdraw",
            "kind": "start_end_date",
            "relationship_id": relationship_id,
            "expected_version": version,
        },
    )


def _count_rows(client: TestClient) -> int:
    with client.app.state.analysis_engine.connect() as connection:  # type: ignore[attr-defined]
        return int(
            connection.execute(
                text("SELECT COUNT(*) FROM confirmed_relationship_versions")
            ).scalar_one()
        )


def test_confirm_creates_version_one_and_never_claims_a_check(client: TestClient) -> None:
    analysis_id = _completed_analysis(client)
    start, end = _keys(client, analysis_id)[:2]

    response = _confirm(client, analysis_id, start, end)

    assert response.status_code == 201, response.text
    body = response.json()
    assert set(body) == {"relationship_id", "version", "state", "check_status", "recorded_at"}
    assert body["version"] == 1
    assert body["state"] == "active"
    assert body["check_status"] == "not_active"


def test_get_returns_projection_and_ordered_history(client: TestClient) -> None:
    analysis_id = _completed_analysis(client)
    keys = _keys(client, analysis_id)
    created = _confirm(client, analysis_id, keys[0], keys[1]).json()
    replaced = _replace(client, analysis_id, created["relationship_id"], 1, keys[1], keys[2])
    assert replaced.status_code == 200
    assert replaced.json()["version"] == 2

    body = client.get(_url(analysis_id)).json()

    assert len(body["relationships"]) == 1
    relationship = body["relationships"][0]
    assert relationship["relationship_id"] == created["relationship_id"]
    assert relationship["state"] == "active"
    assert relationship["check_status"] == "not_active"
    assert relationship["current"]["version"] == 2
    assert relationship["current"]["start"]["internal_key"] == keys[1]
    assert [item["version"] for item in relationship["history"]] == [1, 2]
    assert [item["transition"] for item in relationship["history"]] == ["confirm", "replace"]
    assert relationship["history"][0]["source"] == "direct"
    # Provenance is server-set only: no identity, client or free-text field.
    assert set(relationship["current"]) == {
        "relationship_id",
        "version",
        "kind",
        "transition",
        "state",
        "start",
        "end",
        "source",
        "recorded_at",
    }


def test_withdraw_is_a_new_version_and_is_terminal(client: TestClient) -> None:
    analysis_id = _completed_analysis(client)
    keys = _keys(client, analysis_id)
    created = _confirm(client, analysis_id, keys[0], keys[1]).json()

    withdrawn = _withdraw(client, analysis_id, created["relationship_id"], 1)

    assert withdrawn.status_code == 200
    assert withdrawn.json()["version"] == 2
    assert withdrawn.json()["state"] == "withdrawn"
    listing = client.get(_url(analysis_id)).json()["relationships"][0]
    assert listing["state"] == "withdrawn"
    assert listing["history"][1]["start"] == listing["history"][0]["start"]
    again = _replace(client, analysis_id, created["relationship_id"], 2, keys[0], keys[1])
    assert again.status_code == 409
    assert again.json()["error"]["code"] == "RELATIONSHIP_WITHDRAWN"
    # A later confirmation of the same columns is a new relationship.
    fresh = _confirm(client, analysis_id, keys[0], keys[1]).json()
    assert fresh["relationship_id"] != created["relationship_id"]
    assert fresh["version"] == 1


def test_a_stale_version_is_rejected_and_nothing_is_stored(client: TestClient) -> None:
    analysis_id = _completed_analysis(client)
    keys = _keys(client, analysis_id)
    created = _confirm(client, analysis_id, keys[0], keys[1]).json()
    assert (
        _replace(client, analysis_id, created["relationship_id"], 1, keys[1], keys[2]).status_code
        == 200
    )
    rows_before = _count_rows(client)

    stale = _replace(client, analysis_id, created["relationship_id"], 1, keys[2], keys[3])

    assert stale.status_code == 409
    error = stale.json()["error"]
    assert error["code"] == "RELATIONSHIP_VERSION_CONFLICT"
    assert error["details"]["current_version"] == 2
    assert _count_rows(client) == rows_before


def test_unknown_relationship_and_unknown_column_are_refused_without_echo(
    client: TestClient,
) -> None:
    analysis_id = _completed_analysis(client)
    keys = _keys(client, analysis_id)
    secret = "SECRET-SUBMITTED-VALUE-123"

    missing = _replace(client, analysis_id, secret, 1, keys[0], keys[1])
    unknown = _confirm(client, analysis_id, keys[0], secret)

    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "RELATIONSHIP_NOT_FOUND"
    assert unknown.status_code == 422
    assert unknown.json()["error"]["code"] == "COLUMN_REFERENCE_NOT_IN_ANALYSIS"
    assert secret not in missing.text
    assert secret not in unknown.text
    assert _count_rows(client) == 0


def test_malformed_requests_are_rejected_with_stable_codes(client: TestClient) -> None:
    analysis_id = _completed_analysis(client)
    keys = _keys(client, analysis_id)
    created = _confirm(client, analysis_id, keys[0], keys[1]).json()
    base = {"kind": "start_end_date"}

    cases: list[tuple[dict[str, Any], str]] = [
        # Shape errors the service judges.
        (
            {
                **base,
                "transition": "confirm",
                "relationship_id": "x",
                "expected_version": 1,
                "start": keys[0],
                "end": keys[1],
            },
            "INVALID_RELATIONSHIP_TRANSITION",
        ),
        ({**base, "transition": "confirm", "start": keys[0]}, "INVALID_RELATIONSHIP_TRANSITION"),
        (
            {
                **base,
                "transition": "withdraw",
                "relationship_id": created["relationship_id"],
                "expected_version": 1,
                "start": keys[0],
                "end": keys[1],
            },
            "INVALID_RELATIONSHIP_TRANSITION",
        ),
        (
            {
                **base,
                "transition": "replace",
                "relationship_id": created["relationship_id"],
                "start": keys[0],
                "end": keys[1],
            },
            "INVALID_RELATIONSHIP_TRANSITION",
        ),
        # Strict-schema errors.
        (
            {**base, "transition": "confirm", "start": keys[0], "end": keys[1], "note": "x"},
            "INVALID_REQUEST",
        ),
        (
            {"kind": "other_kind", "transition": "confirm", "start": keys[0], "end": keys[1]},
            "INVALID_REQUEST",
        ),
        ({**base, "transition": "delete"}, "INVALID_REQUEST"),
        ({**base, "transition": "confirm", "start": "k" * 257, "end": keys[1]}, "INVALID_REQUEST"),
        (
            {
                **base,
                "transition": "confirm",
                "start": keys[0],
                "end": keys[1],
                "source": "someone",
            },
            "INVALID_REQUEST",
        ),
    ]
    for payload, code in cases:
        response = client.post(_url(analysis_id), json=payload)
        assert response.status_code == 422, (payload, response.text)
        assert response.json()["error"]["code"] == code, payload

    assert _count_rows(client) == 1


def test_same_column_on_both_sides_is_stored_not_rejected(client: TestClient) -> None:
    analysis_id = _completed_analysis(client)
    key = _keys(client, analysis_id)[0]

    response = _confirm(client, analysis_id, key, key)

    assert response.status_code == 201


def test_unknown_and_unfinished_analyses_are_refused(client: TestClient) -> None:
    unknown = client.get(_url("does-not-exist"))
    assert unknown.status_code == 404
    assert unknown.json()["error"]["code"] == "ANALYSIS_NOT_FOUND"

    queued = create_analysis(client.app.state.analysis_store)  # type: ignore[attr-defined]
    refused = _confirm(client, queued.analysis_id, "a", "b")
    assert refused.status_code == 409
    assert refused.json()["error"]["code"] == "INVALID_ANALYSIS_STATE"
    assert client.get(_url(queued.analysis_id)).json() == {"relationships": []}


def test_active_relationship_limit_counts_only_active_relationships(client: TestClient) -> None:
    analysis_id = _completed_analysis(client)
    keys = _keys(client, analysis_id)
    created = [
        _confirm(client, analysis_id, keys[0], keys[1]).json()["relationship_id"]
        for _ in range(MAX_ACTIVE_RELATIONSHIPS)
    ]

    over = _confirm(client, analysis_id, keys[0], keys[1])
    assert over.status_code == 409
    assert over.json()["error"]["code"] == "ACTIVE_RELATIONSHIP_LIMIT_REACHED"

    # A withdrawn relationship no longer counts, so a new one fits again.
    assert _withdraw(client, analysis_id, created[0], 1).status_code == 200
    assert _confirm(client, analysis_id, keys[0], keys[1]).status_code == 201


def test_version_limit_blocks_replace_but_never_withdrawal(client: TestClient) -> None:
    analysis_id = _completed_analysis(client)
    keys = _keys(client, analysis_id)
    created = _confirm(client, analysis_id, keys[0], keys[1]).json()
    relationship_id = created["relationship_id"]
    for version in range(1, MAX_VERSIONS_PER_RELATIONSHIP):
        assert (
            _replace(client, analysis_id, relationship_id, version, keys[0], keys[1]).status_code
            == 200
        )

    blocked = _replace(
        client, analysis_id, relationship_id, MAX_VERSIONS_PER_RELATIONSHIP, keys[0], keys[1]
    )
    assert blocked.status_code == 409
    assert blocked.json()["error"]["code"] == "RELATIONSHIP_VERSION_LIMIT_REACHED"

    withdrawn = _withdraw(client, analysis_id, relationship_id, MAX_VERSIONS_PER_RELATIONSHIP)
    assert withdrawn.status_code == 200
    assert withdrawn.json()["version"] == MAX_VERSIONS_PER_RELATIONSHIP + 1
    history = client.get(_url(analysis_id)).json()["relationships"][0]["history"]
    assert len(history) == MAX_VERSIONS_PER_RELATIONSHIP + 1


def test_deleting_the_analysis_removes_every_relationship_row(client: TestClient) -> None:
    kept = _completed_analysis(client)
    doomed = _completed_analysis(client)
    for analysis_id in (kept, doomed):
        keys = _keys(client, analysis_id)
        created = _confirm(client, analysis_id, keys[0], keys[1]).json()
        assert (
            _replace(
                client, analysis_id, created["relationship_id"], 1, keys[1], keys[2]
            ).status_code
            == 200
        )
    assert _count_rows(client) == 4

    assert client.delete(f"/api/v1/analyses/{doomed}").status_code == 204

    assert _count_rows(client) == 2
    assert client.get(_url(doomed)).status_code == 404
    assert len(client.get(_url(kept)).json()["relationships"][0]["history"]) == 2
