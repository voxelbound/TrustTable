from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from trusttable_backend.config import Settings, get_settings
from trusttable_backend.main import create_app


@pytest.fixture(autouse=True)
def _hermetic_settings(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
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
    """
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    for name in list(os.environ):
        if name.lower() in Settings.model_fields:
            monkeypatch.delenv(name)
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
