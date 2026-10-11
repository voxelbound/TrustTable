"""Product-managed settings: the allowlist and the precedence rule (`UX-08a`).

`docs/decision-log.md` D-066 item 5 (owner-confirmed): for a user-manageable
product setting the effective value is an *explicit deployment override*, then a
*stored* user setting, then the built-in default. This module is the one place
that rule lives; it is pure (no I/O) so it can be tested on its own.

- **The allowlist is closed.** Exactly one key exists, `ai_assistance` (whether
  AI explanations may be requested). It is a boolean. Anything else (an unknown
  key, a value of another type) is rejected, not stored. Deployment
  configuration, security and resource limits, paths, URLs and secrets are never
  product-managed. There is deliberately no generic key and value surface.
- **An override is explicit, never inferred.** `LLM_PROVIDER` is an override only
  when the operator configured it (in the process environment or the `.env`
  file), which `pydantic-settings` records in `model_fields_set`. A value is
  never compared with its default to decide this, so a container or packaging
  default cannot make the setting read-only.
- **A stored value never exceeds an override.** With an override the stored value
  is ignored and the setting is read-only; the product never edits `.env`.
- **What "on" means without an override.** The only real provider is the local
  `llama_cpp` runtime, so a stored "on" selects it, but only when the installation
  has configured a model (`LLM_MODEL`) **and** the configured address names this
  machine (the same conservative test that classifies a model location as
  `local`: loopback, `localhost` or `host.docker.internal`). The product contract
  is local-first inference (`docs/product-requirements.md`: "AI is optional and
  local by default"; D-007 and D-066 item 10: network egress needs explicit
  consent), so an in-product switch never activates an address that is not this
  machine. Such a stored "on" is reported honestly as on-but-unavailable, with the
  reason, and no AI call is made. Using a non-local runtime remains an explicit
  operator decision: set `LLM_PROVIDER` (an override). Guided setup is `UX-09`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

from .ai_provider.location import model_location_for
from .config import Settings
from .domain.ai_enrichment import EnrichmentModelLocation

AI_ASSISTANCE_KEY: Final[str] = "ai_assistance"

#: The closed allowlist: key -> the type its value must have.
ALLOWED_SETTINGS: Final[dict[str, type]] = {AI_ASSISTANCE_KEY: bool}

#: The provider a stored "on" selects (the only real one).
STORED_ON_PROVIDER: Final[str] = "llama_cpp"

SettingSource = Literal["deployment", "stored", "default"]


class UnknownSettingError(Exception):
    """The key is not on the allowlist."""


class InvalidSettingValueError(Exception):
    """The value is not of the type the allowlisted key requires."""


def validate_setting(key: str, value: object) -> object:
    """Return `value` if `key` is allowlisted and `value` has exactly its type."""
    expected = ALLOWED_SETTINGS.get(key)
    if expected is None:
        raise UnknownSettingError(key)
    # `bool` is a subclass of `int`, so compare types exactly: 1 and "true" are
    # not booleans.
    if type(value) is not expected:
        raise InvalidSettingValueError(key)
    return value


def is_deployment_override(settings: Settings) -> bool:
    """Whether the operator explicitly configured `LLM_PROVIDER`.

    `model_fields_set` holds exactly the fields that came from the environment,
    the `.env` file or an explicit argument; a field that merely has its default
    is not in it. The value is never compared with the default.
    """
    return "llm_provider" in settings.model_fields_set


@dataclass(frozen=True, slots=True)
class AiAssistanceResolution:
    """The effective AI-assistance setting and the settings consumers must use."""

    #: Whether AI assistance is on (the effective intent).
    enabled: bool
    source: SettingSource
    #: True when an explicit deployment override makes the setting read-only.
    managed: bool
    #: False only for a stored "on" that cannot run: on, but no usable runtime.
    runtime_configured: bool
    #: What every AI consumer must use instead of the raw deployment settings.
    settings: Settings
    #: Why a stored "on" cannot run: `no_runtime` (no model configured) or
    #: `not_local` (the configured address is not this machine). None otherwise.
    unavailable_reason: Literal["no_runtime", "not_local"] | None = None


def resolve_ai_assistance(settings: Settings, stored: bool | None) -> AiAssistanceResolution:
    """Apply explicit override, then stored value, then default (off)."""
    if is_deployment_override(settings):
        return AiAssistanceResolution(
            enabled=settings.llm_provider != "disabled",
            source="deployment",
            managed=True,
            runtime_configured=True,
            settings=settings,
        )
    if stored is None:
        return AiAssistanceResolution(
            enabled=False,
            source="default",
            managed=False,
            runtime_configured=True,
            settings=settings,
        )
    if not stored:
        return AiAssistanceResolution(
            enabled=False,
            source="stored",
            managed=False,
            runtime_configured=True,
            settings=settings,
        )
    if not settings.llm_model.strip():
        # On, but nothing to run: consumers see AI as disabled and make no call.
        return AiAssistanceResolution(
            enabled=True,
            source="stored",
            managed=False,
            runtime_configured=False,
            settings=settings,
            unavailable_reason="no_runtime",
        )
    if model_location_for(STORED_ON_PROVIDER, settings.llm_base_url) is not (
        EnrichmentModelLocation.LOCAL
    ):
        # The in-product switch never activates an address that is not this machine
        # (local-first inference; egress needs an explicit operator decision).
        return AiAssistanceResolution(
            enabled=True,
            source="stored",
            managed=False,
            runtime_configured=False,
            settings=settings,
            unavailable_reason="not_local",
        )
    return AiAssistanceResolution(
        enabled=True,
        source="stored",
        managed=False,
        runtime_configured=True,
        settings=settings.model_copy(update={"llm_provider": STORED_ON_PROVIDER}),
    )
