"""The honest, bounded Local AI status behind `GET /ai/status` (`UX-02`, D-068).

Derived from the deployment configuration and, when a runtime is configured,
one short liveness probe. It never makes a completion call, never sends dataset
content, and never returns a base URL, host, port, path, exception text or the
provider's own `detail` string. Labels come from `ai_provider.display`, which
bounds and sanitizes operator-supplied values. Guided setup and connection
testing are `UX-09`; this module neither starts nor manages a runtime.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Final, Literal

from .ai_provider.contract import AIProvider
from .ai_provider.display import describe_provenance
from .ai_provider.factory import create_provider
from .ai_provider.location import model_location_for
from .config import Settings
from .domain.ai_enrichment import EnrichmentModelLocation

#: The probe never waits longer than this, whatever `LLM_TIMEOUT_SECONDS` is.
MAX_PROBE_SECONDS: Final[float] = 3.0

AssistanceState = Literal["off", "on"]
ReadyState = Literal["disabled", "ready", "unavailable"]
LocationState = Literal["none", "local", "unknown"]

_ASSISTANCE_NOTE: Final[str] = (
    "AI only adds optional explanations; the built-in checks decide the findings and the "
    "trust assessment."
)


@dataclass(frozen=True, slots=True)
class AiStatus:
    assistance: AssistanceState
    state: ReadyState
    location: LocationState
    provider_label: str
    runtime_label: str | None
    model_label: str | None
    sample_values_sent: bool
    summary: str


ProviderFactory = Callable[..., AIProvider]


def _summary(
    state: ReadyState, location: LocationState, runtime_label: str | None, sample_values: bool
) -> str:
    if state == "disabled":
        return (
            "AI assistance is off. TrustTable finds and scores issues with its built-in "
            "checks only, and no dataset content is sent to any model."
        )
    sent = (
        "When you ask for an AI explanation of a finding, bounded evidence about that "
        "finding is sent to the model. Sample values from your data "
        + ("may also be included." if sample_values else "are not included.")
    )
    runtime = runtime_label or "model"
    if state == "unavailable":
        return (
            f"AI assistance is turned on, but the {runtime} runtime is not reachable right "
            "now. Everything else works with the built-in checks alone. " + _ASSISTANCE_NOTE
        )
    where = (
        "on this machine"
        if location == "local"
        else "but TrustTable cannot confirm that it runs on this machine"
    )
    ready = f"AI assistance is on and the {runtime} runtime is ready, {where}."
    return f"{ready} {sent} {_ASSISTANCE_NOTE}"


def compute_ai_status(
    settings: Settings, *, provider_factory: ProviderFactory = create_provider
) -> AiStatus:
    """Build the status for `settings`, probing the runtime at most once."""
    name = settings.llm_provider
    if name == "disabled":
        return AiStatus(
            assistance="off",
            state="disabled",
            location="none",
            provider_label="AI assistance",
            runtime_label=None,
            model_label=None,
            sample_values_sent=False,
            summary=_summary("disabled", "none", None, False),
        )

    display = describe_provenance(name, settings.llm_model)
    location: LocationState = (
        "local"
        if model_location_for(name, settings.llm_base_url) is EnrichmentModelLocation.LOCAL
        else "unknown"
    )
    state: ReadyState = "unavailable"
    try:
        provider = provider_factory(
            name,
            base_url=settings.llm_base_url,
            model_identifier=settings.llm_model,
            timeout_seconds=min(float(settings.llm_timeout_seconds), MAX_PROBE_SECONDS),
            temperature=settings.llm_temperature,
        )
        if provider.health_check().available:
            state = "ready"
    except Exception:  # noqa: BLE001 - the status route must never raise or leak detail
        state = "unavailable"

    sample_values = settings.llm_send_sample_values
    return AiStatus(
        assistance="on",
        state=state,
        location=location,
        provider_label=display.deployment_label,
        runtime_label=display.runtime_label,
        model_label=display.model_label,
        sample_values_sent=sample_values,
        summary=_summary(state, location, display.runtime_label, sample_values),
    )
