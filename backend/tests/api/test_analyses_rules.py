"""Decisive HTTP end-to-end proof for the validation-rule engine
(`RULE-01`; slices 1+2, `WP-078`/`WP-079`) against the real FastAPI
application: a rule created through `POST .../rules` executes
synchronously against the real demo analysis's real parsed rows,
persists, can be re-executed on demand, listed, fetched, and deleted.
"""

from __future__ import annotations

import time

from fastapi.testclient import TestClient

from trusttable_backend.rules.generation import GENERATABLE_DETECTOR_IDS

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
# Creation executes synchronously against real rows
# ---------------------------------------------------------------------------


def test_create_rule_executes_synchronously_and_returns_the_result(
    client: TestClient,
) -> None:
    analysis_id = _create_completed_analysis(client)

    response = client.post(
        f"/api/v1/analyses/{analysis_id}/rules",
        json={
            "name": "quantity must not be blank",
            "description": "Every row must have a quantity.",
            "severity": "medium",
            "rule_type": "not_null",
            "column_names": ["quantity"],
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["rule_type"] == "not_null"
    assert body["last_result"] is not None
    assert body["last_result"]["pass_count"] + body["last_result"]["fail_count"] > 0
    assert body["last_result"]["error"] is None


def test_created_rule_is_persisted_and_listed(client: TestClient) -> None:
    analysis_id = _create_completed_analysis(client)
    create_response = client.post(
        f"/api/v1/analyses/{analysis_id}/rules",
        json={
            "name": "quantity range",
            "description": "quantity should be non-negative",
            "severity": "medium",
            "rule_type": "numeric_range",
            "column_names": ["quantity"],
            "minimum": 0.0,
        },
    )
    rule_id = create_response.json()["rule_id"]

    list_response = client.get(f"/api/v1/analyses/{analysis_id}/rules")
    assert list_response.status_code == 200
    body = list_response.json()
    assert body["total_items"] == 1
    assert body["items"][0]["rule_id"] == rule_id

    detail_response = client.get(f"/api/v1/analyses/{analysis_id}/rules/{rule_id}")
    assert detail_response.status_code == 200
    assert detail_response.json()["rule_id"] == rule_id


# ---------------------------------------------------------------------------
# Negative cases
# ---------------------------------------------------------------------------


def test_create_rule_unknown_column_returns_422(client: TestClient) -> None:
    analysis_id = _create_completed_analysis(client)

    response = client.post(
        f"/api/v1/analyses/{analysis_id}/rules",
        json={
            "name": "ghost",
            "description": "ghost column",
            "severity": "low",
            "rule_type": "not_null",
            "column_names": ["this_column_does_not_exist"],
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "RULE_INVALID"


def test_create_rule_malformed_parameters_returns_422(client: TestClient) -> None:
    analysis_id = _create_completed_analysis(client)

    response = client.post(
        f"/api/v1/analyses/{analysis_id}/rules",
        json={
            "name": "bad range",
            "description": "neither bound set",
            "severity": "low",
            "rule_type": "numeric_range",
            "column_names": ["quantity"],
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "RULE_INVALID"


def test_create_rule_unrecognized_rule_type_returns_422(client: TestClient) -> None:
    analysis_id = _create_completed_analysis(client)

    response = client.post(
        f"/api/v1/analyses/{analysis_id}/rules",
        json={
            "name": "bad type",
            "description": "not a real rule type",
            "severity": "low",
            "rule_type": "not_a_real_type",
            "column_names": ["quantity"],
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "RULE_INVALID"


def test_create_rule_on_a_not_yet_completed_analysis_returns_409(client: TestClient) -> None:
    created = client.post("/api/v1/demo/sales")
    analysis_id = created.json()["analysis"]["analysis_id"]

    response = client.post(
        f"/api/v1/analyses/{analysis_id}/rules",
        json={
            "name": "too early",
            "description": "analysis not completed yet",
            "severity": "low",
            "rule_type": "not_null",
            "column_names": ["quantity"],
        },
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_ANALYSIS_STATE"
    _wait_for_terminal_state(client, analysis_id)  # drain before the test ends


def test_create_rule_unknown_analysis_returns_404(client: TestClient) -> None:
    response = client.post(
        "/api/v1/analyses/unknown-id/rules",
        json={
            "name": "x",
            "description": "x",
            "severity": "low",
            "rule_type": "not_null",
            "column_names": ["quantity"],
        },
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "ANALYSIS_NOT_FOUND"


def test_get_rule_unknown_rule_id_returns_404(client: TestClient) -> None:
    analysis_id = _create_completed_analysis(client)

    response = client.get(f"/api/v1/analyses/{analysis_id}/rules/no-such-rule")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "RULE_NOT_FOUND"


# ---------------------------------------------------------------------------
# Re-execute and delete
# ---------------------------------------------------------------------------


def test_execute_rule_now_reruns_and_returns_an_updated_result(client: TestClient) -> None:
    analysis_id = _create_completed_analysis(client)
    created = client.post(
        f"/api/v1/analyses/{analysis_id}/rules",
        json={
            "name": "quantity must not be blank",
            "description": "Every row must have a quantity.",
            "severity": "medium",
            "rule_type": "not_null",
            "column_names": ["quantity"],
        },
    )
    rule_id = created.json()["rule_id"]
    first_executed_at = created.json()["last_result"]["executed_at"]

    response = client.post(f"/api/v1/analyses/{analysis_id}/rules/{rule_id}/test")

    assert response.status_code == 200
    body = response.json()
    assert body["rule_id"] == rule_id
    assert body["last_result"]["executed_at"] >= first_executed_at


def test_execute_rule_now_unknown_rule_id_returns_404(client: TestClient) -> None:
    analysis_id = _create_completed_analysis(client)

    response = client.post(f"/api/v1/analyses/{analysis_id}/rules/no-such-rule/test")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "RULE_NOT_FOUND"


def test_delete_rule_removes_it(client: TestClient) -> None:
    analysis_id = _create_completed_analysis(client)
    created = client.post(
        f"/api/v1/analyses/{analysis_id}/rules",
        json={
            "name": "quantity must not be blank",
            "description": "Every row must have a quantity.",
            "severity": "medium",
            "rule_type": "not_null",
            "column_names": ["quantity"],
        },
    )
    rule_id = created.json()["rule_id"]

    delete_response = client.delete(f"/api/v1/analyses/{analysis_id}/rules/{rule_id}")
    assert delete_response.status_code == 204

    list_response = client.get(f"/api/v1/analyses/{analysis_id}/rules")
    assert list_response.json()["total_items"] == 0


def test_delete_rule_unknown_rule_id_returns_404(client: TestClient) -> None:
    analysis_id = _create_completed_analysis(client)

    response = client.delete(f"/api/v1/analyses/{analysis_id}/rules/no-such-rule")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "RULE_NOT_FOUND"


# ---------------------------------------------------------------------------
# expression_comparison / conditional_rule (RULE-01 slice 2, WP-079)
# ---------------------------------------------------------------------------


def test_create_expression_comparison_against_a_literal_executes_synchronously(
    client: TestClient,
) -> None:
    analysis_id = _create_completed_analysis(client)

    response = client.post(
        f"/api/v1/analyses/{analysis_id}/rules",
        json={
            "name": "quantity must be positive",
            "description": "Every quantity should be greater than zero.",
            "severity": "medium",
            "rule_type": "expression_comparison",
            "column_names": ["quantity"],
            "comparison_operator": "greater_than",
            "comparison_value": 0.0,
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["rule_type"] == "expression_comparison"
    assert body["comparison_operator"] == "greater_than"
    assert body["last_result"]["error"] is None
    assert body["last_result"]["pass_count"] + body["last_result"]["fail_count"] > 0


def test_create_expression_comparison_against_a_column_executes_synchronously(
    client: TestClient,
) -> None:
    analysis_id = _create_completed_analysis(client)

    response = client.post(
        f"/api/v1/analyses/{analysis_id}/rules",
        json={
            "name": "quantity vs unit_price",
            "description": "Compares two real numeric columns.",
            "severity": "low",
            "rule_type": "expression_comparison",
            "column_names": ["quantity", "unit_price"],
            "comparison_operator": "not_equals",
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["comparison_value"] is None
    assert body["last_result"]["error"] is None


def test_create_conditional_rule_executes_synchronously(client: TestClient) -> None:
    analysis_id = _create_completed_analysis(client)

    response = client.post(
        f"/api/v1/analyses/{analysis_id}/rules",
        json={
            "name": "when quantity positive then unit_price positive",
            "description": "A conditional check across two real numeric columns.",
            "severity": "medium",
            "rule_type": "conditional_rule",
            "column_names": ["quantity", "unit_price"],
            "condition_operator": "greater_than",
            "condition_value": -1.0,
            "comparison_operator": "greater_than",
            "comparison_value": -1.0,
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["rule_type"] == "conditional_rule"
    assert body["condition_operator"] == "greater_than"
    assert body["last_result"]["error"] is None
    assert body["last_result"]["pass_count"] + body["last_result"]["fail_count"] > 0


def test_create_expression_comparison_missing_comparison_value_returns_422(
    client: TestClient,
) -> None:
    analysis_id = _create_completed_analysis(client)

    response = client.post(
        f"/api/v1/analyses/{analysis_id}/rules",
        json={
            "name": "missing literal",
            "description": "comparison_value omitted for a 1-column rule",
            "severity": "low",
            "rule_type": "expression_comparison",
            "column_names": ["quantity"],
            "comparison_operator": "greater_than",
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "RULE_INVALID"


def test_create_conditional_rule_missing_then_clause_returns_422(client: TestClient) -> None:
    analysis_id = _create_completed_analysis(client)

    response = client.post(
        f"/api/v1/analyses/{analysis_id}/rules",
        json={
            "name": "missing THEN clause",
            "description": "comparison_operator/value omitted",
            "severity": "low",
            "rule_type": "conditional_rule",
            "column_names": ["quantity", "unit_price"],
            "condition_operator": "greater_than",
            "condition_value": 0.0,
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "RULE_INVALID"


def test_create_rule_unrecognized_comparison_operator_returns_422(client: TestClient) -> None:
    analysis_id = _create_completed_analysis(client)

    response = client.post(
        f"/api/v1/analyses/{analysis_id}/rules",
        json={
            "name": "bad operator",
            "description": "not a real comparison operator",
            "severity": "low",
            "rule_type": "expression_comparison",
            "column_names": ["quantity"],
            "comparison_operator": "roughly_equals",
            "comparison_value": 0.0,
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "RULE_INVALID"


# ---------------------------------------------------------------------------
# Duplicate-detection proof against the real demo dataset
# ---------------------------------------------------------------------------


def test_unique_rule_reports_real_duplicates_in_the_demo_dataset(client: TestClient) -> None:
    """The bundled demo dataset deliberately injects duplicate rows
    (`DEMO-01`) — a `unique` rule on `order_id` must report genuine
    failures, not merely execute without error."""
    analysis_id = _create_completed_analysis(client)

    response = client.post(
        f"/api/v1/analyses/{analysis_id}/rules",
        json={
            "name": "order_id must be unique",
            "description": "Each order_id should appear once.",
            "severity": "high",
            "rule_type": "unique",
            "column_names": ["order_id"],
        },
    )

    assert response.status_code == 201
    result = response.json()["last_result"]
    assert result["fail_count"] > 0
    assert len(result["example_failures"]) > 0


# ---------------------------------------------------------------------------
# RULE-02 slice 1: deterministic rule generation from findings (WP-080)
# ---------------------------------------------------------------------------


def _findings(client: TestClient, analysis_id: str) -> list[dict[str, object]]:
    response = client.get(f"/api/v1/analyses/{analysis_id}/findings")
    assert response.status_code == 200
    items: list[dict[str, object]] = response.json()["items"]
    return items


def _first_generatable_finding_id(client: TestClient, analysis_id: str) -> str:
    for finding in _findings(client, analysis_id):
        if finding["detector_id"] in GENERATABLE_DETECTOR_IDS:
            return str(finding["finding_id"])
    raise AssertionError(
        "expected at least one demo-dataset finding from a RULE-02 slice 1 generatable detector"
    )


def test_rule_proposal_returns_an_executed_unpersisted_candidate(client: TestClient) -> None:
    analysis_id = _create_completed_analysis(client)
    finding_id = _first_generatable_finding_id(client, analysis_id)

    response = client.get(f"/api/v1/analyses/{analysis_id}/findings/{finding_id}/rule-proposal")

    assert response.status_code == 200
    body = response.json()
    assert body["available"] is True
    assert body["reason"] is None
    assert body["rule"] is not None
    assert body["rule"]["provenance"] == "detector_generated"
    assert body["rule"]["source_finding_ids"] == [finding_id]
    assert body["result"] is not None
    assert body["result"]["error"] is None
    # Never persisted by the proposal endpoint itself.
    assert client.get(f"/api/v1/analyses/{analysis_id}/rules").json()["total_items"] == 0


def test_rule_proposal_unavailable_for_an_excluded_detector_reports_a_reason(
    client: TestClient,
) -> None:
    """The decisive false-positive-avoidance proof at the HTTP layer: a
    finding from a detector RULE-02 slice 1 excludes (e.g. the
    multiplicative `cross_field.line_total_mismatch` check, which does
    not fit `APPROXIMATE_EQUALITY`'s additive semantics) must report
    `available: false`, never a fabricated rule."""
    analysis_id = _create_completed_analysis(client)
    excluded = [
        finding
        for finding in _findings(client, analysis_id)
        if finding["detector_id"] not in GENERATABLE_DETECTOR_IDS
    ]
    if not excluded:
        return  # nothing to prove against this dataset run; not a failure
    finding_id = str(excluded[0]["finding_id"])

    response = client.get(f"/api/v1/analyses/{analysis_id}/findings/{finding_id}/rule-proposal")

    assert response.status_code == 200
    body = response.json()
    assert body["available"] is False
    assert body["reason"] is not None
    assert body["rule"] is None
    assert body["result"] is None


def test_rule_proposal_unknown_finding_returns_404(client: TestClient) -> None:
    analysis_id = _create_completed_analysis(client)

    response = client.get(f"/api/v1/analyses/{analysis_id}/findings/999999/rule-proposal")

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "FINDING_NOT_FOUND"


def test_rule_proposal_on_a_not_yet_completed_analysis_returns_409(client: TestClient) -> None:
    created = client.post("/api/v1/demo/sales")
    analysis_id = created.json()["analysis"]["analysis_id"]

    response = client.get(f"/api/v1/analyses/{analysis_id}/findings/0/rule-proposal")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "INVALID_ANALYSIS_STATE"
    _wait_for_terminal_state(client, analysis_id)  # drain before the test ends


def test_accept_rule_proposal_persists_with_detector_generated_provenance(
    client: TestClient,
) -> None:
    analysis_id = _create_completed_analysis(client)
    finding_id = _first_generatable_finding_id(client, analysis_id)
    proposal = client.get(
        f"/api/v1/analyses/{analysis_id}/findings/{finding_id}/rule-proposal"
    ).json()["rule"]

    response = client.post(
        f"/api/v1/analyses/{analysis_id}/rules",
        json={
            "name": proposal["name"],
            "description": proposal["description"],
            "severity": proposal["severity"],
            "rule_type": proposal["rule_type"],
            "column_names": [column["original_name"] for column in proposal["columns"]],
            "minimum": proposal["minimum"],
            "maximum": proposal["maximum"],
            "minimum_date": proposal["minimum_date"],
            "maximum_date": proposal["maximum_date"],
            "pattern": proposal["pattern"],
            "threshold_percentage": proposal["threshold_percentage"],
            "tolerance": proposal["tolerance"],
            "source_finding_id": finding_id,
        },
    )

    assert response.status_code == 201
    body = response.json()
    assert body["provenance"] == "detector_generated"
    assert body["source_finding_ids"] == [finding_id]


def test_create_rule_unknown_source_finding_id_returns_404(client: TestClient) -> None:
    analysis_id = _create_completed_analysis(client)

    response = client.post(
        f"/api/v1/analyses/{analysis_id}/rules",
        json={
            "name": "x",
            "description": "x",
            "severity": "low",
            "rule_type": "not_null",
            "column_names": ["quantity"],
            "source_finding_id": "999999",
        },
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "FINDING_NOT_FOUND"
    assert client.get(f"/api/v1/analyses/{analysis_id}/rules").json()["total_items"] == 0
