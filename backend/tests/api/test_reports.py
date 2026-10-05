"""HTTP proof for the four report routes (`EXP-01` slice 3) against the
real FastAPI application and a real demo analysis."""

from __future__ import annotations

import hashlib
import time
from dataclasses import replace
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from trusttable_backend.analysis import AnalysisState
from trusttable_backend.main import create_app

_TERMINAL = {"completed", "failed", "cancelled"}
_NOT_RECORDED = "Per-request AI enrichment is not recorded for this analysis."


def _wait(client: TestClient, analysis_id: str) -> str:
    deadline = time.monotonic() + 15.0
    while time.monotonic() < deadline:
        state: str = client.get(f"/api/v1/analyses/{analysis_id}/status").json()["state"]
        if state in _TERMINAL:
            return state
        time.sleep(0.01)
    raise AssertionError("analysis did not finish")


def _completed_analysis(client: TestClient) -> str:
    created = client.post("/api/v1/demo/sales")
    assert created.status_code == 202
    analysis_id: str = created.json()["analysis"]["analysis_id"]
    assert _wait(client, analysis_id) == "completed"
    return analysis_id


def _create(client: TestClient, analysis_id: str, **options: bool) -> dict[str, object]:
    response = client.post(f"/api/v1/analyses/{analysis_id}/reports", json={"options": options})
    assert response.status_code == 201, response.text
    body: dict[str, object] = response.json()
    return body


def _download(client: TestClient, analysis_id: str, report_id: object) -> bytes:
    response = client.get(f"/api/v1/analyses/{analysis_id}/reports/{report_id}/download")
    assert response.status_code == 200
    content: bytes = response.content
    return content


def test_create_returns_metadata_and_download_matches_its_digest(client: TestClient) -> None:
    analysis_id = _completed_analysis(client)

    body = _create(client, analysis_id)

    assert set(body) == {
        "report_id",
        "analysis_id",
        "generated_at",
        "options",
        "schema_version",
        "content_sha256",
    }
    assert body["analysis_id"] == analysis_id
    assert body["options"] == {
        "include_dismissed": False,
        "include_technical_appendix": False,
        "include_bounded_examples": False,
    }
    response = client.get(f"/api/v1/analyses/{analysis_id}/reports/{body['report_id']}/download")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    assert "attachment" in response.headers["content-disposition"]
    assert hashlib.sha256(response.content).hexdigest() == body["content_sha256"]


def test_create_without_a_body_uses_default_options(client: TestClient) -> None:
    analysis_id = _completed_analysis(client)

    response = client.post(f"/api/v1/analyses/{analysis_id}/reports")

    assert response.status_code == 201
    assert response.json()["options"]["include_bounded_examples"] is False


def test_unknown_option_is_rejected(client: TestClient) -> None:
    analysis_id = _completed_analysis(client)

    response = client.post(
        f"/api/v1/analyses/{analysis_id}/reports", json={"options": {"include_everything": True}}
    )

    assert response.status_code == 422


def test_unknown_analysis_is_404_on_every_route(client: TestClient) -> None:
    for method, path in (
        ("post", "/api/v1/analyses/nope/reports"),
        ("get", "/api/v1/analyses/nope/reports"),
        ("get", "/api/v1/analyses/nope/reports/x"),
        ("get", "/api/v1/analyses/nope/reports/x/download"),
    ):
        response = getattr(client, method)(path)
        assert response.status_code == 404, path
        assert response.json()["error"]["code"] == "ANALYSIS_NOT_FOUND"


def test_non_completed_analysis_cannot_be_reported(client: TestClient) -> None:
    analysis_id = _completed_analysis(client)
    store = client.app.state.analysis_store  # type: ignore[attr-defined]
    store.replace(
        replace(
            store.get(analysis_id),
            state=AnalysisState.CANCELLED,
            dataset_profile=None,
            trust_assessment=None,
            findings=(),
            evidence=(),
            observations=(),
            priority_scores=(),
            context=None,
            guided_questions=(),
            rules=(),
            context_version=0,
            completed_at=None,
            cancelled_at=datetime.now(UTC),
        )
    )

    response = client.post(f"/api/v1/analyses/{analysis_id}/reports")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_ANALYSIS_STATE"
    assert client.get(f"/api/v1/analyses/{analysis_id}/reports").json() == {"reports": []}


def test_unknown_report_is_404(client: TestClient) -> None:
    analysis_id = _completed_analysis(client)

    for suffix in ("", "/download"):
        response = client.get(f"/api/v1/analyses/{analysis_id}/reports/missing{suffix}")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "REPORT_NOT_FOUND"


def test_a_report_of_another_analysis_is_not_found(client: TestClient) -> None:
    first = _completed_analysis(client)
    second = _completed_analysis(client)
    report = _create(client, first)

    for suffix in ("", "/download"):
        response = client.get(f"/api/v1/analyses/{second}/reports/{report['report_id']}{suffix}")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "REPORT_NOT_FOUND"
    assert client.get(f"/api/v1/analyses/{second}/reports").json() == {"reports": []}


def test_list_is_in_creation_order_and_metadata_matches(client: TestClient) -> None:
    analysis_id = _completed_analysis(client)
    reports = [
        _create(client, analysis_id),
        _create(client, analysis_id, include_technical_appendix=True),
        _create(client, analysis_id, include_bounded_examples=True),
    ]

    listed = client.get(f"/api/v1/analyses/{analysis_id}/reports").json()["reports"]

    assert [item["report_id"] for item in listed] == [item["report_id"] for item in reports]
    assert len({item["report_id"] for item in listed}) == 3
    for item in reports:
        fetched = client.get(f"/api/v1/analyses/{analysis_id}/reports/{item['report_id']}")
        assert fetched.status_code == 200
        assert fetched.json() == item


def test_options_change_the_stored_content(client: TestClient) -> None:
    analysis_id = _completed_analysis(client)
    plain = _create(client, analysis_id)
    appendix = _create(client, analysis_id, include_technical_appendix=True)
    examples = _create(client, analysis_id, include_bounded_examples=True)

    texts = {
        name: _download(client, analysis_id, item["report_id"])
        for name, item in (("plain", plain), ("appendix", appendix), ("examples", examples))
    }

    assert len(set(texts.values())) == 3
    assert len(texts["appendix"]) > len(texts["plain"])
    assert plain["content_sha256"] != appendix["content_sha256"]


def test_report_for_an_analysis_without_a_record_states_ai_enrichment_is_not_recorded(
    client: TestClient,
) -> None:
    analysis_id = _completed_analysis(client)
    store = client.app.state.analysis_store  # type: ignore[attr-defined]
    store.update_ai_enrichment(analysis_id, lambda _: None)
    report = _create(client, analysis_id)

    text = _download(client, analysis_id, report["report_id"]).decode("utf-8")

    assert _NOT_RECORDED in text
    lowered = text.lower()
    assert "no data was sent" not in lowered
    assert "nothing was sent" not in lowered


def test_default_report_omits_detector_observation_text(client: TestClient) -> None:
    analysis_id = _completed_analysis(client)
    analysis = client.app.state.analysis_store.get(analysis_id)  # type: ignore[attr-defined]
    plain = _download(client, analysis_id, _create(client, analysis_id)["report_id"]).decode()
    examples = _download(
        client,
        analysis_id,
        _create(client, analysis_id, include_bounded_examples=True)["report_id"],
    ).decode()
    observation = next(
        f.calculated_observation for f in analysis.findings if f.calculated_observation
    )

    assert observation.split()[0] in examples
    assert observation not in plain


def test_snapshot_is_immutable_when_reviews_change_afterwards(client: TestClient) -> None:
    analysis_id = _completed_analysis(client)
    first = _create(client, analysis_id)
    before = _download(client, analysis_id, first["report_id"])

    dismissed = client.put(
        f"/api/v1/analyses/{analysis_id}/findings/0/review",
        json={"state": "dismissed", "dismissal_reason": "not relevant"},
    )
    assert dismissed.status_code == 200
    second = _create(client, analysis_id, include_dismissed=True)

    after = _download(client, analysis_id, first["report_id"])
    assert after == before
    assert hashlib.sha256(after).hexdigest() == first["content_sha256"]
    assert (
        client.get(f"/api/v1/analyses/{analysis_id}/reports/{first['report_id']}").json() == first
    )
    current = _download(client, analysis_id, second["report_id"])
    assert current != before
    assert b"not relevant" in current


def test_snapshot_is_immutable_when_rules_change_afterwards(client: TestClient) -> None:
    analysis_id = _completed_analysis(client)
    first = _create(client, analysis_id)
    before = _download(client, analysis_id, first["report_id"])

    created = client.post(
        f"/api/v1/analyses/{analysis_id}/rules",
        json={
            "name": "quantity present",
            "description": "quantity is never blank",
            "severity": "medium",
            "column_names": ["quantity"],
            "rule_type": "not_null",
        },
    )
    assert created.status_code == 201
    second = _create(client, analysis_id)

    assert _download(client, analysis_id, first["report_id"]) == before
    assert _download(client, analysis_id, second["report_id"]) != before


def test_reports_survive_restart_byte_identical() -> None:
    with TestClient(create_app()) as first_client:
        analysis_id = _completed_analysis(first_client)
        report = _create(first_client, analysis_id, include_technical_appendix=True)
        stored = _download(first_client, analysis_id, report["report_id"])

    with TestClient(create_app()) as second_client:
        assert _download(second_client, analysis_id, report["report_id"]) == stored
        listed = second_client.get(f"/api/v1/analyses/{analysis_id}/reports").json()["reports"]
        assert listed == [report]
