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
        "finding_id",
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
    assert item["finding_id"] == "0"
    assert "." in item["detector_id"]
    assert 0.0 <= item["confidence"] <= 1.0
    assert 0.0 <= item["priority_score"] <= 100.0
    # Every FindingCandidate has at least one evidence object
    # (docs/domain-model.md #12, DET-01's own invariant).
    assert item["evidence_count"] >= 1


def test_get_analysis_findings_item_finding_ids_are_distinct_and_ordered(
    client: TestClient,
) -> None:
    """`WP-027`: every list item's `finding_id` is the stringified index
    of its position in the returned list, matching
    `analysis.service.get_finding`'s own addressing scheme exactly.
    """
    created = _create_demo_analysis(client)["analysis"]

    response = client.get(f"/api/v1/analyses/{created['analysis_id']}/findings")
    items = response.json()["items"]

    assert [item["finding_id"] for item in items] == [str(index) for index in range(len(items))]


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


# --- GET /analyses/{id}/findings/{finding_id} (`WP-027`) -----------------


def test_get_analysis_finding_detail_shape(client: TestClient) -> None:
    created = _create_demo_analysis(client)["analysis"]

    response = client.get(f"/api/v1/analyses/{created['analysis_id']}/findings/0")

    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {
        "finding_id",
        "detector_id",
        "detector_version",
        "category",
        "severity",
        "confidence",
        "priority_score",
        "calculated_observation",
        "affected_columns",
        "affected_row_count",
        "affected_row_numbers",
        "evidence_count",
        "security_exposure",
    }
    assert body["finding_id"] == "0"
    assert body["evidence_count"] >= 1
    assert len(body["affected_row_numbers"]) == body["affected_row_count"]
    assert body["affected_row_numbers"] == sorted(body["affected_row_numbers"])
    assert body["security_exposure"] == {
        "model_provider_enabled": False,
        "sample_transmission_enabled": False,
    }


def test_get_analysis_finding_detail_matches_list_item(client: TestClient) -> None:
    created = _create_demo_analysis(client)["analysis"]
    list_item = client.get(f"/api/v1/analyses/{created['analysis_id']}/findings").json()["items"][0]

    detail = client.get(f"/api/v1/analyses/{created['analysis_id']}/findings/0").json()

    for key in (
        "finding_id",
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
    ):
        assert detail[key] == list_item[key]


def test_get_analysis_finding_detail_unknown_analysis_returns_structured_404(
    client: TestClient,
) -> None:
    response = client.get("/api/v1/analyses/does-not-exist/findings/0")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ANALYSIS_NOT_FOUND"


def test_get_analysis_finding_detail_out_of_range_id_returns_structured_404(
    client: TestClient,
) -> None:
    created = _create_demo_analysis(client)["analysis"]
    out_of_range_id = str(created["finding_count"])

    response = client.get(f"/api/v1/analyses/{created['analysis_id']}/findings/{out_of_range_id}")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "FINDING_NOT_FOUND"


def test_get_analysis_finding_detail_before_completion_returns_finding_not_found(
    client: TestClient,
) -> None:
    """White-box: a known, not-yet-`completed` analysis has an empty
    `findings` tuple, so every `finding_id` is out of range —
    `FINDING_NOT_FOUND`, not a separate state-conflict error.
    """
    analysis_id = _create_queued_analysis_id(client)

    response = client.get(f"/api/v1/analyses/{analysis_id}/findings/0")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "FINDING_NOT_FOUND"


# --- GET /analyses/{id}/findings/{finding_id}/evidence (`WP-027`) --------


def test_get_analysis_finding_evidence_shape(client: TestClient) -> None:
    created = _create_demo_analysis(client)["analysis"]

    response = client.get(f"/api/v1/analyses/{created['analysis_id']}/findings/0/evidence")

    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {"items", "total_items"}
    assert body["total_items"] >= 1
    assert len(body["items"]) == body["total_items"]
    item = body["items"][0]
    assert set(item.keys()) == {
        "evidence_id",
        "evidence_type",
        "display_safe_summary",
        "affected_columns",
        "affected_row_count",
        "scope",
    }
    assert item["display_safe_summary"]
    # Never the raw structured payload (docs/domain-model.md #13: "report
    # references use display-safe summaries").
    assert "structured_payload" not in item


def test_get_analysis_finding_evidence_unknown_analysis_returns_structured_404(
    client: TestClient,
) -> None:
    response = client.get("/api/v1/analyses/does-not-exist/findings/0/evidence")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ANALYSIS_NOT_FOUND"


def test_get_analysis_finding_evidence_out_of_range_id_returns_structured_404(
    client: TestClient,
) -> None:
    created = _create_demo_analysis(client)["analysis"]
    out_of_range_id = str(created["finding_count"])

    response = client.get(
        f"/api/v1/analyses/{created['analysis_id']}/findings/{out_of_range_id}/evidence"
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "FINDING_NOT_FOUND"


# --- GET /analyses/{id}/findings/{finding_id}/row-context (`FIND-01`, `WP-038`) --


def _finding_with_rows(client: TestClient, analysis_id: str) -> dict[str, Any]:
    items = client.get(f"/api/v1/analyses/{analysis_id}/findings").json()["items"]
    for item in items:
        if item["affected_row_count"] > 0:
            return item  # type: ignore[no-any-return]
    raise AssertionError("expected at least one demo finding with affected rows")


def _finding_without_rows(client: TestClient, analysis_id: str) -> dict[str, Any]:
    items = client.get(f"/api/v1/analyses/{analysis_id}/findings").json()["items"]
    for item in items:
        if item["affected_row_count"] == 0:
            return item  # type: ignore[no-any-return]
    raise AssertionError("expected at least one demo finding with zero affected rows")


def test_get_analysis_finding_row_context_shape(client: TestClient) -> None:
    created = _create_demo_analysis(client)["analysis"]
    finding_item = _finding_with_rows(client, created["analysis_id"])
    detail = client.get(
        f"/api/v1/analyses/{created['analysis_id']}/findings/{finding_item['finding_id']}"
    ).json()
    anchor_row = detail["affected_row_numbers"][0]

    response = client.get(
        f"/api/v1/analyses/{created['analysis_id']}/findings/{finding_item['finding_id']}"
        f"/row-context",
        params={"anchor_row": anchor_row},
    )

    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {
        "columns",
        "requested_before",
        "requested_after",
        "actual_before",
        "actual_after",
        "truncated_at_start",
        "truncated_at_end",
        "max_window",
        "rows",
    }
    assert body["requested_before"] == 3
    assert body["requested_after"] == 3
    anchor_rows = [row for row in body["rows"] if row["is_anchor"]]
    assert len(anchor_rows) == 1
    assert anchor_rows[0]["row_number"] == anchor_row
    assert anchor_rows[0]["is_affected_by_finding"] is True
    for row in body["rows"]:
        assert set(row.keys()) == {
            "row_number",
            "is_anchor",
            "is_affected_by_finding",
            "values",
        }
        assert len(row["values"]) == len(body["columns"])


def test_get_analysis_finding_row_context_custom_window(client: TestClient) -> None:
    created = _create_demo_analysis(client)["analysis"]
    finding_item = _finding_with_rows(client, created["analysis_id"])
    detail = client.get(
        f"/api/v1/analyses/{created['analysis_id']}/findings/{finding_item['finding_id']}"
    ).json()
    anchor_row = detail["affected_row_numbers"][0]

    response = client.get(
        f"/api/v1/analyses/{created['analysis_id']}/findings/{finding_item['finding_id']}"
        f"/row-context",
        params={"anchor_row": anchor_row, "before": 1000, "after": 1000},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["requested_before"] == 1000
    assert body["max_window"] == 25
    assert body["actual_before"] <= 25
    assert body["actual_after"] <= 25


def test_get_analysis_finding_row_context_unrelated_row_returns_structured_404(
    client: TestClient,
) -> None:
    created = _create_demo_analysis(client)["analysis"]
    finding_item = _finding_without_rows(client, created["analysis_id"])

    response = client.get(
        f"/api/v1/analyses/{created['analysis_id']}/findings/{finding_item['finding_id']}"
        f"/row-context",
        params={"anchor_row": 0},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ROW_NOT_IN_FINDING"


def test_get_analysis_finding_row_context_unknown_analysis_returns_structured_404(
    client: TestClient,
) -> None:
    response = client.get(
        "/api/v1/analyses/does-not-exist/findings/0/row-context", params={"anchor_row": 0}
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ANALYSIS_NOT_FOUND"


def test_get_analysis_finding_row_context_out_of_range_finding_returns_structured_404(
    client: TestClient,
) -> None:
    created = _create_demo_analysis(client)["analysis"]
    out_of_range_id = str(created["finding_count"])

    response = client.get(
        f"/api/v1/analyses/{created['analysis_id']}/findings/{out_of_range_id}/row-context",
        params={"anchor_row": 0},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "FINDING_NOT_FOUND"


def test_get_analysis_finding_row_context_missing_anchor_row_returns_422(
    client: TestClient,
) -> None:
    created = _create_demo_analysis(client)["analysis"]
    finding_item = _finding_with_rows(client, created["analysis_id"])

    response = client.get(
        f"/api/v1/analyses/{created['analysis_id']}/findings/{finding_item['finding_id']}"
        f"/row-context"
    )

    assert response.status_code == 422


def test_get_analysis_finding_row_context_negative_before_returns_422(
    client: TestClient,
) -> None:
    created = _create_demo_analysis(client)["analysis"]
    finding_item = _finding_with_rows(client, created["analysis_id"])

    response = client.get(
        f"/api/v1/analyses/{created['analysis_id']}/findings/{finding_item['finding_id']}"
        f"/row-context",
        params={"anchor_row": 0, "before": -1},
    )

    assert response.status_code == 422


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


# --- POST /analyses (generic upload, WP-029) --------------------------

#: A small, deliberately flawed CSV — one row has a duplicate of another
#: (fires `structural.exact_duplicate_rows`) — proving the real pipeline
#: runs on uploaded content, not only demo content.
_FLAWED_CSV = b"name,amount\nAlice,10\nBob,20\nAlice,10\n"
_VALID_CSV = b"name,amount\nAlice,10\nBob,20\n"


def _upload_csv(
    client: TestClient, *, filename: str = "sample.csv", content: bytes = _VALID_CSV
) -> Any:
    return client.post("/api/v1/analyses", files={"file": (filename, content, "text/csv")})


def test_post_analyses_upload_returns_202_with_completed_analysis(client: TestClient) -> None:
    response = _upload_csv(client)

    assert response.status_code == 202
    body = response.json()
    assert body["analysis"]["state"] == "completed"
    assert body["analysis"]["dataset"]["source_type"] == "upload"
    assert body["analysis"]["dataset"]["format"] == "csv"
    assert body["analysis"]["dataset"]["byte_size"] == len(_VALID_CSV)
    assert body["analysis"]["dataset"]["content_hash"]


def test_post_analyses_upload_runs_real_pipeline_and_finds_issues(client: TestClient) -> None:
    response = _upload_csv(client, content=_FLAWED_CSV)

    assert response.status_code == 202
    body = response.json()
    assert body["analysis"]["finding_count"] > 0


def test_post_analyses_upload_response_has_exact_top_level_fields(client: TestClient) -> None:
    response = _upload_csv(client)

    assert set(response.json().keys()) == {"analysis", "status_url"}


def test_post_analyses_upload_produces_distinct_analysis_ids(client: TestClient) -> None:
    first = _upload_csv(client).json()
    second = _upload_csv(client).json()

    assert first["analysis"]["analysis_id"] != second["analysis"]["analysis_id"]


def test_post_analyses_upload_sanitizes_path_traversal_filename(client: TestClient) -> None:
    response = _upload_csv(client, filename="../../etc/passwd.csv")

    assert response.status_code == 202
    original_filename = response.json()["analysis"]["dataset"]["original_filename"]
    assert "/" not in original_filename
    assert "\\" not in original_filename
    assert original_filename == "passwd.csv"


def test_post_analyses_upload_no_file_returns_structured_422(client: TestClient) -> None:
    """`file: UploadFile` is a required parameter — FastAPI's own request
    validation rejects a request with no `file` part at all before the
    handler body ever runs, via the app's existing `FND-04`
    `RequestValidationError` -> `422 INVALID_REQUEST` global handler
    (no new code path needed here).
    """
    response = client.post("/api/v1/analyses", files={})

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


def test_post_analyses_upload_wrong_extension_returns_structured_415(
    client: TestClient,
) -> None:
    response = _upload_csv(client, filename="sample.txt")

    assert response.status_code == 415
    body = response.json()
    assert body["error"]["code"] == "UNSUPPORTED_FILE_TYPE"
    assert body["error"]["details"]["filename"] == "sample.txt"


def test_post_analyses_upload_xlsx_extension_returns_structured_415(
    client: TestClient,
) -> None:
    """`.xlsx` is a real, documented future format (`ING-03`) — still
    rejected today, same structured code as any other unsupported
    extension, no silent partial handling.
    """
    response = _upload_csv(client, filename="sample.xlsx")

    assert response.status_code == 415
    assert response.json()["error"]["code"] == "UNSUPPORTED_FILE_TYPE"


def test_post_analyses_upload_empty_file_returns_structured_400(client: TestClient) -> None:
    response = _upload_csv(client, content=b"")

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "INVALID_REQUEST"


def test_post_analyses_upload_oversized_file_returns_structured_413(
    client: TestClient,
) -> None:
    from trusttable_backend.config import get_settings

    max_bytes = get_settings().max_file_size_mb * 1024 * 1024
    oversized_content = b"a" * (max_bytes + 1)

    response = _upload_csv(client, content=oversized_content)

    assert response.status_code == 413
    body = response.json()
    assert body["error"]["code"] == "FILE_TOO_LARGE"
    assert body["error"]["details"]["max_bytes"] == max_bytes


def test_post_analyses_upload_no_analysis_created_on_rejection(client: TestClient) -> None:
    """A rejected upload (wrong extension) must not leave a stray
    `AnalysisStore` entry behind."""
    store: AnalysisStore = client.app.state.analysis_store  # type: ignore[attr-defined]
    before = len(store._analyses)  # test-only introspection of the in-memory dict

    response = _upload_csv(client, filename="sample.txt")

    assert response.status_code == 415
    after = len(store._analyses)
    assert after == before
    assert response.json()["error"]["code"] == "UNSUPPORTED_FILE_TYPE"
