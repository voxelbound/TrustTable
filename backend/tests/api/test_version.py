"""Exact-shape tests for `GET /api/v1/version` (WP-001 AC-01/AC-04).

`environment_mode` sourcing from typed `Settings` (WP-002 AC-08) is
covered here for `version_info.get_environment_mode()` itself; full
per-field configuration validation lives in `tests/config/test_settings.py`.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

import trusttable_backend.version_info as version_info_module


def test_version_returns_200_with_exact_field_set(client: TestClient) -> None:
    response = client.get("/api/v1/version")

    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {
        "application_version",
        "api_version",
        "schema_version",
        "detector_catalogue_version",
        "build_commit",
        "environment_mode",
    }


def test_version_field_types_and_nullability(client: TestClient) -> None:
    body = client.get("/api/v1/version").json()

    assert isinstance(body["application_version"], str) and body["application_version"]
    assert body["api_version"] == "v1"
    assert body["schema_version"] is None
    assert body["detector_catalogue_version"] is None
    assert body["build_commit"] is None or isinstance(body["build_commit"], str)
    assert body["environment_mode"] in {"development", "test", "production"}


def test_version_defaults_environment_mode_to_development_when_unset(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("APP_ENV", raising=False)
    body = client.get("/api/v1/version").json()
    assert body["environment_mode"] == "development"


def test_version_reads_environment_mode_from_app_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("APP_ENV", "production")
    assert version_info_module.get_environment_mode() == "production"


def test_version_rejects_unknown_app_env_instead_of_falling_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Superseded by WP-002: an unrecognized APP_ENV now fails fast

    (`Settings` validation) rather than silently falling back to
    "development", as WP-001's temporary raw env-var read used to do.
    """
    monkeypatch.setenv("APP_ENV", "not-a-real-mode")
    with pytest.raises(ValidationError):
        version_info_module.get_environment_mode()
