"""HTTP proof for the validated-rules export routes (`EXP-01` slice 1)
against the real FastAPI application and a real demo analysis."""

from __future__ import annotations

import json
import time
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any

import yaml
from fastapi.testclient import TestClient

from trusttable_backend.analysis import AnalysisState

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


def _create_rule(client: TestClient, analysis_id: str, name: str, **body: Any) -> str:
    response = client.post(
        f"/api/v1/analyses/{analysis_id}/rules",
        json={
            "name": name,
            "description": f"{name} description",
            "severity": "medium",
            "column_names": ["quantity"],
            **body,
        },
    )
    assert response.status_code == 201
    rule_id: str = response.json()["rule_id"]
    return rule_id


def _mutate_rules(client: TestClient, analysis_id: str, changes: dict[str, dict[str, Any]]) -> None:
    store = client.app.state.analysis_store  # type: ignore[attr-defined]
    analysis = store.get(analysis_id)
    rules = tuple(
        replace(rule, **changes[rule.rule_id]) if rule.rule_id in changes else rule
        for rule in analysis.rules
    )
    store.replace(replace(analysis, rules=rules))


def test_json_and_yaml_exports_match_and_are_downloads(client: TestClient) -> None:
    analysis_id = _completed_analysis(client)
    _create_rule(client, analysis_id, "not blank", rule_type="not_null")
    _create_rule(client, analysis_id, "range", rule_type="numeric_range", minimum=0.0)

    as_json = client.get(f"/api/v1/analyses/{analysis_id}/exports/rules.json")
    as_yaml = client.get(f"/api/v1/analyses/{analysis_id}/exports/rules.yaml")

    assert as_json.status_code == as_yaml.status_code == 200
    assert as_json.headers["content-type"].startswith("application/json")
    assert as_yaml.headers["content-type"].startswith("application/yaml")
    assert f"rules-{analysis_id}.json" in as_json.headers["content-disposition"]
    assert f"rules-{analysis_id}.yaml" in as_yaml.headers["content-disposition"]
    document = json.loads(as_json.text)
    assert document["rule_count"] == 2
    assert document["analysis_id"] == analysis_id
    assert yaml.safe_load(as_yaml.text) == document


def test_only_validated_rules_are_exported_and_the_rest_are_counted(client: TestClient) -> None:
    analysis_id = _completed_analysis(client)
    good = _create_rule(client, analysis_id, "good", rule_type="not_null")
    unrun = _create_rule(client, analysis_id, "unrun", rule_type="numeric_range", minimum=0.0)
    errored = _create_rule(
        client, analysis_id, "errored", rule_type="max_missing_percentage", threshold_percentage=50
    )
    disabled = _create_rule(
        client, analysis_id, "disabled", rule_type="accepted_values", accepted_values=["1"]
    )
    good_result = client.get(f"/api/v1/analyses/{analysis_id}/rules/{good}").json()["last_result"]
    assert good_result["error"] is None
    store = client.app.state.analysis_store  # type: ignore[attr-defined]
    template = store.get(analysis_id).rules[0].last_result
    _mutate_rules(
        client,
        analysis_id,
        {
            unrun: {"last_result": None},
            errored: {"last_result": replace(template, rule_id=errored, error="boom")},
            disabled: {"enabled": False},
        },
    )

    for extension in ("json", "yaml"):
        response = client.get(f"/api/v1/analyses/{analysis_id}/exports/rules.{extension}")
        document = (
            json.loads(response.text) if extension == "json" else yaml.safe_load(response.text)
        )
        assert [entry["rule_id"] for entry in document["rules"]] == [good]
        assert document["rule_count"] == 1
        assert document["excluded_rule_count"] == 3


def test_export_carries_no_row_derived_detail(client: TestClient) -> None:
    analysis_id = _completed_analysis(client)
    rule_id = _create_rule(
        client, analysis_id, "range", rule_type="numeric_range", minimum=1000000.0
    )
    detail = client.get(f"/api/v1/analyses/{analysis_id}/rules/{rule_id}").json()
    assert detail["last_result"]["fail_count"] > 0
    assert detail["last_result"]["example_failures"]

    for extension in ("json", "yaml"):
        text = client.get(f"/api/v1/analyses/{analysis_id}/exports/rules.{extension}").text
        assert "example" not in text
        assert "row_number" not in text
        assert "example_failures" not in text
    entry = json.loads(client.get(f"/api/v1/analyses/{analysis_id}/exports/rules.json").text)[
        "rules"
    ][0]
    assert set(entry["validation"]) == {"pass_count", "fail_count", "skipped_count"}


def test_export_is_byte_identical_across_calls(client: TestClient) -> None:
    analysis_id = _completed_analysis(client)
    _create_rule(client, analysis_id, "not blank", rule_type="not_null")

    for extension in ("json", "yaml"):
        url = f"/api/v1/analyses/{analysis_id}/exports/rules.{extension}"
        assert client.get(url).content == client.get(url).content


def test_a_completed_analysis_without_rules_exports_an_empty_list(client: TestClient) -> None:
    analysis_id = _completed_analysis(client)

    document = client.get(f"/api/v1/analyses/{analysis_id}/exports/rules.json").json()

    assert document["rules"] == []
    assert document["rule_count"] == 0


def test_unknown_analysis_is_404_for_both_formats(client: TestClient) -> None:
    for extension in ("json", "yaml"):
        response = client.get(f"/api/v1/analyses/nope/exports/rules.{extension}")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "ANALYSIS_NOT_FOUND"


def test_a_not_completed_analysis_is_409_for_both_formats(client: TestClient) -> None:
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

    for extension in ("json", "yaml"):
        response = client.get(f"/api/v1/analyses/{analysis_id}/exports/rules.{extension}")
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "INVALID_ANALYSIS_STATE"
