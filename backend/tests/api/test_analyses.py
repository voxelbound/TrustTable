"""Tests for the analysis HTTP routes (`API-01`).

Exercises the six documented behaviors
(`docs/implementation-backlog.md#API-01`): create analysis / load demo
(`POST /demo/sales`), status, profile, findings, and cancel — against the
real app via the shared `client` fixture (`conftest.py`), each test
getting a fresh in-memory `AnalysisStore` (one per `create_app()` call).

`POST /demo/sales` runs the pipeline synchronously to completion within
the same request — there is no background worker yet (`JOB-01`) — so the
public HTTP contract alone never produces an observable `queued`
analysis. The not-yet-`completed` profile/findings/cancel paths are
exercised with **white-box** setup: reaching into
`client.app.state.analysis_store` and calling
`trusttable_backend.analysis.create_analysis` directly (without
`run_analysis`) to construct a real `queued` analysis, then driving it
through the HTTP layer — clearly distinguished from the black-box tests
above it in each test's own docstring/naming.
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from trusttable_backend.analysis import AnalysisStore, create_analysis
from trusttable_backend.request_context import REQUEST_ID_HEADER

_KNOWN_TRUST_LABELS = {
    "high_confidence",
    "usable_with_caution",
    "material_quality_concerns",
    "not_reliable_for_decision_making",
}


def _create_demo_analysis(client: TestClient) -> dict[str, Any]:
    """Black-box: `POST /demo/sales`, returning the parsed response body."""
    response = client.post("/api/v1/demo/sales")
    assert response.status_code == 202
    return response.json()  # type: ignore[no-any-return]


def _create_queued_analysis_id(client: TestClient) -> str:
    """White-box: construct a real `queued` (not yet run) analysis
    directly against the app's store, bypassing the HTTP layer entirely
    — the only way to reach the not-yet-`completed` code paths, since
    `POST /demo/sales` always runs synchronously to completion.
    """
    store: AnalysisStore = client.app.state.analysis_store  # type: ignore[attr-defined]
    analysis = create_analysis(store)
    return analysis.analysis_id


# --- POST /demo/sales -------------------------------------------------


def test_post_demo_sales_returns_202_with_completed_analysis(client: TestClient) -> None:
    body = _create_demo_analysis(client)

    assert body["analysis"]["state"] == "completed"
    assert body["analysis"]["completed_at"] is not None
    assert body["analysis"]["failure"] is None


def test_post_demo_sales_response_has_exact_top_level_fields(client: TestClient) -> None:
    body = _create_demo_analysis(client)

    assert set(body.keys()) == {"analysis", "status_url"}
    assert body["status_url"] == f"/api/v1/analyses/{body['analysis']['analysis_id']}/status"


def test_post_demo_sales_analysis_has_exact_fields(client: TestClient) -> None:
    body = _create_demo_analysis(client)

    assert set(body["analysis"].keys()) == {
        "analysis_id",
        "state",
        "dataset",
        "security_exposure",
        "trust_assessment",
        "finding_count",
        "failure",
        "created_at",
        "started_at",
        "completed_at",
        "failed_at",
        "cancelled_at",
    }


def test_post_demo_sales_dataset_summary_fields(client: TestClient) -> None:
    body = _create_demo_analysis(client)
    dataset = body["analysis"]["dataset"]

    assert dataset["source_type"] == "bundled_demo"
    assert dataset["format"] == "csv"
    assert dataset["original_filename"] == "sales_demo.csv"
    assert dataset["byte_size"] > 0
    assert isinstance(dataset["content_hash"], str) and dataset["content_hash"]


def test_post_demo_sales_security_exposure_is_disabled(client: TestClient) -> None:
    body = _create_demo_analysis(client)
    exposure = body["analysis"]["security_exposure"]

    assert exposure == {"model_provider_enabled": False, "sample_transmission_enabled": False}


def test_post_demo_sales_produces_findings_and_trust_assessment(client: TestClient) -> None:
    body = _create_demo_analysis(client)
    analysis = body["analysis"]

    # `demo-data/sales_demo.csv` has many injected issues (DET-02/DET-SEC-01
    # precedent, e.g. WP-014..WP-021's own real-file finding counts).
    assert analysis["finding_count"] > 0
    trust_assessment = analysis["trust_assessment"]
    assert trust_assessment is not None
    assert trust_assessment["label"] in _KNOWN_TRUST_LABELS
    assert trust_assessment["finding_count"] == analysis["finding_count"]
    assert 0.0 <= trust_assessment["score"] <= 100.0


def test_two_demo_sales_calls_produce_distinct_analysis_ids(client: TestClient) -> None:
    first = _create_demo_analysis(client)
    second = _create_demo_analysis(client)

    assert first["analysis"]["analysis_id"] != second["analysis"]["analysis_id"]


# --- GET /analyses/{id} -------------------------------------------------


def test_get_analysis_returns_same_resource_as_created(client: TestClient) -> None:
    created = _create_demo_analysis(client)["analysis"]

    response = client.get(f"/api/v1/analyses/{created['analysis_id']}")

    assert response.status_code == 200
    assert response.json() == created


def test_get_analysis_unknown_id_returns_structured_404(client: TestClient) -> None:
    response = client.get("/api/v1/analyses/does-not-exist")

    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "ANALYSIS_NOT_FOUND"
    assert body["error"]["details"] == {"analysis_id": "does-not-exist"}
    assert response.headers[REQUEST_ID_HEADER]


# --- GET /analyses/{id}/status ------------------------------------------


def test_get_analysis_status_for_completed_analysis(client: TestClient) -> None:
    created = _create_demo_analysis(client)["analysis"]

    response = client.get(f"/api/v1/analyses/{created['analysis_id']}/status")

    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {
        "analysis_id",
        "state",
        "message",
        "cancellable",
        "poll_interval_ms",
    }
    assert body["state"] == "completed"
    assert body["cancellable"] is False
    assert body["message"] == "Analysis completed."
    assert body["poll_interval_ms"] > 0


def test_get_analysis_status_unknown_id_returns_structured_404(client: TestClient) -> None:
    response = client.get("/api/v1/analyses/does-not-exist/status")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ANALYSIS_NOT_FOUND"


def test_get_analysis_status_for_queued_analysis_is_cancellable(client: TestClient) -> None:
    """White-box: a real `queued`, not-yet-run analysis."""
    analysis_id = _create_queued_analysis_id(client)

    response = client.get(f"/api/v1/analyses/{analysis_id}/status")

    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "queued"
    assert body["cancellable"] is True
    assert body["message"] == "Analysis is queued."


# --- GET /analyses/{id}/profile ------------------------------------------


def test_get_analysis_profile_after_completion(client: TestClient) -> None:
    created = _create_demo_analysis(client)["analysis"]

    response = client.get(f"/api/v1/analyses/{created['analysis_id']}/profile")

    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {
        "schema_version",
        "dataset_metrics",
        "column_profiles",
        "sampling",
        "warnings",
        "timing",
    }
    assert body["schema_version"]
    # `demo-data/sales_demo.csv` has 15 columns (DEMO-01/ING-02 precedent).
    assert len(body["column_profiles"]) == 15
    assert body["sampling"]["scope"] == "full"
    assert body["timing"]["duration_ms"] >= 0


def test_get_analysis_profile_column_profile_shape(client: TestClient) -> None:
    created = _create_demo_analysis(client)["analysis"]

    response = client.get(f"/api/v1/analyses/{created['analysis_id']}/profile")
    column = response.json()["column_profiles"][0]

    assert set(column.keys()) == {
        "column",
        "inferred_type",
        "null_count",
        "distinct_count",
        "metrics",
        "warnings",
    }
    assert set(column["column"].keys()) == {"original_name", "internal_key", "ordinal"}


def test_get_analysis_profile_unknown_id_returns_structured_404(client: TestClient) -> None:
    response = client.get("/api/v1/analyses/does-not-exist/profile")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ANALYSIS_NOT_FOUND"


def test_get_analysis_profile_before_completion_returns_409(client: TestClient) -> None:
    """White-box: a real `queued`, not-yet-run analysis has no profile yet."""
    analysis_id = _create_queued_analysis_id(client)

    response = client.get(f"/api/v1/analyses/{analysis_id}/profile")

    assert response.status_code == 409
    body = response.json()
    assert body["error"]["code"] == "INVALID_ANALYSIS_STATE"
    assert body["error"]["details"] == {"analysis_id": analysis_id, "state": "queued"}


# --- GET /analyses/{id}/findings -----------------------------------------


def test_get_analysis_findings_after_completion(client: TestClient) -> None:
    created = _create_demo_analysis(client)["analysis"]

    response = client.get(f"/api/v1/analyses/{created['analysis_id']}/findings")

    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {"items", "total_items"}
    assert body["total_items"] == created["finding_count"]
    assert len(body["items"]) == created["finding_count"]


def test_get_analysis_findings_item_shape(client: TestClient) -> None:
    created = _create_demo_analysis(client)["analysis"]

    response = client.get(f"/api/v1/analyses/{created['analysis_id']}/findings")
    item = response.json()["items"][0]

    assert set(item.keys()) == {
        "detector_id",
        "detector_version",
        "category",
        "severity",
        "confidence",
        "priority_score",
        "calculated_observation",
        "affected_columns",
        "affected_row_count",
        "evidence_count",
    }
    assert "." in item["detector_id"]
    assert 0.0 <= item["confidence"] <= 1.0
    assert 0.0 <= item["priority_score"] <= 100.0
    # Every FindingCandidate has at least one evidence object
    # (docs/domain-model.md #12, DET-01's own invariant).
    assert item["evidence_count"] >= 1


def test_get_analysis_findings_unknown_id_returns_structured_404(client: TestClient) -> None:
    response = client.get("/api/v1/analyses/does-not-exist/findings")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ANALYSIS_NOT_FOUND"


def test_get_analysis_findings_empty_before_completion(client: TestClient) -> None:
    """White-box: matches `analysis.service.get_findings`'s documented
    empty-tuple-for-not-completed behavior, not an error.
    """
    analysis_id = _create_queued_analysis_id(client)

    response = client.get(f"/api/v1/analyses/{analysis_id}/findings")

    assert response.status_code == 200
    assert response.json() == {"items": [], "total_items": 0}


# --- POST /analyses/{id}/cancel ------------------------------------------


def test_cancel_queued_analysis_transitions_to_cancelled(client: TestClient) -> None:
    """White-box: only a real `queued` analysis is ever cancellable."""
    analysis_id = _create_queued_analysis_id(client)

    response = client.post(f"/api/v1/analyses/{analysis_id}/cancel")

    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "cancelled"
    assert body["cancelled_at"] is not None


def test_cancel_completed_analysis_returns_unchanged_state(client: TestClient) -> None:
    created = _create_demo_analysis(client)["analysis"]

    response = client.post(f"/api/v1/analyses/{created['analysis_id']}/cancel")

    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "completed"
    assert body["cancelled_at"] is None
    assert body == created


def test_cancel_unknown_id_returns_structured_404(client: TestClient) -> None:
    response = client.post("/api/v1/analyses/does-not-exist/cancel")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ANALYSIS_NOT_FOUND"
