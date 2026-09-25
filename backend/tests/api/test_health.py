"""Exact-shape tests for the health endpoints (WP-001 AC-01/AC-04).

Assertions pin field presence, types, nullability, and status codes to
WP-001's "Exact API contracts" — not a general shape check. WP-002 AC-09
adds the `configuration` check entry alongside WP-001's `process` entry.
`DB-01` (`WP-074`, AC-06) adds the `storage` check entry: every test
`client` fixture already builds a real, migrated, per-test-isolated
database (`conftest.py`), so `storage` is `"ok"` here exactly like
`configuration` is.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from trusttable_backend.api.v1.health import router as health_router
from trusttable_backend.config import Settings
from trusttable_backend.persistence import build_engine, run_migrations


def _unwired_health_app(settings: Settings) -> FastAPI:
    """A minimal app exposing only `health_router`, with
    `app.state.analysis_engine` set directly — used to observe the
    `storage` check's response to a database state `main.create_app()`'s
    own always-migrate-first behavior never actually leaves reachable
    through the real app (`docs/testing-strategy.md` §4 AC-06: readiness
    blocked during an invalid/pre-migration schema state).
    """
    app = FastAPI()
    app.include_router(health_router)
    app.state.analysis_engine = build_engine(settings)
    return app


def test_liveness_returns_200_with_exact_body(client: TestClient) -> None:
    response = client.get("/api/v1/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


def test_readiness_returns_200_ready_with_process_configuration_and_storage_checks(
    client: TestClient,
) -> None:
    response = client.get("/api/v1/health/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert body["checks"] == [
        {"name": "process", "status": "ok", "detail": None},
        {"name": "configuration", "status": "ok", "detail": None},
        {"name": "storage", "status": "ok", "detail": None},
    ]


def test_readiness_checks_entries_have_exact_fields(client: TestClient) -> None:
    body = client.get("/api/v1/health/ready").json()

    assert len(body["checks"]) == 3
    for check in body["checks"]:
        assert set(check.keys()) == {"name", "status", "detail"}
        assert isinstance(check["name"], str)
        assert check["status"] in {"ok", "failing", "not_configured"}
        assert check["detail"] is None or isinstance(check["detail"], str)


def test_readiness_top_level_has_exact_fields(client: TestClient) -> None:
    body = client.get("/api/v1/health/ready").json()

    assert set(body.keys()) == {"status", "checks"}
    assert body["status"] in {"ready", "not_ready"}
    assert isinstance(body["checks"], list)


# ---------------------------------------------------------------------------
# DB-01 (WP-074, AC-06): readiness reports the real migration state.
# ---------------------------------------------------------------------------


def test_readiness_reports_503_and_storage_failing_before_migration(tmp_path: Path) -> None:
    """An empty, never-migrated database: `storage` is `"failing"`, and the
    overall response is `503`/`not_ready` — `docs/testing-strategy.md` §4's
    "application readiness blocked during invalid schema state" bullet.
    """
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path / 'unmigrated.db'}",
        data_directory=str(tmp_path),
    )
    app = _unwired_health_app(settings)

    with TestClient(app) as client:
        response = client.get("/health/ready")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "not_ready"
    storage_check = next(check for check in body["checks"] if check["name"] == "storage")
    assert storage_check["status"] == "failing"
    assert storage_check["detail"] is not None


def test_readiness_reports_200_and_storage_ok_once_migrated(tmp_path: Path) -> None:
    """The same empty database, migrated to head first: `storage` is
    `"ok"` and the overall response is `200`/`ready` — the positive half
    of AC-06's migration-testing pair.
    """
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path / 'migrated.db'}",
        data_directory=str(tmp_path),
    )
    run_migrations(settings)
    app = _unwired_health_app(settings)

    with TestClient(app) as client:
        response = client.get("/health/ready")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    storage_check = next(check for check in body["checks"] if check["name"] == "storage")
    assert storage_check == {"name": "storage", "status": "ok", "detail": None}
