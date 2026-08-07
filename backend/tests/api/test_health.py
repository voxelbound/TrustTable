"""Exact-shape tests for the health endpoints (WP-001 AC-01/AC-04).

Assertions pin field presence, types, nullability, and status codes to
WP-001's "Exact API contracts" — not a general shape check.
"""

from __future__ import annotations

from fastapi.testclient import TestClient


def test_liveness_returns_200_with_exact_body(client: TestClient) -> None:
    response = client.get("/api/v1/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


def test_readiness_returns_200_ready_with_process_check(client: TestClient) -> None:
    response = client.get("/api/v1/health/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["checks"] == [{"name": "process", "status": "ok", "detail": None}]


def test_readiness_checks_entry_has_exact_fields(client: TestClient) -> None:
    body = client.get("/api/v1/health/ready").json()

    check = body["checks"][0]
    assert set(check.keys()) == {"name", "status", "detail"}
    assert isinstance(check["name"], str)
    assert check["status"] in {"ok", "failing", "not_configured"}
    assert check["detail"] is None or isinstance(check["detail"], str)


def test_readiness_top_level_has_exact_fields(client: TestClient) -> None:
    body = client.get("/api/v1/health/ready").json()

    assert set(body.keys()) == {"status", "checks"}
    assert body["status"] in {"ready", "not_ready"}
    assert isinstance(body["checks"], list)
