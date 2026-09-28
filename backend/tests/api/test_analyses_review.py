"""Decisive HTTP end-to-end proof for persisted finding review state
(`REV-01`, `WP-083`) against the real FastAPI application: `PUT
.../findings/{finding_id}/review` sets a finding's review state, an
optional note, and (only when dismissed) a dismissal reason, and it is
immediately reflected by `GET .../findings`/`GET .../findings/{finding_id}`.
"""

from __future__ import annotations

import time

from fastapi.testclient import TestClient

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


def _create_completed_analysis(client: TestClient) -> str:
    created = client.post("/api/v1/demo/sales")
    assert created.status_code == 202
    analysis_id: str = created.json()["analysis"]["analysis_id"]
    assert _wait_for_terminal_state(client, analysis_id) == "completed"
    return analysis_id


# ---------------------------------------------------------------------------
# Setting a review persists immediately and is reflected by GET
# ---------------------------------------------------------------------------


def test_put_review_confirmed_persists_and_is_reflected_by_get(client: TestClient) -> None:
    analysis_id = _create_completed_analysis(client)

    response = client.put(
        f"/api/v1/analyses/{analysis_id}/findings/0/review",
        json={"state": "confirmed", "note": "Verified against the source system."},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["finding_id"] == "0"
    assert body["review_state"] == "confirmed"
    assert body["note"] == "Verified against the source system."
    assert body["dismissal_reason"] is None
    assert body["reviewed_at"] is not None

    detail = client.get(f"/api/v1/analyses/{analysis_id}/findings/0").json()
    assert detail["review_state"] == "confirmed"
    assert detail["note"] == "Verified against the source system."

    list_item = client.get(f"/api/v1/analyses/{analysis_id}/findings").json()["items"][0]
    assert list_item["review_state"] == "confirmed"


def test_put_review_dismissed_requires_a_reason(client: TestClient) -> None:
    analysis_id = _create_completed_analysis(client)

    response = client.put(
        f"/api/v1/analyses/{analysis_id}/findings/0/review",
        json={"state": "dismissed"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "REVIEW_INVALID"
    detail = client.get(f"/api/v1/analyses/{analysis_id}/findings/0").json()
    assert detail["review_state"] == "unreviewed"


def test_put_review_dismissed_with_a_reason_persists(client: TestClient) -> None:
    analysis_id = _create_completed_analysis(client)

    response = client.put(
        f"/api/v1/analyses/{analysis_id}/findings/0/review",
        json={
            "state": "dismissed",
            "dismissal_reason": "Known-fixed value, confirmed with the source-system owner.",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["review_state"] == "dismissed"
    assert body["dismissal_reason"] == (
        "Known-fixed value, confirmed with the source-system owner."
    )


def test_put_review_rejects_a_dismissal_reason_for_a_non_dismissed_state(
    client: TestClient,
) -> None:
    analysis_id = _create_completed_analysis(client)

    response = client.put(
        f"/api/v1/analyses/{analysis_id}/findings/0/review",
        json={"state": "confirmed", "dismissal_reason": "should not be allowed"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "REVIEW_INVALID"


def test_put_review_rejects_an_unrecognized_state(client: TestClient) -> None:
    analysis_id = _create_completed_analysis(client)

    response = client.put(
        f"/api/v1/analyses/{analysis_id}/findings/0/review",
        json={"state": "not_a_real_state"},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "REVIEW_INVALID"


def test_put_review_unknown_finding_returns_404(client: TestClient) -> None:
    analysis_id = _create_completed_analysis(client)

    response = client.put(
        f"/api/v1/analyses/{analysis_id}/findings/999999/review",
        json={"state": "confirmed"},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "FINDING_NOT_FOUND"


def test_put_review_unknown_analysis_returns_404(client: TestClient) -> None:
    response = client.put(
        "/api/v1/analyses/unknown-id/findings/0/review",
        json={"state": "confirmed"},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ANALYSIS_NOT_FOUND"


def test_put_review_on_a_not_yet_completed_analysis_returns_409(client: TestClient) -> None:
    created = client.post("/api/v1/demo/sales")
    analysis_id = created.json()["analysis"]["analysis_id"]

    response = client.put(
        f"/api/v1/analyses/{analysis_id}/findings/0/review",
        json={"state": "confirmed"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_ANALYSIS_STATE"
    _wait_for_terminal_state(client, analysis_id)  # drain before the test ends


def test_put_review_twice_replaces_the_prior_record(client: TestClient) -> None:
    analysis_id = _create_completed_analysis(client)

    client.put(
        f"/api/v1/analyses/{analysis_id}/findings/0/review",
        json={"state": "needs_investigation", "note": "first pass"},
    )
    response = client.put(
        f"/api/v1/analyses/{analysis_id}/findings/0/review",
        json={"state": "confirmed"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["review_state"] == "confirmed"
    assert body["note"] is None

    detail = client.get(f"/api/v1/analyses/{analysis_id}/findings/0").json()
    assert detail["review_state"] == "confirmed"
    assert detail["note"] is None


def test_put_review_does_not_affect_other_findings(client: TestClient) -> None:
    analysis_id = _create_completed_analysis(client)
    findings = client.get(f"/api/v1/analyses/{analysis_id}/findings").json()["items"]
    assert len(findings) > 1

    client.put(
        f"/api/v1/analyses/{analysis_id}/findings/0/review",
        json={"state": "confirmed"},
    )

    other = client.get(f"/api/v1/analyses/{analysis_id}/findings/1").json()
    assert other["review_state"] == "unreviewed"
