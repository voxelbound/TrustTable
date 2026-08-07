"""Read-only accessors backing `GET /api/v1/version`.

Deliberately minimal per WP-001 Non-goals: `environment_mode` is a single
raw environment-variable read, explicitly not the typed configuration
system that `FND-02` introduces later.
"""

from __future__ import annotations

import os
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as read_installed_version
from typing import Final, get_args

from trusttable_backend.schemas.version import EnvironmentMode

_DISTRIBUTION_NAME: Final = "trusttable-backend"
_API_VERSION: Final = "v1"
_DEFAULT_ENVIRONMENT_MODE: Final[EnvironmentMode] = "development"
_VALID_ENVIRONMENT_MODES: Final = frozenset(get_args(EnvironmentMode))


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
    """Return the current environment mode from a single raw env-var read."""
    raw_value = os.environ.get("APP_ENV", _DEFAULT_ENVIRONMENT_MODE)
    if raw_value in _VALID_ENVIRONMENT_MODES:
        return raw_value  # type: ignore[return-value]  # narrowed by membership check
    return _DEFAULT_ENVIRONMENT_MODE
