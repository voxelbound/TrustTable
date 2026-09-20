"""Docker Compose pull-only file integration test (`REL-02`).

`docker-compose.release.yml` runs a published release from container images
without building anything. No image is published yet, so this test stands in
for the registry: it builds both images locally under the exact names the
release workflow publishes, then starts the pull-only file with pulling
disabled (`--pull never`). If the file could build, or needed a registry, it
could not start here.

It proves the pull-only file starts a working stack (frontend served, API
proxied through Nginx, backend healthy) and that it fails closed when the
version is missing or the images are absent. It does not, and cannot, prove
that a real GHCR publish or an anonymous pull works; that is verified by the
release workflow's own verification job and by the fresh-host run.

The stack is started from a byte-identical copy of the compose file in a
temporary directory. Compose resolves `env_file: .env` next to the compose
file, so this guarantees the stack runs on `Settings`' own defaults whatever
the developer's own repository-root `.env` contains, without touching it.

Requires a reachable Docker daemon and buildable `backend`/`frontend` images.
Not part of the default backend unit-test suite; invoke explicitly, e.g.:

    uv run --project backend pytest tests/integration -v
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
RELEASE_COMPOSE_SOURCE = REPO_ROOT / "docker-compose.release.yml"
PROJECT_NAME = "trusttable-release-file-test"
BACKEND_URL = "http://127.0.0.1:8000"
FRONTEND_URL = "http://127.0.0.1:8080"
TEST_VERSION = "0.0.0-ci"
ABSENT_VERSION = "0.0.0-absent"
IMAGES = {
    "backend": "ghcr.io/voxelbound/trusttable-backend",
    "frontend": "ghcr.io/voxelbound/trusttable-frontend",
}
BUILD_TIMEOUT_SECONDS = 600
UP_TIMEOUT_SECONDS = 120
ERROR_LOG_PATTERN = re.compile(r"ERROR:|\[error\]|Traceback \(most recent call last\)")


def _compose(
    compose_file: Path, *args: str, version: str | None, timeout: int
) -> subprocess.CompletedProcess[str]:
    env = {key: value for key, value in os.environ.items() if key != "TRUSTTABLE_VERSION"}
    if version is not None:
        env["TRUSTTABLE_VERSION"] = version
    return subprocess.run(
        ["docker", "compose", "-p", PROJECT_NAME, "-f", str(compose_file), *args],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        env=env,
    )


def _docker(*args: str, timeout: int) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *args], capture_output=True, text=True, timeout=timeout, check=False
    )


@pytest.fixture(scope="module")
def compose_file(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A byte-identical copy of the pull-only file in a directory with no `.env`."""
    directory = tmp_path_factory.mktemp("release-compose")
    copy = directory / RELEASE_COMPOSE_SOURCE.name
    shutil.copyfile(RELEASE_COMPOSE_SOURCE, copy)
    assert copy.read_bytes() == RELEASE_COMPOSE_SOURCE.read_bytes()
    assert not (directory / ".env").exists()
    return copy


@pytest.fixture(scope="module")
def locally_built_release_images() -> Iterator[None]:
    """Build both images under the published names, as the release workflow would."""
    for name, image in IMAGES.items():
        result = _docker(
            "build",
            "-t",
            f"{image}:{TEST_VERSION}",
            str(REPO_ROOT / name),
            timeout=BUILD_TIMEOUT_SECONDS,
        )
        assert result.returncode == 0, (
            f"docker build of {name} failed:\nstdout={result.stdout}\nstderr={result.stderr}"
        )
    try:
        yield
    finally:
        for image in IMAGES.values():
            _docker("rmi", "--force", f"{image}:{TEST_VERSION}", timeout=60)


@pytest.fixture(scope="module")
def pull_only_stack(compose_file: Path, locally_built_release_images: None) -> Iterator[str]:
    up = _compose(
        compose_file,
        "up",
        "-d",
        "--wait",
        "--wait-timeout",
        str(UP_TIMEOUT_SECONDS),
        "--pull",
        "never",
        version=TEST_VERSION,
        timeout=UP_TIMEOUT_SECONDS + 30,
    )
    assert up.returncode == 0, f"pull-only up failed:\nstdout={up.stdout}\nstderr={up.stderr}"
    logs = _compose(compose_file, "logs", "--no-color", version=TEST_VERSION, timeout=30).stdout
    try:
        yield logs
    finally:
        down = _compose(compose_file, "down", "--volumes", version=TEST_VERSION, timeout=60)
        assert down.returncode == 0, f"pull-only down failed:\n{down.stdout}\n{down.stderr}"


def test_the_pull_only_stack_starts_from_local_images_without_building(
    compose_file: Path, pull_only_stack: str
) -> None:
    ps = _compose(compose_file, "ps", "--format", "json", version=TEST_VERSION, timeout=30)
    assert ps.returncode == 0
    # Two services, both healthy: `up --wait` already required it; this pins the count.
    assert ps.stdout.count('"Service"') == 2
    assert not ERROR_LOG_PATTERN.search(pull_only_stack), pull_only_stack


def test_the_backend_is_healthy_and_reports_its_version(pull_only_stack: str) -> None:
    ready = httpx.get(f"{BACKEND_URL}/api/v1/health/ready", timeout=10)
    assert ready.status_code == 200
    version = httpx.get(f"{BACKEND_URL}/api/v1/version", timeout=10)
    assert version.status_code == 200
    assert version.json()["api_version"] == "v1"


def test_the_frontend_is_served_and_proxies_the_api(pull_only_stack: str) -> None:
    page = httpx.get(f"{FRONTEND_URL}/", timeout=10)
    assert page.status_code == 200
    assert 'id="root"' in page.text  # the SPA shell, served by Nginx from the frontend image
    proxied = httpx.get(f"{FRONTEND_URL}/api/v1/version", timeout=10)
    assert proxied.status_code == 200
    assert proxied.json()["api_version"] == "v1"


def test_a_missing_version_is_refused_with_the_variable_named(compose_file: Path) -> None:
    result = _compose(compose_file, "config", version=None, timeout=30)
    assert result.returncode != 0
    assert "TRUSTTABLE_VERSION" in result.stderr


def test_absent_images_are_never_built_or_substituted(compose_file: Path) -> None:
    """With pulling disabled and the images absent, `up` must fail, not fall back to building."""
    for image in IMAGES.values():
        assert _docker("image", "inspect", f"{image}:{ABSENT_VERSION}", timeout=30).returncode != 0
    result = _compose(
        compose_file, "up", "-d", "--pull", "never", version=ABSENT_VERSION, timeout=120
    )
    assert result.returncode != 0, result.stdout
    for image in IMAGES.values():
        # Nothing was built under the absent tag.
        assert _docker("image", "inspect", f"{image}:{ABSENT_VERSION}", timeout=30).returncode != 0
    _compose(compose_file, "down", "--volumes", version=ABSENT_VERSION, timeout=60)
