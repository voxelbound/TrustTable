"""Docker Compose persistence-survives-restart integration test (`DB-01`,
`WP-074` AC-07).

Proves the real, deployed stack — not merely `create_app()` in-process —
actually persists: an analysis created through the real backend
container survives `docker compose restart backend`, because the SQLite
file lives on the named `/data` volume `docker-compose.yml` now declares,
not in the container's own writable layer (which `restart` does not
wipe, but a real redeploy/recreate would).

Requires a reachable Docker daemon (unsandboxed socket access) and a
buildable `backend` image — the same precondition
`test_docker_compose_smoke.py` already documents. Not part of the
default backend unit-test suite; invoke explicitly, e.g.:

    uv run --project backend pytest ../tests/integration/test_docker_compose_persistence.py -v
"""

from __future__ import annotations

import subprocess
import time
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = REPO_ROOT / "docker-compose.yml"
BACKEND_URL = "http://127.0.0.1:8000"
BUILD_TIMEOUT_SECONDS = 180
UP_TIMEOUT_SECONDS = 90
RESTART_TIMEOUT_SECONDS = 60
READY_POLL_TIMEOUT_SECONDS = 60
DOWN_TIMEOUT_SECONDS = 30


def _run_compose(*args: str, timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE_FILE), *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


def _wait_until_ready(timeout: float) -> None:
    deadline = time.monotonic() + timeout
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        try:
            response = httpx.get(f"{BACKEND_URL}/api/v1/health/ready", timeout=2)
            if response.status_code == 200 and response.json().get("status") == "ready":
                return
        except httpx.HTTPError as exc:  # noqa: PERF203 - a bounded startup poll, not a hot loop
            last_error = exc
        time.sleep(0.5)
    raise AssertionError(f"backend never became ready within {timeout}s (last_error={last_error!r})")


@pytest.fixture(scope="module")
def compose_stack() -> Iterator[None]:
    build_result = _run_compose("build", "backend", timeout=BUILD_TIMEOUT_SECONDS)
    assert build_result.returncode == 0, (
        f"docker compose build failed:\nstdout={build_result.stdout}\nstderr={build_result.stderr}"
    )

    up_result = _run_compose(
        "up",
        "-d",
        "--wait",
        "--wait-timeout",
        str(UP_TIMEOUT_SECONDS),
        "backend",
        timeout=UP_TIMEOUT_SECONDS + 10,
    )
    assert up_result.returncode == 0, (
        f"docker compose up failed:\nstdout={up_result.stdout}\nstderr={up_result.stderr}"
    )

    try:
        yield
    finally:
        down_result = _run_compose("down", "-v", timeout=DOWN_TIMEOUT_SECONDS + 10)
        assert down_result.returncode == 0, (
            f"docker compose down failed:\nstdout={down_result.stdout}\nstderr={down_result.stderr}"
        )


def _wait_for_terminal_state(analysis_id: str, timeout: float) -> None:
    """`JOB-01` (`WP-075`): the real deployed backend now runs every
    analysis on a background worker too — `POST /demo/sales` returns
    `queued` immediately, so the persisted-and-restart-surviving state
    this test proves must be captured only after the analysis actually
    reaches a terminal state, not the creation response itself.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = httpx.get(f"{BACKEND_URL}/api/v1/analyses/{analysis_id}/status", timeout=5)
        assert status.status_code == 200
        if status.json()["state"] in {"completed", "failed", "cancelled"}:
            return
        time.sleep(0.5)
    raise AssertionError(f"analysis {analysis_id} did not reach a terminal state within {timeout}s")


def test_analysis_survives_backend_container_restart(compose_stack: None) -> None:
    created = httpx.post(f"{BACKEND_URL}/api/v1/demo/sales", timeout=30)
    assert created.status_code == 202
    analysis_id = created.json()["analysis"]["analysis_id"]
    _wait_for_terminal_state(analysis_id, READY_POLL_TIMEOUT_SECONDS)

    before = httpx.get(f"{BACKEND_URL}/api/v1/analyses/{analysis_id}", timeout=5)
    assert before.status_code == 200

    restart_result = _run_compose("restart", "backend", timeout=RESTART_TIMEOUT_SECONDS)
    assert restart_result.returncode == 0, (
        f"docker compose restart failed:\nstdout={restart_result.stdout}\nstderr={restart_result.stderr}"
    )

    _wait_until_ready(READY_POLL_TIMEOUT_SECONDS)

    ready = httpx.get(f"{BACKEND_URL}/api/v1/health/ready", timeout=5)
    assert ready.status_code == 200
    storage_check = next(c for c in ready.json()["checks"] if c["name"] == "storage")
    assert storage_check == {"name": "storage", "status": "ok", "detail": None}

    after = httpx.get(f"{BACKEND_URL}/api/v1/analyses/{analysis_id}", timeout=5)
    assert after.status_code == 200
    assert after.json() == before.json()
