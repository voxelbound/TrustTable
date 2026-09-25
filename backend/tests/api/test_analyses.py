"""Tests for the analysis HTTP routes (`API-01`).

Exercises the six documented behaviors
(`docs/implementation-backlog.md#API-01`): create analysis / load demo
(`POST /demo/sales`), status, profile, findings, and cancel — against the
real app via the shared `client` fixture (`conftest.py`), each test
getting a fresh, isolated, durable `SqlAnalysisStore` (`DB-01`; one per
`create_app()` call, backed by that test's own isolated on-disk SQLite
database — see `conftest.py`'s `_hermetic_settings` fixture).

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

import pytest
from fastapi.testclient import TestClient

import trusttable_backend.api.v1.analyses as analyses_module
from trusttable_backend.ai_provider.contract import (
    ProviderConnectionError,
    ProviderRequest,
    ProviderResponse,
)
from trusttable_backend.analysis import AnalysisStoreProtocol, create_analysis, get_finding_evidence
from trusttable_backend.config import get_settings
from trusttable_backend.persistence.models import AnalysisRecord
from trusttable_backend.request_context import REQUEST_ID_HEADER

_VALID_AI_OUTPUT = {
    "schema_version": "1",
    "narrative": "A validated AI narrative.",
    "provenance": "ai_interpretation",
}


class _RecordingProvider:
    """A minimal `AIProvider`-protocol test double (structural, no
    inheritance needed — matches `AI-01`'s own established convention)
    that records every request it receives, so a test can inspect
    exactly what `PromptEnvelope` a route built and sent — real proof
    of wiring, not just a proof that *some* accepted response came
    back (`UI-02` slice 2 revision, `WP-064` r2)."""

    def __init__(self, raw_output: dict[str, object] | None = None) -> None:
        self._raw_output = raw_output
        self.requests: list[ProviderRequest] = []

    @property
    def provider_name(self) -> str:
        return "recording"

    def health_check(self) -> Any:
        raise NotImplementedError

    def complete(self, request: ProviderRequest) -> ProviderResponse:
        self.requests.append(request)
        contract = request.output_contract
        raw_output: dict[str, object] | Any
        if self._raw_output is not None:
            raw_output = self._raw_output
        elif contract is not None and contract.mock_output_factory is not None:
            # `AI-08`: a structured-contract request (the finding analysis)
            # gets the contract's own grounded default output.
            raw_output = contract.mock_output_factory(request.envelope)
        else:
            raw_output = dict(_VALID_AI_OUTPUT)
        return ProviderResponse(
            raw_output=raw_output,
            provider_name=self.provider_name,
            model_identifier="recording-v1",
            duration_ms=1.0,
        )


class _RejectingProvider:
    """`AIProvider`-protocol test double whose output never validates
    (missing required `narrative`), forcing `run_finding_explanation`'s
    retry-exhaustion/rejection path (`WP-065`, defect fix)."""

    @property
    def provider_name(self) -> str:
        return "rejecting"

    def health_check(self) -> Any:
        raise NotImplementedError

    def complete(self, request: ProviderRequest) -> ProviderResponse:
        return ProviderResponse(
            raw_output={"schema_version": "1", "provenance": "ai_interpretation"},
            provider_name=self.provider_name,
            model_identifier="rejecting-v1",
            duration_ms=1.0,
        )


class _ErroringProvider:
    """`AIProvider`-protocol test double whose `complete()` always raises
    a `ProviderError`, forcing the isolated-provider-error path
    (`WP-065`, defect fix)."""

    @property
    def provider_name(self) -> str:
        return "erroring"

    def health_check(self) -> Any:
        raise NotImplementedError

    def complete(self, request: ProviderRequest) -> ProviderResponse:
        raise ProviderConnectionError("simulated connection failure")


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
    store: AnalysisStoreProtocol = client.app.state.analysis_store  # type: ignore[attr-defined]
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


# --- GET /analyses/{id}/findings/{finding_id}/explanation (`UI-02` slice 1, `WP-063`) --


def test_get_analysis_finding_explanation_default_config_is_deterministic(
    client: TestClient,
) -> None:
    """Default config (`llm_provider="disabled"`, unchanged) — the
    response is the deterministic explanation, provider fields both
    `null`, `ai_call_status` (`WP-065`) discloses that no AI call was
    even attempted (distinct from a call that was attempted and
    failed/was rejected), and `evidence_sent_to_model`/
    `confirmed_context_sent_to_model` (`WP-065` r4, D-038 axis 5) are
    both `False` — nothing was sent since no attempt was made."""
    created = _create_demo_analysis(client)["analysis"]

    response = client.get(f"/api/v1/analyses/{created['analysis_id']}/findings/0/explanation")

    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {
        "finding_id",
        "narrative",
        "provenance",
        "provider_name",
        "model_identifier",
        "ai_provenance",
        "ai_call_status",
        "evidence_sent_to_model",
        "confirmed_context_sent_to_model",
        "referenced_evidence_ids",
        "referenced_columns",
        "business_impact",
        "remediation",
        "validation_rule",
    }
    assert body["finding_id"] == "0"
    assert body["narrative"]
    assert body["provenance"] == "deterministic_fallback"
    assert body["provider_name"] is None
    assert body["model_identifier"] is None
    assert body["ai_provenance"] is None
    assert body["ai_call_status"] == "not_configured"
    assert body["evidence_sent_to_model"] is False
    assert body["confirmed_context_sent_to_model"] is False
    assert body["referenced_evidence_ids"]
    # `AI-08`: with AI disabled the four sections are still all present and
    # useful — deterministic built-in guidance, never a placeholder.
    _assert_four_sections_present(body)
    assert all(item["basis"] == "assumption" for item in body["business_impact"])
    assert all(item["assumption"] for item in body["business_impact"])


def _assert_four_sections_present(body: dict[str, Any]) -> None:
    assert body["narrative"]
    assert body["business_impact"]
    for item in body["business_impact"]:
        assert set(item) == {"statement", "basis", "evidence_ids", "context_fields", "assumption"}
        assert item["statement"]
        # There is deliberately no "evidence" basis: the deterministic evidence
        # establishes what was found, not what it costs a business.
        assert item["basis"] in {"confirmed_context", "assumption"}
        assert item["assumption"]
    assert body["remediation"]
    assert all(step for step in body["remediation"])
    rule = body["validation_rule"]
    assert rule is not None
    assert set(rule) == {"rule_type", "columns", "description", "status"}
    assert rule["status"] == "proposed"
    assert rule["description"]


def test_get_analysis_finding_explanation_with_mock_provider_is_ai_interpretation(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`LLM_PROVIDER=mock` (real `MockProvider`, real factory) — the
    response is the AI-interpretation explanation, provider fields
    populated, `ai_call_status == "attempted_accepted"` (`WP-065`), and
    `evidence_sent_to_model is True`/`confirmed_context_sent_to_model
    is False` (`WP-065` r4, D-038 axis 5 — evidence was sent on this
    attempt, no context was finalized yet)."""
    created = _create_demo_analysis(client)["analysis"]
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    get_settings.cache_clear()

    response = client.get(f"/api/v1/analyses/{created['analysis_id']}/findings/0/explanation")

    assert response.status_code == 200
    body = response.json()
    assert body["provenance"] == "ai_interpretation"
    assert body["provider_name"] == "mock"
    assert body["model_identifier"] == "mock-v1"
    assert body["ai_provenance"] == {
        "deployment_label": "Test AI",
        "runtime_label": "Mock provider",
        "model_label": "mock-v1",
        "quantization": None,
        "model_identifier": "mock-v1",
    }
    assert body["ai_call_status"] == "attempted_accepted"
    assert body["evidence_sent_to_model"] is True
    assert body["confirmed_context_sent_to_model"] is False
    _assert_four_sections_present(body)


def test_get_analysis_finding_explanation_rejected_output_falls_back_with_status(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A provider that is called but never produces a validated output
    still returns the deterministic explanation unchanged (existing
    fallback contract), but `ai_call_status` (`WP-065`) now distinguishes
    this "attempted and rejected" outcome from "never attempted"
    (`not_configured`) — the exact ambiguity `provenance` alone cannot
    express."""
    created = _create_demo_analysis(client)["analysis"]
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    get_settings.cache_clear()
    monkeypatch.setattr(analyses_module, "create_provider", lambda *a, **kw: _RejectingProvider())

    response = client.get(f"/api/v1/analyses/{created['analysis_id']}/findings/0/explanation")

    assert response.status_code == 200
    body = response.json()
    assert body["provenance"] == "deterministic_fallback"
    assert body["provider_name"] is None
    assert body["model_identifier"] is None
    assert body["ai_provenance"] is None
    assert body["ai_call_status"] == "attempted_rejected"
    assert body["evidence_sent_to_model"] is True
    assert body["narrative"]
    # The fallback is the full deterministic four-section guidance, not a
    # partial or empty result.
    _assert_four_sections_present(body)


def test_get_analysis_finding_explanation_provider_error_falls_back_with_status(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A provider whose `complete()` raises a `ProviderError` still
    returns the deterministic explanation unchanged, with
    `ai_call_status == "attempted_provider_error"` (`WP-065`) —
    distinguished from both `not_configured` and `attempted_rejected`.
    No raw exception text reaches the response body."""
    created = _create_demo_analysis(client)["analysis"]
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    get_settings.cache_clear()
    monkeypatch.setattr(analyses_module, "create_provider", lambda *a, **kw: _ErroringProvider())

    response = client.get(f"/api/v1/analyses/{created['analysis_id']}/findings/0/explanation")

    assert response.status_code == 200
    body = response.json()
    assert body["provenance"] == "deterministic_fallback"
    assert body["ai_call_status"] == "attempted_provider_error"
    assert body["evidence_sent_to_model"] is True
    assert "simulated connection failure" not in response.text
    _assert_four_sections_present(body)


def _finding_with_category(client: TestClient, analysis_id: str, category: str) -> dict[str, Any]:
    items = client.get(f"/api/v1/analyses/{analysis_id}/findings").json()["items"]
    for item in items:
        if item["category"] == category:
            return item  # type: ignore[no-any-return]
    raise AssertionError(f"expected at least one demo finding in category {category!r}")


def test_get_analysis_finding_explanation_ai_call_status_independent_of_security_exposure(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Semantic proof (`WP-065`'s own `semantic.proof`): for a real
    `ai_processing_security` (prompt-injection) finding, an accepted AI
    explanation's `ai_call_status`/`provider_name`/`model_identifier`
    are genuinely independent of that same finding's own
    `security_exposure.model_provider_enabled` — the deterministic
    pipeline's unrelated, permanently-`False` raw-sample-exposure
    posture never varies with, and is never derived from, this
    per-request enrichment call's own outcome."""
    created = _create_demo_analysis(client)["analysis"]
    analysis_id = created["analysis_id"]
    finding_item = _finding_with_category(client, analysis_id, "ai_processing_security")
    finding_id = finding_item["finding_id"]
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    get_settings.cache_clear()

    explanation_response = client.get(
        f"/api/v1/analyses/{analysis_id}/findings/{finding_id}/explanation"
    )
    detail_response = client.get(f"/api/v1/analyses/{analysis_id}/findings/{finding_id}")

    assert explanation_response.status_code == 200
    explanation_body = explanation_response.json()
    assert explanation_body["ai_call_status"] == "attempted_accepted"
    assert explanation_body["provider_name"] == "mock"
    assert explanation_body["model_identifier"] == "mock-v1"
    assert explanation_body["evidence_sent_to_model"] is True

    assert detail_response.status_code == 200
    detail_body = detail_response.json()
    assert detail_body["security_exposure"]["model_provider_enabled"] is False
    assert detail_body["security_exposure"]["sample_transmission_enabled"] is False


def test_get_analysis_finding_explanation_preserves_canonical_evidence_when_sanitizing(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`WP-065` r4, D-038 axis 4 real-payload proof, end-to-end through
    the actual HTTP route (complementing `ai_boundary/test_prompt.py`'s
    and `ai_provider/test_llama_cpp.py`'s own lower-level proofs): for a
    real `ai_processing_security` demo finding with an accepted mock
    explanation, `evidence_sent_to_model` is genuinely `True` (bounded
    non-raw metadata was sent) while `security_exposure` stays `False`
    — and, independently, the canonical local `Evidence` object
    reachable through `analysis.service.get_finding_evidence` (the same
    object `ai_boundary.prompt._serialize_evidence` redacts *a copy
    of*, never mutates) still carries its own real
    `truncated_sample_prefix` value, unaffected by the AI-bound
    sanitization — proving the fix only touches the outgoing AI
    payload, never TrustTable's own retained evidence."""
    created = _create_demo_analysis(client)["analysis"]
    analysis_id = created["analysis_id"]
    finding_item = _finding_with_category(client, analysis_id, "ai_processing_security")
    finding_id = finding_item["finding_id"]
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    get_settings.cache_clear()

    explanation_response = client.get(
        f"/api/v1/analyses/{analysis_id}/findings/{finding_id}/explanation"
    )

    assert explanation_response.status_code == 200
    body = explanation_response.json()
    assert body["ai_call_status"] == "attempted_accepted"
    assert body["evidence_sent_to_model"] is True

    # White-box: the canonical local Evidence, reached the same way the
    # explanation route itself reaches it, still carries the real raw
    # excerpt — the fix never touches this object.
    store: AnalysisStoreProtocol = client.app.state.analysis_store  # type: ignore[attr-defined]
    evidence_items = get_finding_evidence(store, analysis_id, finding_id)
    security_pattern_items = [
        item for item in evidence_items if item.evidence_type.value == "security_pattern"
    ]
    assert security_pattern_items, "expected at least one security_pattern evidence item"
    assert security_pattern_items[0].structured_payload.get("truncated_sample_prefix")


def test_get_analysis_finding_explanation_confirmed_context_sent_to_model_after_finalize(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`confirmed_context_sent_to_model` (`WP-065` r4, D-038 axis 5)
    becomes `True` only once `POST .../finalize` has actually been
    called for this analysis — before finalize, evidence alone is sent
    (mirrors `test_get_analysis_finding_explanation_ignores_unfinalized_
    context`'s own established envelope-level proof, now asserted at
    the disclosed-field level a real UI consumes)."""
    created = _create_demo_analysis(client)["analysis"]
    analysis_id = created["analysis_id"]
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    get_settings.cache_clear()

    before_finalize = client.get(f"/api/v1/analyses/{analysis_id}/findings/0/explanation")
    assert before_finalize.json()["confirmed_context_sent_to_model"] is False
    assert before_finalize.json()["evidence_sent_to_model"] is True

    client.get(f"/api/v1/analyses/{analysis_id}/context")
    # `AI-08`: finalize alone never turns inferred values into confirmed
    # facts — the user must have confirmed or corrected a field.
    edit_response = client.put(
        f"/api/v1/analyses/{analysis_id}/context",
        json={"edits": {"row_grain": "One row per order"}, "expected_version": 1},
    )
    assert edit_response.status_code == 200
    finalize_response = client.post(
        f"/api/v1/analyses/{analysis_id}/finalize", json={"expected_version": 2}
    )
    assert finalize_response.status_code == 202

    after_finalize = client.get(f"/api/v1/analyses/{analysis_id}/findings/0/explanation")

    assert after_finalize.status_code == 200
    after_body = after_finalize.json()
    assert after_body["confirmed_context_sent_to_model"] is True
    assert after_body["evidence_sent_to_model"] is True


def test_finalizing_without_confirming_anything_sends_no_context_to_the_model(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`AI-08`: `finalize` alone must not present inferred values as
    confirmed. Nothing was confirmed or corrected, so nothing is sent and
    the disclosure says so."""
    created = _create_demo_analysis(client)["analysis"]
    analysis_id = created["analysis_id"]
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    get_settings.cache_clear()
    recording = _RecordingProvider()
    monkeypatch.setattr(analyses_module, "create_provider", lambda *a, **kw: recording)
    client.get(f"/api/v1/analyses/{analysis_id}/context")
    finalize_response = client.post(
        f"/api/v1/analyses/{analysis_id}/finalize", json={"expected_version": 1}
    )
    assert finalize_response.status_code == 202
    recording.requests.clear()

    response = client.get(f"/api/v1/analyses/{analysis_id}/findings/0/explanation")

    assert response.status_code == 200
    body = response.json()
    assert body["confirmed_context_sent_to_model"] is False
    assert body["evidence_sent_to_model"] is True
    assert len(recording.requests) == 1
    assert recording.requests[0].envelope.confirmed_context == {}


def test_get_analysis_finding_explanation_unknown_analysis_returns_structured_404(
    client: TestClient,
) -> None:
    response = client.get("/api/v1/analyses/does-not-exist/findings/0/explanation")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ANALYSIS_NOT_FOUND"


def test_get_analysis_finding_explanation_out_of_range_id_returns_structured_404(
    client: TestClient,
) -> None:
    created = _create_demo_analysis(client)["analysis"]
    out_of_range_id = str(created["finding_count"])

    response = client.get(
        f"/api/v1/analyses/{created['analysis_id']}/findings/{out_of_range_id}/explanation"
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "FINDING_NOT_FOUND"


# --- GET/PUT /analyses/{id}/context, /questions, .../answer, /finalize
# --- (`API-02`, `UI-02` slice 2, `WP-064`) --------------------------------

_CONTEXT_FIELD_KEYS = {
    "value",
    "confidence",
    "inference_source",
    "confirmation_state",
    "evidence_ids",
}
_CONTEXT_RESPONSE_KEYS = {
    "context_version",
    "schema_version",
    "probable_domain",
    "row_grain",
    "primary_entity",
    "candidate_keys",
    "business_dates",
    "measure_roles",
    "dimensions",
    "currency_behavior",
    "expected_business_rules",
}


def test_get_analysis_context_shape(client: TestClient) -> None:
    created = _create_demo_analysis(client)["analysis"]

    response = client.get(f"/api/v1/analyses/{created['analysis_id']}/context")

    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == _CONTEXT_RESPONSE_KEYS
    assert body["context_version"] == 1
    assert set(body["probable_domain"].keys()) == _CONTEXT_FIELD_KEYS
    assert isinstance(body["candidate_keys"]["value"], list)
    assert isinstance(body["probable_domain"]["value"], str)


def test_get_analysis_context_unknown_analysis_returns_structured_404(
    client: TestClient,
) -> None:
    response = client.get("/api/v1/analyses/does-not-exist/context")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ANALYSIS_NOT_FOUND"


def test_get_analysis_context_before_completion_returns_409(client: TestClient) -> None:
    """White-box: only a real `queued` analysis is not yet ready."""
    analysis_id = _create_queued_analysis_id(client)

    response = client.get(f"/api/v1/analyses/{analysis_id}/context")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_ANALYSIS_STATE"


def test_put_analysis_context_edits_field_and_increments_version(client: TestClient) -> None:
    created = _create_demo_analysis(client)["analysis"]
    analysis_id = created["analysis_id"]

    response = client.put(
        f"/api/v1/analyses/{analysis_id}/context",
        json={"edits": {"row_grain": "One row per order"}, "expected_version": 1},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["context_version"] == 2
    assert body["row_grain"]["value"] == "One row per order"
    assert body["row_grain"]["inference_source"] in {"user_confirmed", "user_corrected"}
    assert body["row_grain"]["confirmation_state"] in {"confirmed", "corrected"}


def test_put_analysis_context_version_conflict_returns_409(client: TestClient) -> None:
    created = _create_demo_analysis(client)["analysis"]
    analysis_id = created["analysis_id"]

    response = client.put(
        f"/api/v1/analyses/{analysis_id}/context",
        json={"edits": {"row_grain": "One row per order"}, "expected_version": 99},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CONTEXT_VERSION_CONFLICT"


def test_put_analysis_context_role_field_returns_422(client: TestClient) -> None:
    created = _create_demo_analysis(client)["analysis"]
    analysis_id = created["analysis_id"]

    response = client.put(
        f"/api/v1/analyses/{analysis_id}/context",
        json={"edits": {"candidate_keys": "order_id"}, "expected_version": 1},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_CONTEXT"


def test_put_analysis_context_unknown_field_returns_422(client: TestClient) -> None:
    created = _create_demo_analysis(client)["analysis"]
    analysis_id = created["analysis_id"]

    response = client.put(
        f"/api/v1/analyses/{analysis_id}/context",
        json={"edits": {"not_a_real_field": "x"}, "expected_version": 1},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_CONTEXT"


def test_get_analysis_questions_returns_known_demo_questions(client: TestClient) -> None:
    """Matches `CTX-03`/`API-02`'s own already-established real-demo-
    dataset fact: only `currency_behavior`/`expected_business_rules`
    remain unresolved."""
    created = _create_demo_analysis(client)["analysis"]

    response = client.get(f"/api/v1/analyses/{created['analysis_id']}/questions")

    assert response.status_code == 200
    body = response.json()
    assert body["total_items"] == 2
    fields = {item["context_field"] for item in body["items"]}
    assert fields == {"currency_behavior", "expected_business_rules"}
    item = body["items"][0]
    assert set(item.keys()) == {
        "question_id",
        "context_field",
        "concise_text",
        "explanation",
        "suggested_answers",
        "inferred_default",
        "affected_assumptions",
        "free_text_allowed",
        "answered_state",
    }
    assert item["answered_state"] == "unanswered"


def test_get_analysis_questions_unknown_analysis_returns_structured_404(
    client: TestClient,
) -> None:
    response = client.get("/api/v1/analyses/does-not-exist/questions")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ANALYSIS_NOT_FOUND"


def test_post_analysis_question_answer_marks_answered_and_updates_context(
    client: TestClient,
) -> None:
    created = _create_demo_analysis(client)["analysis"]
    analysis_id = created["analysis_id"]
    questions = client.get(f"/api/v1/analyses/{analysis_id}/questions").json()["items"]
    question_id = questions[0]["question_id"]
    context_field = questions[0]["context_field"]

    response = client.post(
        f"/api/v1/analyses/{analysis_id}/questions/{question_id}/answer",
        json={"answer_text": "A custom business answer", "expected_version": 1},
    )

    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {"context", "question", "answer"}
    assert body["question"]["question_id"] == question_id
    assert body["question"]["answered_state"] == "answered"
    assert body["answer"]["question_id"] == question_id
    assert body["answer"]["selected_answer_or_free_text"] == "A custom business answer"
    assert body["answer"]["provenance"] in {"user_confirmed", "user_corrected"}
    assert body["context"]["context_version"] == 2
    assert body["context"][context_field]["value"] == "A custom business answer"


def test_post_analysis_question_answer_unknown_question_returns_404(
    client: TestClient,
) -> None:
    created = _create_demo_analysis(client)["analysis"]
    analysis_id = created["analysis_id"]

    response = client.post(
        f"/api/v1/analyses/{analysis_id}/questions/does-not-exist/answer",
        json={"answer_text": "x", "expected_version": 1},
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "QUESTION_NOT_FOUND"


def test_post_analysis_question_answer_version_conflict_returns_409(
    client: TestClient,
) -> None:
    created = _create_demo_analysis(client)["analysis"]
    analysis_id = created["analysis_id"]
    question_id = client.get(f"/api/v1/analyses/{analysis_id}/questions").json()["items"][0][
        "question_id"
    ]

    response = client.post(
        f"/api/v1/analyses/{analysis_id}/questions/{question_id}/answer",
        json={"answer_text": "x", "expected_version": 99},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CONTEXT_VERSION_CONFLICT"


def test_post_analysis_finalize_returns_202_and_updated_resource(client: TestClient) -> None:
    created = _create_demo_analysis(client)["analysis"]
    analysis_id = created["analysis_id"]
    client.get(f"/api/v1/analyses/{analysis_id}/context")  # ensure context inferred (version 1)

    response = client.post(f"/api/v1/analyses/{analysis_id}/finalize", json={"expected_version": 1})

    assert response.status_code == 202
    body = response.json()
    assert body["analysis_id"] == analysis_id


def test_post_analysis_finalize_version_conflict_returns_409(client: TestClient) -> None:
    created = _create_demo_analysis(client)["analysis"]
    analysis_id = created["analysis_id"]
    client.get(f"/api/v1/analyses/{analysis_id}/context")

    response = client.post(
        f"/api/v1/analyses/{analysis_id}/finalize", json={"expected_version": 99}
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "CONTEXT_VERSION_CONFLICT"


def test_post_analysis_finalize_unknown_analysis_returns_structured_404(
    client: TestClient,
) -> None:
    response = client.post("/api/v1/analyses/does-not-exist/finalize", json={"expected_version": 1})

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ANALYSIS_NOT_FOUND"


# --- Real end-to-end CTX-02/context/explanation wiring (`UI-02` slice 2
# --- revision, `WP-064` r2; `docs/decision-log.md` D-037's "confirmed/
# --- finalized context available to the explanation/enrichment path"
# --- requirement) --------------------------------------------------------


def test_get_analysis_context_default_disabled_provider_never_calls_ctx02(
    client: TestClient,
) -> None:
    """Negative control: default config (`llm_provider="disabled"`,
    unchanged) never invokes CTX-02 — `probable_domain` stays the known
    real-demo-dataset deterministic (`CALCULATED`) value `CTX-01`/`WP-056`
    already established."""
    created = _create_demo_analysis(client)["analysis"]

    response = client.get(f"/api/v1/analyses/{created['analysis_id']}/context")

    body = response.json()
    assert body["probable_domain"]["value"] == "Sales / order transactions"
    assert body["probable_domain"]["inference_source"] == "calculated"


def test_get_analysis_context_wires_ctx02_ai_augmentation(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Real proof `GET .../context` calls `context_inference.ai_context.
    run_context_inference` through the trust boundary and persists the
    accepted AI-sourced `probable_domain` — not merely that some
    accepted response came back, but that the route actually built and
    sent a real `CONTEXT_INFERENCE` request and used its result."""
    created = _create_demo_analysis(client)["analysis"]
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    get_settings.cache_clear()
    recording = _RecordingProvider(
        {
            "schema_version": "1",
            "narrative": "This is a sales/order transaction dataset.",
            "provenance": "ai_interpretation",
        }
    )
    monkeypatch.setattr(analyses_module, "create_provider", lambda *a, **kw: recording)

    response = client.get(f"/api/v1/analyses/{created['analysis_id']}/context")

    assert response.status_code == 200
    body = response.json()
    assert body["probable_domain"]["value"] == "This is a sales/order transaction dataset."
    assert body["probable_domain"]["inference_source"] == "ai_interpretation"
    assert body["context_version"] == 1
    assert len(recording.requests) == 1
    assert recording.requests[0].operation.value == "context_inference"


def test_get_analysis_context_ai_augmentation_only_happens_once(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real provider is never called more than once per analysis —
    a second `GET .../context` returns the identical, already-augmented
    context without a second provider call."""
    created = _create_demo_analysis(client)["analysis"]
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    get_settings.cache_clear()
    recording = _RecordingProvider()
    monkeypatch.setattr(analyses_module, "create_provider", lambda *a, **kw: recording)

    first = client.get(f"/api/v1/analyses/{created['analysis_id']}/context")
    second = client.get(f"/api/v1/analyses/{created['analysis_id']}/context")

    assert first.json() == second.json()
    assert len(recording.requests) == 1


def test_get_analysis_finding_explanation_uses_confirmed_context_after_finalize(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Real end-to-end proof of the full flow: infer context, finalize
    it, then request a finding explanation — the explanation envelope
    actually carries the finalized `DatasetContext` as
    `confirmed_context`, not just Finding+Evidence as before this
    revision."""
    created = _create_demo_analysis(client)["analysis"]
    analysis_id = created["analysis_id"]
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    get_settings.cache_clear()
    recording = _RecordingProvider()
    monkeypatch.setattr(analyses_module, "create_provider", lambda *a, **kw: recording)

    client.get(f"/api/v1/analyses/{analysis_id}/context")
    edit_response = client.put(
        f"/api/v1/analyses/{analysis_id}/context",
        json={"edits": {"row_grain": "One row per order"}, "expected_version": 1},
    )
    assert edit_response.status_code == 200
    finalize_response = client.post(
        f"/api/v1/analyses/{analysis_id}/finalize", json={"expected_version": 2}
    )
    assert finalize_response.status_code == 202
    recording.requests.clear()  # isolate the explanation call's own request

    response = client.get(f"/api/v1/analyses/{analysis_id}/findings/0/explanation")

    assert response.status_code == 200
    assert len(recording.requests) == 1
    confirmed_context = recording.requests[0].envelope.confirmed_context
    # Only the field the user confirmed/corrected is sent; the inferred
    # `probable_domain` (still `CALCULATED`, never confirmed) is not.
    assert set(confirmed_context) == {"row_grain"}
    assert confirmed_context["row_grain"]["value"] == "One row per order"  # type: ignore[index]
    assert confirmed_context["row_grain"]["confirmation_state"] in {  # type: ignore[index]
        "confirmed",
        "corrected",
    }
    assert "probable_domain" not in confirmed_context


def test_get_analysis_finding_explanation_ignores_unfinalized_context(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Negative control: context inferred but not finalized — the
    explanation envelope's `confirmed_context` stays empty, matching
    this route's exact pre-revision (`WP-063`) behavior."""
    created = _create_demo_analysis(client)["analysis"]
    analysis_id = created["analysis_id"]
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    get_settings.cache_clear()
    recording = _RecordingProvider()
    monkeypatch.setattr(analyses_module, "create_provider", lambda *a, **kw: recording)

    client.get(f"/api/v1/analyses/{analysis_id}/context")
    recording.requests.clear()

    response = client.get(f"/api/v1/analyses/{analysis_id}/findings/0/explanation")

    assert response.status_code == 200
    assert len(recording.requests) == 1
    assert recording.requests[0].envelope.confirmed_context == {}


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


def _persisted_analysis_count(client: TestClient) -> int:
    """Test-only introspection of the real database row count (`DB-01`):
    reaches past `AnalysisStoreProtocol` into the concrete
    `SqlAnalysisStore`'s own session factory, the direct successor to
    this file's original in-memory-dict-length introspection.
    """
    from sqlalchemy import func, select

    store = client.app.state.analysis_store  # type: ignore[attr-defined]
    with store._session_factory() as session:  # noqa: SLF001 - white-box, test-only
        return session.scalar(select(func.count()).select_from(AnalysisRecord)) or 0


def test_post_analyses_upload_no_analysis_created_on_rejection(client: TestClient) -> None:
    """A rejected upload (wrong extension) must not leave a stray
    persisted analysis behind."""
    before = _persisted_analysis_count(client)

    response = _upload_csv(client, filename="sample.txt")

    assert response.status_code == 415
    after = _persisted_analysis_count(client)
    assert after == before
    assert response.json()["error"]["code"] == "UNSUPPORTED_FILE_TYPE"
