"""Read-only accessors backing `GET /api/v1/version`.

`environment_mode` is sourced from the typed `Settings` system (FND-02),
superseding WP-001's temporary single raw environment-variable read. An
unrecognized `APP_ENV` value now fails application startup (see
`main.create_app`) instead of silently falling back to a default.
"""

from __future__ import annotations

import os
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as read_installed_version
from typing import Final

from trusttable_backend.config import get_settings
from trusttable_backend.schemas.version import EnvironmentMode

_DISTRIBUTION_NAME: Final = "trusttable-backend"
_API_VERSION: Final = "v1"


def get_application_version() -> str:
    """Return the backend package version from `pyproject.toml`.

    The package version is the single source of truth. Falls back to a
    sentinel only if the package metadata is unavailable (e.g. running
    from source without an installed/editable distribution record).
    """
    try:
        return read_installed_version(_DISTRIBUTION_NAME)
    except PackageNotFoundError:
        return "0.0.0-unknown"


def get_api_version() -> str:
    """Return the API version constant matching the `/api/v1` prefix."""
    return _API_VERSION


def get_build_commit() -> str | None:
    """Return the build commit if injected at build time, else `None`.

    Expected to be `None` in local `uv run` execution; a Docker build can
    inject it via a build arg (e.g. `git rev-parse --short HEAD`).
    """
    return os.environ.get("BUILD_COMMIT") or None


def get_environment_mode() -> EnvironmentMode:
    """Return the current environment mode from typed `Settings`.

    `Settings.app_env` and `schemas.version.EnvironmentMode` are the same
    three-value literal; an invalid value cannot reach here because
    `Settings()` would already have raised at application startup.
    """
    return get_settings().app_env
