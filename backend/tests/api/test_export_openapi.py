"""Tests for `export_openapi` (FND-05, WP-005 AC-01).

Asserts the exported document is valid OpenAPI JSON, matches
`create_app().openapi()` exactly, contains the currently-registered
paths, and that `main()` can write either to stdout or to a given file
path with no live server/database required.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from trusttable_backend.export_openapi import get_openapi_schema, main
from trusttable_backend.main import create_app


def test_get_openapi_schema_matches_create_app_openapi() -> None:
    schema = get_openapi_schema()
    expected = create_app().openapi()

    assert schema == expected


def test_get_openapi_schema_is_valid_openapi_document() -> None:
    schema = get_openapi_schema()

    assert "openapi" in schema
    assert isinstance(schema["openapi"], str)
    assert schema["openapi"].startswith("3.")
    assert "paths" in schema
    assert isinstance(schema["paths"], dict)


def test_get_openapi_schema_contains_registered_paths() -> None:
    schema = get_openapi_schema()
    paths = schema["paths"]

    assert isinstance(paths, dict)
    assert set(paths.keys()) >= {
        "/api/v1/health/live",
        "/api/v1/health/ready",
        "/api/v1/version",
    }


def test_main_writes_to_given_output_path(tmp_path: Path) -> None:
    output_path = tmp_path / "schema.json"

    exit_code = main([str(output_path)])

    assert exit_code == 0
    written = json.loads(output_path.read_text(encoding="utf-8"))
    assert written == get_openapi_schema()


def test_main_writes_to_stdout_when_no_path_given(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main([])

    assert exit_code == 0
    captured = capsys.readouterr()
    written = json.loads(captured.out)
    assert written == get_openapi_schema()
