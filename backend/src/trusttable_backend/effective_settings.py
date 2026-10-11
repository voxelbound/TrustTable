"""The effective AI settings every AI consumer must use (`UX-08a`).

`resolve_current_ai` reads the stored value fresh on every call, so a change made
through the Settings API takes effect on the next request without a restart. It
fails closed: if the stored value cannot be read or is not a boolean, it is
treated as "not stored", which means AI assistance stays off unless an explicit
deployment override turns it on.
"""

from __future__ import annotations

from fastapi import Request

from .config import Settings, get_settings
from .persistence.settings_store import SqlSettingsStore
from .product_settings import AI_ASSISTANCE_KEY, AiAssistanceResolution, resolve_ai_assistance


def read_stored_ai_assistance(store: SqlSettingsStore) -> bool | None:
    """The stored AI-assistance value, or None when none is stored or readable."""
    try:
        value = store.get(AI_ASSISTANCE_KEY).value
    except Exception:  # noqa: BLE001 - fail closed; never raise into an AI consumer
        # Nothing is logged: the repository allows exactly one logging call site
        # (`tests/security/test_log_safety.py`).
        return None
    return value if isinstance(value, bool) else None


def resolve_current_ai(
    store: SqlSettingsStore, settings: Settings | None = None
) -> AiAssistanceResolution:
    """The effective AI-assistance resolution for the deployment's settings."""
    return resolve_ai_assistance(
        settings if settings is not None else get_settings(), read_stored_ai_assistance(store)
    )


def resolve_for_request(request: Request) -> AiAssistanceResolution:
    """`resolve_current_ai` for the app that is serving `request`."""
    store: SqlSettingsStore = request.app.state.settings_store
    return resolve_current_ai(store)
