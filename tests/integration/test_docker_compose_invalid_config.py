"""Docker-level invalid-configuration startup test (WP-002 FND-02 AC-07).

Proves that a supplied `.env` override reaching `docker-compose.yml`'s
optional `env_file` exercises the same typed `Settings` validation as
native startup: an invalid value stops the backend container from
becoming healthy, exactly as an invalid native `uv run` startup fails
(`backend/tests/config/test_settings.py::test_invalid_app_env_fails_create_app`).

Kept in its own module, independent of `test_docker_compose_smoke.py`'s
module-scoped `compose_stack` fixture, so the two never run the same
Docker Compose project concurrently. Requires a reachable Docker daemon
(unsandboxed socket access); not part of the default backend unit-test
suite — see `docs/local-development.md`.

WP-026 (REL-01) note: `docker-compose.yml` now sets `restart:
unless-stopped` on both services. A container crashing on invalid
configuration is therefore restarted by Docker rather than left
permanently `exited`, so at the moment this test polls container state
it may observe either `"exited"` (between restart attempts) or
`"restarting"` (mid-attempt) — both are legitimate, timing-dependent
snapshots of the same underlying failure, not a behavior change in the
invariant itself. The real invariant this test proves — an invalid
environment override must never allow the backend to become healthy —
is asserted directly and timing-independently via the container's
`Health` field, in addition to the (now State-tolerant) exit-code check.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPOSE_FILE = REPO_ROOT / "docker-compose.yml"
ENV_FILE_PATH = REPO_ROOT / ".env"
BUILD_TIMEOUT_SECONDS = 180
UP_WAIT_TIMEOUT_SECONDS = 30
DOWN_TIMEOUT_SECONDS = 30


def _run_compose(*args: str, timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE_FILE), *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )


@pytest.fixture
def invalid_env_file() -> Iterator[Path]:
    """Write a repository-root `.env` with one invalid value, then remove it.

    Skips rather than overwrites if a real `.env` already exists on this
    machine — this test must never destroy a developer's own file.
    """
    if ENV_FILE_PATH.exists():
        pytest.skip(
            f"{ENV_FILE_PATH} already exists; refusing to overwrite a real "
            "developer .env file for this test"
        )

    ENV_FILE_PATH.write_text("MAX_ROWS=not-a-number\n", encoding="utf-8")
    try:
        yield ENV_FILE_PATH
    finally:
        down_result = _run_compose("down", timeout=DOWN_TIMEOUT_SECONDS + 10)
        assert down_result.returncode == 0, (
            f"docker compose down failed:\nstdout={down_result.stdout}\nstderr={down_result.stderr}"
        )
        ENV_FILE_PATH.unlink(missing_ok=True)


def test_invalid_env_override_prevents_backend_from_becoming_healthy(
    invalid_env_file: Path,
) -> None:
    # Compose does not rebuild an already-built image on `up` by default;
    # build explicitly so this exercises current source (see the matching
    # note in test_docker_compose_smoke.py's `compose_stack` fixture).
    build_result = _run_compose("build", "backend", timeout=BUILD_TIMEOUT_SECONDS)
    assert build_result.returncode == 0, (
        f"docker compose build failed:\nstdout={build_result.stdout}\nstderr={build_result.stderr}"
    )

    up_result = _run_compose(
        "up",
        "-d",
        "--no-deps",
        "backend",
        "--wait",
        "--wait-timeout",
        str(UP_WAIT_TIMEOUT_SECONDS),
        timeout=UP_WAIT_TIMEOUT_SECONDS + 10,
    )

    assert up_result.returncode != 0, (
        "docker compose up unexpectedly succeeded with an invalid MAX_ROWS "
        f"override:\nstdout={up_result.stdout}\nstderr={up_result.stderr}"
    )

    ps_result = _run_compose("ps", "-a", "--format", "json", "backend", timeout=15)
    assert ps_result.returncode == 0
    backend_state = json.loads(ps_result.stdout.splitlines()[0])

    # With `restart: unless-stopped` (REL-01), Docker restarts a crashing
    # container rather than leaving it permanently exited, so either state
    # is a legitimate snapshot of the same underlying failure depending on
    # exactly when the restart loop is polled.
    assert backend_state["State"] in {"exited", "restarting"}, (
        f"expected the backend container to have exited or be restarting "
        f"after a crash, got: {backend_state}"
    )
    assert backend_state["ExitCode"] != 0, (
        f"expected a non-zero exit code from invalid configuration, got: {backend_state}"
    )
    # Direct, timing-independent proof of the real invariant: an invalid
    # environment override must never allow the backend to become healthy,
    # regardless of which point in the restart loop this happened to catch.
    assert backend_state.get("Health") != "healthy", (
        f"backend must never report healthy with an invalid configuration, got: {backend_state}"
    )
