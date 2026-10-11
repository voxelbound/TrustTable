"""Product settings routes (`UX-08a`, `docs/decision-log.md` D-066 item 5).

`GET /settings` reads the effective settings with their source; `PUT` and
`DELETE /settings/{key}` write an allowlisted key and reset it (remove the stored
value) with an optimistic version check; `GET /settings/advanced` is the one
response that carries the effective runtime and model configuration.

Rules enforced here and nowhere else in the API:

- the allowlist is closed: an unknown key is `404`, a value of the wrong type is
  `422`, and the body may carry nothing else;
- an explicit deployment override makes the setting read-only (`409`), and the
  product never edits deployment configuration;
- a stale `expected_version` changes nothing (`409`);
- writes need a JSON body (or an explicit query parameter for reset) and a
  non-simple HTTP method, so a page on another origin cannot send them without a
  CORS preflight, which this API never grants.

Every response is `Cache-Control: no-store`.
"""

from __future__ import annotations

from typing import Annotated
from urllib.parse import urlsplit

from fastapi import APIRouter, Query, Request, Response

from trusttable_backend.effective_settings import resolve_for_request
from trusttable_backend.errors import AppError
from trusttable_backend.persistence.settings_store import (
    SettingsVersionConflictError,
    SqlSettingsStore,
)
from trusttable_backend.product_settings import (
    AI_ASSISTANCE_KEY,
    ALLOWED_SETTINGS,
    AiAssistanceResolution,
    UnknownSettingError,
)
from trusttable_backend.schemas.settings import (
    AdvancedSettingsResponse,
    SettingItemResponse,
    SettingsResponse,
    SettingWriteRequest,
)

router = APIRouter(tags=["settings"])

_MANAGED_NOTE = (
    "This is set by your installation, so it cannot be changed here. To manage it in "
    "TrustTable, remove the LLM_PROVIDER line from your installation's configuration "
    "(for example from a copied .env file) and restart. TrustTable never edits that "
    "configuration itself."
)
_NO_RUNTIME_NOTE = (
    "AI assistance is on, but no local AI runtime is set up on this installation yet, so "
    "nothing is sent to a model."
)


_NOT_LOCAL_NOTE = (
    "AI assistance is on, but the AI runtime this installation points to is not on this "
    "machine. This switch only uses a runtime on this machine, so nothing is sent to a model. "
    "Sending to another address is an installation decision: set LLM_PROVIDER in your "
    "installation's configuration."
)


def _store(request: Request) -> SqlSettingsStore:
    store: SqlSettingsStore = request.app.state.settings_store
    return store


def _item(resolution: AiAssistanceResolution, version: int) -> SettingItemResponse:
    note: str | None = None
    if resolution.managed:
        note = _MANAGED_NOTE
    elif resolution.enabled and not resolution.runtime_configured:
        note = _NOT_LOCAL_NOTE if resolution.unavailable_reason == "not_local" else _NO_RUNTIME_NOTE
    return SettingItemResponse(
        key="ai_assistance",
        value=resolution.enabled,
        source=resolution.source,
        managed_by_installation=resolution.managed,
        version=version,
        note=note,
    )


def _current_version(store: SqlSettingsStore) -> int:
    try:
        return store.get(AI_ASSISTANCE_KEY).version
    except Exception:  # noqa: BLE001 - an unreadable store reports version 0, never raises
        return 0


def _unknown_key(key: str) -> AppError:
    # The key is caller-supplied and not on the allowlist: it is not echoed back.
    del key
    return AppError(
        "SETTING_NOT_FOUND",
        "That setting does not exist.",
        status_code=404,
    )


def _check_writable(request: Request, key: str) -> None:
    if key not in ALLOWED_SETTINGS:
        raise _unknown_key(key)
    if resolve_for_request(request).managed:
        raise AppError(
            "SETTING_MANAGED_BY_INSTALLATION",
            _MANAGED_NOTE,
            status_code=409,
            details={"key": key},
        )


def _conflict(error: SettingsVersionConflictError) -> AppError:
    return AppError(
        "SETTING_VERSION_CONFLICT",
        "This setting was changed by someone else. Reload it and try again.",
        status_code=409,
        details={"key": error.key, "current_version": error.actual_version},
    )


@router.get("/settings", response_model=SettingsResponse)
def get_settings_route(request: Request, response: Response) -> SettingsResponse:
    """The effective product settings, each with where its value comes from."""
    response.headers["Cache-Control"] = "no-store"
    resolution = resolve_for_request(request)
    return SettingsResponse(settings=[_item(resolution, _current_version(_store(request)))])


def _safe_address(base_url: str) -> str | None:
    """Scheme, host and port only: never a user name, password, path or query."""
    try:
        parts = urlsplit(base_url)
        host = parts.hostname
        port = parts.port
    except ValueError:
        return None
    if not parts.scheme or not host:
        return None
    shown_host = f"[{host}]" if ":" in host else host
    return f"{parts.scheme}://{shown_host}" + (f":{port}" if port is not None else "")


@router.get("/settings/advanced", response_model=AdvancedSettingsResponse)
def get_advanced_settings(request: Request, response: Response) -> AdvancedSettingsResponse:
    """The effective AI runtime and model configuration (the Advanced exception)."""
    response.headers["Cache-Control"] = "no-store"
    resolution = resolve_for_request(request)
    effective = resolution.settings
    configured = effective.llm_provider != "disabled"
    return AdvancedSettingsResponse(
        ai_provider=effective.llm_provider,
        ai_assistance_source=resolution.source,
        runtime_address=_safe_address(effective.llm_base_url) if configured else None,
        model_identifier=(effective.llm_model or None) if configured else None,
        timeout_seconds=effective.llm_timeout_seconds,
        context_window=effective.llm_context_window,
        sample_values_sent=effective.llm_send_sample_values,
        max_sample_values=effective.llm_max_sample_values,
    )


@router.put("/settings/{key}", response_model=SettingItemResponse)
def put_setting(
    key: str, body: SettingWriteRequest, request: Request, response: Response
) -> SettingItemResponse:
    """Store an allowlisted setting. `409` if the installation manages it or the
    quoted version is stale; nothing is changed in either case."""
    response.headers["Cache-Control"] = "no-store"
    _check_writable(request, key)
    store = _store(request)
    try:
        stored = store.put(key, body.value, expected_version=body.expected_version)
    except SettingsVersionConflictError as error:
        raise _conflict(error) from None
    except UnknownSettingError:
        raise _unknown_key(key) from None
    return _item(resolve_for_request(request), stored.version)


@router.delete("/settings/{key}", response_model=SettingItemResponse)
def reset_setting(
    key: str,
    request: Request,
    response: Response,
    expected_version: Annotated[int, Query(ge=0, le=2**31 - 1)],
) -> SettingItemResponse:
    """Reset a setting: remove the stored value so the default applies again."""
    response.headers["Cache-Control"] = "no-store"
    _check_writable(request, key)
    store = _store(request)
    try:
        stored = store.reset(key, expected_version=expected_version)
    except SettingsVersionConflictError as error:
        raise _conflict(error) from None
    except UnknownSettingError:
        raise _unknown_key(key) from None
    return _item(resolve_for_request(request), stored.version)
