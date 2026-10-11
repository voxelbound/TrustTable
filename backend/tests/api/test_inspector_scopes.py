"""API tests for the inspector reads added by `UX-06` part b (D-074):

- `GET /analyses/{id}/observations/{observation_id}/row-context`
- `GET /analyses/{id}/findings/{finding_id}/column-context`

Both are read-only, bounded, concurrency-gated and `no-store`, only ever centre
a window on a row the server offers, and change nothing else the API returns.
"""

from __future__ import annotations

import json
from typing import Any

from fastapi.testclient import TestClient

import trusttable_backend.api.v1.analyses as analyses_module
from tests.api.test_analyses import _create_demo_analysis, _wait_for_terminal
from tests.detectors.test_det03_package2 import sample_csv

NOTE_OBSERVATION = "completeness.concentrated_missingness.observation.note"
NOTE_EXAMPLE_ROWS = list(range(7, 22))


def _upload_sample(client: TestClient) -> str:
    created = client.post("/api/v1/analyses", files={"file": ("x.csv", sample_csv(), "text/csv")})
    assert created.status_code == 202
    analysis_id: str = created.json()["analysis"]["analysis_id"]
    _wait_for_terminal(client, analysis_id)
    return analysis_id


def _column_wide_note_finding(client: TestClient, analysis_id: str) -> str:
    """The sample file's `note` column has a finding that names no rows and an
    observation about the same column with example rows."""
    items = client.get(f"/api/v1/analyses/{analysis_id}/findings").json()["items"]
    for item in items:
        if item["affected_row_count"] == 0:
            detail = client.get(
                f"/api/v1/analyses/{analysis_id}/findings/{item['finding_id']}"
            ).json()
            if [c["internal_key"] for c in detail["affected_columns"]] == ["note"]:
                return str(item["finding_id"])
    raise AssertionError("expected a column-wide finding about the note column")


def _observation_url(analysis_id: str, observation_id: str = NOTE_OBSERVATION) -> str:
    return f"/api/v1/analyses/{analysis_id}/observations/{observation_id}/row-context"


# --- observation windows -----------------------------------------------------------


def test_observation_row_context_shape_and_marking(client: TestClient) -> None:
    analysis_id = _upload_sample(client)

    response = client.get(_observation_url(analysis_id), params={"anchor_row": 10})

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "scope_kind",
        "anchor_source",
        "anchor_rows",
        "columns",
        "requested_before",
        "requested_after",
        "actual_before",
        "actual_after",
        "truncated_at_start",
        "truncated_at_end",
        "max_window",
        "rows",
        "size_limited",
    }
    assert body["scope_kind"] == "observation"
    assert body["anchor_source"] == "observation_example"
    assert body["anchor_rows"] == NOTE_EXAMPLE_ROWS
    anchors = [row for row in body["rows"] if row["is_anchor"]]
    assert [row["row_number"] for row in anchors] == [10]
    for row in body["rows"]:
        assert set(row) == {"row_number", "is_anchor", "is_marked", "values"}
        assert row["is_marked"] == (row["row_number"] in NOTE_EXAMPLE_ROWS)
        assert len(row["values"]) == len(body["columns"])


def test_observation_row_context_is_not_storable_by_caches(client: TestClient) -> None:
    analysis_id = _upload_sample(client)

    response = client.get(_observation_url(analysis_id), params={"anchor_row": 7})

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"


def test_observation_row_context_refuses_every_row_that_is_not_an_example(
    client: TestClient,
) -> None:
    analysis_id = _upload_sample(client)

    for row in (0, 1, 6, 22, 29, 500):
        response = client.get(_observation_url(analysis_id), params={"anchor_row": row})
        assert response.status_code == 404, row
        assert response.json()["error"]["code"] == "ROW_NOT_IN_OBSERVATION"


def test_observation_row_context_refuses_an_unknown_observation_and_analysis(
    client: TestClient,
) -> None:
    analysis_id = _upload_sample(client)

    unknown = client.get(
        _observation_url(analysis_id, "no.such.observation"), params={"anchor_row": 7}
    )
    assert unknown.status_code == 404
    assert unknown.json()["error"]["code"] == "OBSERVATION_NOT_FOUND"

    missing = client.get(
        "/api/v1/analyses/does-not-exist/observations/x/row-context", params={"anchor_row": 0}
    )
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "ANALYSIS_NOT_FOUND"


def test_observation_row_context_validates_its_query(client: TestClient) -> None:
    analysis_id = _upload_sample(client)

    assert client.get(_observation_url(analysis_id)).status_code == 422
    assert (
        client.get(
            _observation_url(analysis_id), params={"anchor_row": 7, "before": -1}
        ).status_code
        == 422
    )


def test_observation_row_context_clamps_the_window_to_the_server_limit(client: TestClient) -> None:
    analysis_id = _upload_sample(client)

    body = client.get(
        _observation_url(analysis_id), params={"anchor_row": 14, "before": 1000, "after": 1000}
    ).json()

    assert body["requested_before"] == 1000
    assert body["max_window"] == 25
    assert body["actual_before"] <= 25
    assert body["actual_after"] <= 25


def test_observation_row_context_shares_the_concurrency_bound(client: TestClient) -> None:
    analysis_id = _upload_sample(client)
    url = _observation_url(analysis_id)
    params = {"anchor_row": 7}
    held = 0
    try:
        while analyses_module._INSPECTOR_READ_GATE.acquire(blocking=False):
            held += 1
        assert held == analyses_module._MAX_CONCURRENT_INSPECTOR_READS
        busy = client.get(url, params=params)
    finally:
        for _ in range(held):
            analyses_module._INSPECTOR_READ_GATE.release()

    assert busy.status_code == 429
    assert busy.json()["error"]["code"] == "INSPECTOR_BUSY"
    assert client.get(url, params=params).status_code == 200


def test_observation_row_context_releases_the_gate_after_a_refused_row(
    client: TestClient,
) -> None:
    analysis_id = _upload_sample(client)

    for _ in range(analyses_module._MAX_CONCURRENT_INSPECTOR_READS + 2):
        assert (
            client.get(_observation_url(analysis_id), params={"anchor_row": 0}).status_code == 404
        )

    assert analyses_module._INSPECTOR_READ_GATE.acquire(blocking=False)
    analyses_module._INSPECTOR_READ_GATE.release()


# --- column-wide finding windows -------------------------------------------------


def test_column_context_uses_the_example_rows_of_observations_about_the_same_column(
    client: TestClient,
) -> None:
    analysis_id = _upload_sample(client)
    finding_id = _column_wide_note_finding(client, analysis_id)
    url = f"/api/v1/analyses/{analysis_id}/findings/{finding_id}/column-context"

    default = client.get(url)
    chosen = client.get(url, params={"anchor_row": 12})

    assert default.status_code == 200
    body = default.json()
    assert body["scope_kind"] == "column_wide_finding"
    assert body["anchor_source"] == "observation_example"
    assert body["anchor_rows"] == NOTE_EXAMPLE_ROWS
    assert [r["row_number"] for r in body["rows"] if r["is_anchor"]] == [NOTE_EXAMPLE_ROWS[0]]
    assert default.headers["cache-control"] == "no-store"
    assert [r["row_number"] for r in chosen.json()["rows"] if r["is_anchor"]] == [12]


def test_column_context_refuses_a_row_the_server_did_not_offer(client: TestClient) -> None:
    analysis_id = _upload_sample(client)
    finding_id = _column_wide_note_finding(client, analysis_id)
    url = f"/api/v1/analyses/{analysis_id}/findings/{finding_id}/column-context"

    for row in (0, 6, 22, 500):
        response = client.get(url, params={"anchor_row": row})
        assert response.status_code == 404, row
        assert response.json()["error"]["code"] == "ROW_NOT_IN_SCOPE"


def test_column_context_without_an_anchor_is_the_start_of_the_file_and_marks_nothing(
    client: TestClient,
) -> None:
    created = _create_demo_analysis(client)["analysis"]
    analysis_id = created["analysis_id"]
    items = client.get(f"/api/v1/analyses/{analysis_id}/findings").json()["items"]
    column_wide = [item for item in items if item["affected_row_count"] == 0]
    assert column_wide
    observed_columns = {
        column["internal_key"]
        for observation in client.get(f"/api/v1/analyses/{analysis_id}/observations").json()[
            "items"
        ]
        for column in observation["affected_columns"]
    }
    found_start_of_file = False
    for item in column_wide:
        detail = client.get(f"/api/v1/analyses/{analysis_id}/findings/{item['finding_id']}").json()
        keys = {column["internal_key"] for column in detail["affected_columns"]}
        if keys & observed_columns:
            continue
        response = client.get(
            f"/api/v1/analyses/{analysis_id}/findings/{item['finding_id']}/column-context"
        )
        assert response.status_code == 200
        body = response.json()
        assert body["anchor_source"] == "start_of_file"
        assert body["anchor_rows"] == [0]
        assert [r["row_number"] for r in body["rows"] if r["is_anchor"]] == [0]
        assert not any(r["is_marked"] for r in body["rows"])
        found_start_of_file = True
        refused = client.get(
            f"/api/v1/analyses/{analysis_id}/findings/{item['finding_id']}/column-context",
            params={"anchor_row": 1},
        )
        assert refused.status_code == 404
        assert refused.json()["error"]["code"] == "ROW_NOT_IN_SCOPE"
    assert found_start_of_file


def test_column_context_is_not_available_for_a_finding_that_names_rows(client: TestClient) -> None:
    analysis_id = _upload_sample(client)
    items = client.get(f"/api/v1/analyses/{analysis_id}/findings").json()["items"]
    with_rows = next(item for item in items if item["affected_row_count"] > 0)

    response = client.get(
        f"/api/v1/analyses/{analysis_id}/findings/{with_rows['finding_id']}/column-context"
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "FINDING_HAS_AFFECTED_ROWS"


def test_column_context_refuses_an_unknown_finding_and_analysis(client: TestClient) -> None:
    analysis_id = _upload_sample(client)

    unknown = client.get(f"/api/v1/analyses/{analysis_id}/findings/999/column-context")
    assert unknown.status_code == 404
    assert unknown.json()["error"]["code"] == "FINDING_NOT_FOUND"
    missing = client.get("/api/v1/analyses/does-not-exist/findings/0/column-context")
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "ANALYSIS_NOT_FOUND"


def test_column_context_shares_the_concurrency_bound(client: TestClient) -> None:
    analysis_id = _upload_sample(client)
    finding_id = _column_wide_note_finding(client, analysis_id)
    url = f"/api/v1/analyses/{analysis_id}/findings/{finding_id}/column-context"
    held = 0
    try:
        while analyses_module._INSPECTOR_READ_GATE.acquire(blocking=False):
            held += 1
        busy = client.get(url)
    finally:
        for _ in range(held):
            analyses_module._INSPECTOR_READ_GATE.release()

    assert busy.status_code == 429
    assert busy.json()["error"]["code"] == "INSPECTOR_BUSY"
    assert client.get(url).status_code == 200


# --- the windows change nothing else the API returns --------------------------------


def _read_everything(client: TestClient, analysis_id: str) -> dict[str, Any]:
    base = f"/api/v1/analyses/{analysis_id}"
    findings = client.get(f"{base}/findings").json()
    snapshot: dict[str, Any] = {
        "resource": client.get(base).json(),
        "findings": findings,
        "observations": client.get(f"{base}/observations").json(),
        "profile": client.get(f"{base}/profile").json(),
    }
    for item in findings["items"]:
        finding_id = item["finding_id"]
        snapshot[f"detail:{finding_id}"] = client.get(f"{base}/findings/{finding_id}").json()
        snapshot[f"evidence:{finding_id}"] = client.get(
            f"{base}/findings/{finding_id}/evidence"
        ).json()
        snapshot[f"explanation:{finding_id}"] = client.get(
            f"{base}/findings/{finding_id}/explanation"
        ).json()
    return snapshot


def test_opening_the_new_windows_changes_nothing_else_the_api_returns(
    client: TestClient,
) -> None:
    analysis_id = _upload_sample(client)
    finding_id = _column_wide_note_finding(client, analysis_id)

    before = json.dumps(_read_everything(client, analysis_id), sort_keys=True)
    assert client.get(_observation_url(analysis_id), params={"anchor_row": 9}).status_code == 200
    assert (
        client.get(
            f"/api/v1/analyses/{analysis_id}/findings/{finding_id}/column-context",
            params={"anchor_row": 9},
        ).status_code
        == 200
    )
    after = json.dumps(_read_everything(client, analysis_id), sort_keys=True)

    assert after == before
