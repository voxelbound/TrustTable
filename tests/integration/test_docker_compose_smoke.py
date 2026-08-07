"""Docker Compose integration smoke test (WP-001 AC-03/AC-09/AC-10).

Drives `docker compose up`/`down` against the real Docker daemon and
verifies the six checks in WP-001's "Compose smoke-test requirements":

1. frontend reachability,
2. backend reachability,
3. `/api/v1` proxying through the frontend/Nginx origin,
4. SPA fallback for a non-root route,
5. clean startup/shutdown within a bounded timeout with no error-level
   log lines,
6. only the intended ports (8000, 8080) are published.

Requires a reachable Docker daemon (unsandboxed socket access) and
buildable `backend`/`frontend` images. Not part of the default backend
unit-test suite; invoke explicitly from the `backend` project, e.g.:

    uv run --project backend pytest ../tests/integration -v
"""

from __future__ import annotations

import json
import re
import subprocess
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest

COMPOSE_FILE = Path(__file__).resolve().parents[2] / "docker-compose.yml"
BACKEND_URL = "http://127.0.0.1:8000"
FRONTEND_URL = "http://127.0.0.1:8080"
UP_TIMEOUT_SECONDS = 90
DOWN_TIMEOUT_SECONDS = 30
INTENDED_HOST_PORTS = {8000, 8080}

# Log-level markers for a real startup failure, not incidental use of
# the word "error" in ordinary text: Uvicorn/Python logging's "ERROR:"
# prefix, nginx's "[error]" tag, and Python tracebacks.
ERROR_LOG_PATTERN = re.compile(r"ERROR:|\[error\]|Traceback \(most recent call last\)")


def _run_compose(*args: str, timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE_FILE), *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


@dataclass
class ComposeStack:
    startup_seconds: float
    logs: str


@pytest.fixture(scope="module")
def compose_stack() -> Iterator[ComposeStack]:
    start = time.monotonic()
    up_result = _run_compose(
        "up",
        "-d",
        "--wait",
        "--wait-timeout",
        str(UP_TIMEOUT_SECONDS),
        timeout=UP_TIMEOUT_SECONDS + 10,
    )
    startup_seconds = time.monotonic() - start
    assert up_result.returncode == 0, (
        f"docker compose up failed:\nstdout={up_result.stdout}\nstderr={up_result.stderr}"
    )

    logs_result = _run_compose("logs", "--no-color", timeout=30)

    try:
        yield ComposeStack(startup_seconds=startup_seconds, logs=logs_result.stdout)
    finally:
        down_start = time.monotonic()
        down_result = _run_compose("down", timeout=DOWN_TIMEOUT_SECONDS + 10)
        down_seconds = time.monotonic() - down_start
        assert down_result.returncode == 0, (
            f"docker compose down failed:\nstdout={down_result.stdout}\nstderr={down_result.stderr}"
        )
        assert down_seconds <= DOWN_TIMEOUT_SECONDS, (
            f"docker compose down took {down_seconds:.1f}s, expected <= {DOWN_TIMEOUT_SECONDS}s"
        )


def test_clean_startup_within_timeout_with_no_error_log_lines(
    compose_stack: ComposeStack,
) -> None:
    assert compose_stack.startup_seconds <= UP_TIMEOUT_SECONDS
    error_lines = [
        line for line in compose_stack.logs.splitlines() if ERROR_LOG_PATTERN.search(line)
    ]
    assert error_lines == [], f"unexpected error-level log lines: {error_lines}"


def test_backend_reachable_directly(compose_stack: ComposeStack) -> None:
    response = httpx.get(f"{BACKEND_URL}/api/v1/health/live", timeout=5)

    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


def test_frontend_reachable_directly(compose_stack: ComposeStack) -> None:
    response = httpx.get(f"{FRONTEND_URL}/", timeout=5)

    assert response.status_code == 200
    assert '<div id="root">' in response.text
    assert "<title>TrustTable</title>" in response.text


def test_proxy_forwards_health_live_to_backend(compose_stack: ComposeStack) -> None:
    direct = httpx.get(f"{BACKEND_URL}/api/v1/health/live", timeout=5)
    proxied = httpx.get(f"{FRONTEND_URL}/api/v1/health/live", timeout=5)

    assert proxied.status_code == direct.status_code == 200
    assert proxied.json() == direct.json()


def test_proxy_forwards_version_to_backend(compose_stack: ComposeStack) -> None:
    direct = httpx.get(f"{BACKEND_URL}/api/v1/version", timeout=5)
    proxied = httpx.get(f"{FRONTEND_URL}/api/v1/version", timeout=5)

    assert proxied.status_code == direct.status_code == 200
    assert proxied.json() == direct.json()


def test_spa_fallback_serves_index_html_for_unknown_route(
    compose_stack: ComposeStack,
) -> None:
    response = httpx.get(f"{FRONTEND_URL}/some/nonexistent/route", timeout=5)

    assert response.status_code == 200
    assert '<div id="root">' in response.text
    assert "<!doctype html>" in response.text.lower()


def test_only_intended_ports_are_published(compose_stack: ComposeStack) -> None:
    config_result = _run_compose("config", "--format", "json", timeout=15)
    assert config_result.returncode == 0

    config = json.loads(config_result.stdout)
    published_ports = {
        int(port["published"])
        for service in config["services"].values()
        for port in service.get("ports", [])
    }

    assert published_ports == INTENDED_HOST_PORTS
