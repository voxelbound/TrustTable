from __future__ import annotations

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from trusttable_backend.config import get_settings
from trusttable_backend.main import create_app


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
