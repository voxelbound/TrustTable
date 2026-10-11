"""Local AI readiness and the bounded connection test (`UX-09`, D-066 item 10).

Both are read-only views of the *effective* AI-assistance setting. They never
download, install, start or configure anything, never make a completion call, never
send dataset content, and never accept a target from the caller: the only thing that
can ever be contacted is the runtime this installation is already configured to use,
and only when it is on this machine. Neither returns a base URL, host, port, path,
exception text or the provider's own `detail`; every sentence here is fixed text.

The contract is deliberately abstract: it says what is configured and whether the
configured runtime answers, not where or how a runtime is run, so the unapproved
product-managed design (`LAI-01`) is not decided implicitly.
"""

from __future__ import annotations

import math
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Final, Literal

from .ai_provider.factory import create_provider
from .ai_provider.location import model_location_for
from .ai_status import AiStatus, ProviderFactory, probe_runtime
from .config import Settings
from .domain.ai_enrichment import EnrichmentModelLocation
from .product_settings import AiAssistanceResolution

#: A second test is refused until this many seconds after the previous one finished.
MIN_TEST_INTERVAL_SECONDS: Final[int] = 5

CheckKey = Literal[
    "assistance_on",
    "runtime_configured",
    "runtime_on_this_machine",
    "runtime_answers",
    "model_named",
]
CheckState = Literal["done", "todo", "attention", "not_checked"]
TestOutcome = Literal[
    "reachable",
    "not_reachable",
    "assistance_off",
    "no_runtime",
    "not_local",
    "busy",
    "too_soon",
]


@dataclass(frozen=True, slots=True)
class ReadinessCheck:
    key: CheckKey
    title: str
    state: CheckState
    detail: str


@dataclass(frozen=True, slots=True)
class Readiness:
    ready: bool
    model_label: str | None
    runtime_label: str | None
    checks: tuple[ReadinessCheck, ...]


@dataclass(frozen=True, slots=True)
class ConnectionTestResult:
    outcome: TestOutcome
    tested: bool
    message: str
    retry_after_seconds: int | None = None


_CHECK_TITLES: Final[dict[CheckKey, str]] = {
    "assistance_on": "AI assistance is on",
    "runtime_configured": "This installation names an AI runtime",
    "runtime_on_this_machine": "The runtime is on this machine",
    "runtime_answers": "The runtime answers",
    "model_named": "A model is named",
}

_WAITING: Final[str] = "Not checked yet: an earlier step is not complete."


def _check(key: CheckKey, state: CheckState, detail: str) -> ReadinessCheck:
    return ReadinessCheck(key=key, title=_CHECK_TITLES[key], state=state, detail=detail)


def compute_readiness(resolution: AiAssistanceResolution, status: AiStatus) -> Readiness:
    """Readiness checklist from the effective resolution and one already-made status.

    `status` comes from `compute_ai_status`, which makes the single bounded probe, so
    the checklist and the status line can never disagree and no second probe is made.
    """
    checks: list[ReadinessCheck] = []

    if resolution.enabled:
        checks.append(_check("assistance_on", "done", "AI assistance is on."))
    elif resolution.managed:
        checks.append(
            _check(
                "assistance_on",
                "todo",
                "AI assistance is off, and your installation manages that setting. "
                "Whoever looks after this installation can turn it on.",
            )
        )
    else:
        checks.append(
            _check("assistance_on", "todo", "AI assistance is off. You can turn it on in Settings.")
        )

    if not resolution.enabled:
        checks.append(_check("runtime_configured", "not_checked", _WAITING))
        checks.append(_check("runtime_on_this_machine", "not_checked", _WAITING))
        checks.append(_check("runtime_answers", "not_checked", _WAITING))
        checks.append(_check("model_named", "not_checked", _WAITING))
        return Readiness(ready=False, model_label=None, runtime_label=None, checks=tuple(checks))

    if resolution.unavailable_reason != "not_local" and (
        resolution.unavailable_reason == "no_runtime" or status.location == "none"
    ):
        checks.append(
            _check(
                "runtime_configured",
                "todo",
                "No AI runtime is set up on this installation. TrustTable does not install "
                "or start one; it is set up outside TrustTable.",
            )
        )
        for key in ("runtime_on_this_machine", "runtime_answers"):
            checks.append(_check(key, "not_checked", _WAITING))
        checks.append(_check("model_named", "not_checked", _WAITING))
        return Readiness(ready=False, model_label=None, runtime_label=None, checks=tuple(checks))

    checks.append(_check("runtime_configured", "done", "This installation names an AI runtime."))

    if resolution.unavailable_reason == "not_local":
        checks.append(
            _check(
                "runtime_on_this_machine",
                "todo",
                "The runtime this installation names is not on this machine. The in-product "
                "switch only uses a runtime on this machine, so nothing is sent to it.",
            )
        )
        checks.append(_check("runtime_answers", "not_checked", _WAITING))
        checks.append(_check("model_named", "not_checked", _WAITING))
        return Readiness(ready=False, model_label=None, runtime_label=None, checks=tuple(checks))

    if status.location == "local":
        checks.append(_check("runtime_on_this_machine", "done", "The runtime is on this machine."))
    else:
        checks.append(
            _check(
                "runtime_on_this_machine",
                "attention",
                "TrustTable cannot confirm that the runtime is on this machine.",
            )
        )

    if status.state == "ready":
        checks.append(_check("runtime_answers", "done", "The runtime answered a short check."))
    else:
        checks.append(
            _check(
                "runtime_answers",
                "todo",
                "The runtime did not answer a short check. Make sure it is running, then test "
                "the connection again.",
            )
        )

    if status.model_label:
        checks.append(_check("model_named", "done", "A model is named."))
    else:
        checks.append(
            _check(
                "model_named",
                "attention",
                "No model name is available to show.",
            )
        )

    ready = all(check.state == "done" for check in checks)
    return Readiness(
        ready=ready,
        model_label=status.model_label,
        runtime_label=status.runtime_label,
        checks=tuple(checks),
    )


class ConnectionTestGate:
    """At most one connection test in flight, and a minimum gap between tests.

    This bounds a forged or repeated request: the route takes no input, so the only
    abuse left is making the server probe its own configured runtime too often.
    """

    def __init__(
        self,
        *,
        min_interval_seconds: int = MIN_TEST_INTERVAL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._min_interval = min_interval_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._in_flight = False
        self._last_finished: float | None = None

    def begin(self) -> tuple[Literal["ok", "busy", "too_soon"], int | None]:
        with self._lock:
            if self._in_flight:
                return "busy", None
            if self._last_finished is not None:
                remaining = self._min_interval - (self._clock() - self._last_finished)
                if remaining > 0:
                    return "too_soon", max(1, math.ceil(remaining))
            self._in_flight = True
            return "ok", None

    def end(self) -> None:
        with self._lock:
            self._in_flight = False
            self._last_finished = self._clock()


_MESSAGES: Final[dict[TestOutcome, str]] = {
    "reachable": (
        "The AI runtime on this machine answered. This only shows that it is running; "
        "it does not check the model, and nothing was sent to it."
    ),
    "not_reachable": (
        "The AI runtime did not answer. Make sure it is running on this machine and that "
        "your installation names it correctly, then test again."
    ),
    "assistance_off": "AI assistance is off, so nothing was tested.",
    "no_runtime": (
        "No AI runtime is set up on this installation, so nothing was tested. "
        "Setup happens outside TrustTable."
    ),
    "not_local": (
        "The AI runtime this installation names is not on this machine. TrustTable only "
        "tests a runtime on this machine, so nothing was tested."
    ),
    "busy": "A connection test is already running, so nothing new was started.",
    "too_soon": "A test finished a moment ago, so nothing was tested. Wait a few seconds.",
}


def _refused(outcome: TestOutcome, retry_after: int | None = None) -> ConnectionTestResult:
    return ConnectionTestResult(
        outcome=outcome, tested=False, message=_MESSAGES[outcome], retry_after_seconds=retry_after
    )


def _is_local(settings: Settings) -> bool:
    return (
        model_location_for(settings.llm_provider, settings.llm_base_url)
        is EnrichmentModelLocation.LOCAL
    )


def run_connection_test(
    resolution: AiAssistanceResolution,
    *,
    gate: ConnectionTestGate,
    provider_factory: ProviderFactory = create_provider,
) -> ConnectionTestResult:
    """Probe the configured runtime once, or say precisely why nothing was probed.

    A refusal never touches the gate, so only a real probe uses the interval.
    """
    settings = resolution.settings
    if not resolution.enabled:
        return _refused("assistance_off")
    if resolution.unavailable_reason == "not_local":
        return _refused("not_local")
    if (
        resolution.unavailable_reason == "no_runtime"
        or settings.llm_provider == "disabled"
        or (settings.llm_provider != "mock" and not settings.llm_model.strip())
    ):
        return _refused("no_runtime")
    if not _is_local(settings):
        return _refused("not_local")

    verdict, retry_after = gate.begin()
    if verdict == "busy":
        return _refused("busy")
    if verdict == "too_soon":
        return _refused("too_soon", retry_after)
    try:
        answered = probe_runtime(settings, provider_factory=provider_factory)
    finally:
        gate.end()
    return ConnectionTestResult(
        outcome="reachable" if answered else "not_reachable",
        tested=True,
        message=_MESSAGES["reachable" if answered else "not_reachable"],
    )
