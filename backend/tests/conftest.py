from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from trusttable_backend.config import Settings, get_settings
from trusttable_backend.main import create_app


@pytest.fixture(autouse=True)
def _hermetic_settings(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[None]:
    """Make every test observe the documented `Settings` defaults (FUP-013).

    `Settings()` reads a repository-root `.env` and the process environment.
    A developer machine configured for a real provider (for example
    `LLM_PROVIDER=llama_cpp` in `.env`) would otherwise change the outcome of
    tests that assume the documented default, so local results would differ
    from CI, which has no `.env`. This fixture removes both inputs for the
    duration of each test: the env file is disabled on `Settings` itself, and
    every environment variable that names a `Settings` field is removed
    (case-insensitively, matching `Settings`' own `case_sensitive=False`).

    A test remains free to configure `Settings` explicitly (`monkeypatch.setenv`,
    constructor arguments, or an explicit `_env_file=`): this fixture runs
    before the test body, and `monkeypatch` restores everything afterwards.

    `DATABASE_URL`/`DATA_DIRECTORY` (`DB-01`) are then set to a fresh,
    isolated on-disk SQLite database under pytest's own per-test
    `tmp_path` — every test that builds a real app now runs
    `main.create_app()`'s real engine/migration path, and the documented
    built-in default (`sqlite:////data/trusttable.db`) is a Docker
    Compose-only absolute path this fixture must never touch. A test that
    checks the true documented defaults (`tests/config/test_settings.py`)
    already clears these two variables itself immediately before
    constructing `Settings`, so this override does not affect it. A real
    `subprocess.Popen` (`tests/analysis/test_service.py`'s Uvicorn-boot
    test) inherits these same values automatically: `monkeypatch.setenv`
    mutates the actual process `os.environ`.
    """
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    for name in list(os.environ):
        if name.lower() in Settings.model_fields:
            monkeypatch.delenv(name)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'trusttable-test.db'}")
    monkeypatch.setenv("DATA_DIRECTORY", str(tmp_path))
    yield


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> Iterator[None]:
    """Ensure every test observes a fresh `Settings` load (FND-02).

    `get_settings()` is cached for the process lifetime (`lru_cache`).
    Without clearing it before and after each test, a test that
    monkeypatches environment variables would silently observe a
    previous test's cached `Settings` instance instead of its own.
    """
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def client() -> Iterator[TestClient]:
    with TestClient(create_app()) as test_client:
        yield test_client
