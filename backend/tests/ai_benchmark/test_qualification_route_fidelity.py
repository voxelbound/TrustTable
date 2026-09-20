"""Fidelity proof for the finding-analysis qualification harness (`REL-02`,
`docs/decision-log.md` D-043).

The harness is only worth running if what it measures is what a user of the
product gets. So these tests do not check the harness against itself: they
drive the **real HTTP explanation route** and the **harness** over the same
findings, the same real `LlamaCppProvider` and the same stub `llama-server`
(an `httpx.MockTransport` that records every byte it receives and answers from
the request it actually got), and assert that:

- the harness's outcome equals the route's `ai_call_status` and accept-or-fall-
  back decision, and it makes the same number of provider calls, for every
  scripted provider behavior and both context conditions;
- the request bytes the provider sends are identical;
- the harness builds the provider with exactly the arguments the route passes
  to the provider factory;
- latency is measured by the harness clock and the confirmed-context condition
  delivers only confirmed fields, through the real provider.

Nothing reaches a live model or the network.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

import trusttable_backend.ai_benchmark.qualification as qualification_module
import trusttable_backend.api.v1.analyses as analyses_module
from trusttable_backend.ai_benchmark.qualification import (
    CaseOutcome,
    Condition,
    QualificationConfig,
    QualificationSuite,
    build_qualification_suite,
    run_qualification,
)
from trusttable_backend.ai_benchmark.qualification_cli import provider_from_settings
from trusttable_backend.ai_provider.contract import AIProvider
from trusttable_backend.ai_provider.factory import create_provider as real_create_provider
from trusttable_backend.analysis.service import create_analysis, run_analysis
from trusttable_backend.config import Settings, get_settings

from .test_qualification import (
    EDITABLE_FIELD_NAMES,
    INVALID_OUTPUT,
    ROLE_FIELD_NAMES,
    ManualClock,
    grounded_output,
)

Responder = Callable[[dict[str, Any], dict[str, Any]], httpx.Response]

_FEEDBACK_MARKER = "Your previous response was rejected"


def chat_response(content: str, status: int = 200) -> httpx.Response:
    return httpx.Response(status, json={"choices": [{"message": {"content": content}}]})


def payload_of(body: dict[str, Any]) -> dict[str, Any]:
    """The untrusted-data JSON payload a real model would read."""
    user = body["messages"][1]["content"]
    return json.loads(user.split(f"\n\n{_FEEDBACK_MARKER}")[0])  # type: ignore[no-any-return]


def has_feedback(body: dict[str, Any]) -> bool:
    return _FEEDBACK_MARKER in body["messages"][1]["content"]


class StubServer:
    """A `llama-server` stand-in: records every request, answers via `respond`."""

    def __init__(self, respond: Responder) -> None:
        self.raw: list[bytes] = []
        self.bodies: list[dict[str, Any]] = []
        self.health_probes = 0
        self.respond = respond

    def __call__(self, request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path == "/health":
            # The harness probes health once at the start; it is not a model request.
            self.health_probes += 1
            return httpx.Response(200, json={"status": "ok"})
        self.raw.append(request.content)
        body = json.loads(request.content)
        self.bodies.append(body)
        return self.respond(payload_of(body), body)


def make_factory(server: StubServer, created: list[dict[str, Any]]) -> Callable[..., AIProvider]:
    """The real provider factory, with the HTTP client swapped for the stub and
    every call's arguments recorded."""

    def factory(name: str, **kwargs: Any) -> AIProvider:
        created.append({"name": name, **kwargs})
        provider = real_create_provider(name, **kwargs)
        provider._client = httpx.Client(transport=httpx.MockTransport(server))  # type: ignore[attr-defined]
        return provider

    return factory


def select_llama(monkeypatch: pytest.MonkeyPatch, **extra: str) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "llama_cpp")
    monkeypatch.setenv("LLM_BASE_URL", "http://llama.test:8081")
    monkeypatch.setenv("LLM_MODEL", "Qwen3.5-4B-Q4_K_M")
    for key, value in extra.items():
        monkeypatch.setenv(key, value)
    # The route reads the process-wide cached settings; the analyses were prepared
    # (which caches the AI-disabled defaults) before a provider was selected.
    get_settings.cache_clear()


# ---------------------------------------------------------------------------
# Route helpers
# ---------------------------------------------------------------------------


def create_reference_analysis(client: TestClient) -> str:
    """Create the demo analysis in the running app's own store at the harness's
    fixed reference instant, so the route and the harness analyse the identical
    dataset. (`POST /demo/sales` uses the live clock, and a date-dependent
    detector's evidence embeds the date, which would differ.)"""
    store = client.app.state.analysis_store  # type: ignore[attr-defined]
    created = create_analysis(store)
    analysis = run_analysis(store, created.analysis_id, now=qualification_module._REFERENCE_INSTANT)
    return str(analysis.analysis_id)


def confirm_and_finalize(client: TestClient, analysis_id: str, edits: dict[str, str]) -> None:
    context = client.get(f"/api/v1/analyses/{analysis_id}/context").json()
    edited = client.put(
        f"/api/v1/analyses/{analysis_id}/context",
        json={"edits": edits, "expected_version": context["context_version"]},
    )
    assert edited.status_code == 200
    finalized = client.post(
        f"/api/v1/analyses/{analysis_id}/finalize",
        json={"expected_version": edited.json()["context_version"]},
    )
    assert finalized.status_code == 202


def first_finding_by_detector(client: TestClient, analysis_id: str) -> dict[str, str]:
    first: dict[str, str] = {}
    items = client.get(f"/api/v1/analyses/{analysis_id}/findings").json()["items"]
    for item in items:
        first.setdefault(item["detector_id"], str(item["finding_id"]))
    return first


def route_ai_call_status(client: TestClient, analysis_id: str, finding_id: str) -> str:
    response = client.get(f"/api/v1/analyses/{analysis_id}/findings/{finding_id}/explanation")
    assert response.status_code == 200
    return str(response.json()["ai_call_status"])


@dataclass(frozen=True)
class Analyses:
    open_id: str
    """Context not finalized: the evidence-only condition."""

    finalized_id: str
    """Context confirmed and finalized: the confirmed-context condition."""


def prepare_analyses(client: TestClient, suite: QualificationSuite) -> Analyses:
    """Create both analyses and finalize one *before* any provider is
    configured, so the context flow makes no model call."""
    edits = {name: str(entry["value"]) for name, entry in suite.confirmed_context.items()}  # type: ignore[index]
    open_id = create_reference_analysis(client)
    finalized_id = create_reference_analysis(client)
    confirm_and_finalize(client, finalized_id, edits)
    return Analyses(open_id=open_id, finalized_id=finalized_id)


@pytest.fixture(scope="module")
def suite() -> QualificationSuite:
    return build_qualification_suite()


# ---------------------------------------------------------------------------
# Scripted server behaviors
# ---------------------------------------------------------------------------


def accept(payload: dict[str, Any], body: dict[str, Any]) -> httpx.Response:
    return chat_response(json.dumps(grounded_output(payload)))


def reject_then_accept(payload: dict[str, Any], body: dict[str, Any]) -> httpx.Response:
    if has_feedback(body):
        return chat_response(json.dumps(grounded_output(payload)))
    return chat_response(json.dumps(INVALID_OUTPUT))


def reject_always(payload: dict[str, Any], body: dict[str, Any]) -> httpx.Response:
    return chat_response(json.dumps(INVALID_OUTPUT))


def time_out(payload: dict[str, Any], body: dict[str, Any]) -> httpx.Response:
    raise httpx.ReadTimeout("timed out")


def refuse(payload: dict[str, Any], body: dict[str, Any]) -> httpx.Response:
    raise httpx.ConnectError("refused")


def server_error(payload: dict[str, Any], body: dict[str, Any]) -> httpx.Response:
    return httpx.Response(500, text="boom")


def not_json(payload: dict[str, Any], body: dict[str, Any]) -> httpx.Response:
    return chat_response("this is not json")


@dataclass(frozen=True)
class Scenario:
    respond: Responder
    route_status: str
    outcome: CaseOutcome
    provider_calls: int


SCENARIOS: dict[str, Scenario] = {
    "accepted_first_attempt": Scenario(
        accept, "attempted_accepted", CaseOutcome.ACCEPTED_FIRST_ATTEMPT, 1
    ),
    "accepted_after_retry": Scenario(
        reject_then_accept, "attempted_accepted", CaseOutcome.ACCEPTED_AFTER_RETRY, 2
    ),
    "rejected_on_every_attempt": Scenario(
        reject_always, "attempted_rejected", CaseOutcome.FELL_BACK_REJECTED, 3
    ),
    "timeout": Scenario(
        time_out, "attempted_provider_error", CaseOutcome.FELL_BACK_PROVIDER_ERROR, 1
    ),
    "connection_error": Scenario(
        refuse, "attempted_provider_error", CaseOutcome.FELL_BACK_PROVIDER_ERROR, 1
    ),
    "http_500": Scenario(
        server_error, "attempted_provider_error", CaseOutcome.FELL_BACK_PROVIDER_ERROR, 1
    ),
    "invalid_json": Scenario(
        not_json, "attempted_provider_error", CaseOutcome.FELL_BACK_PROVIDER_ERROR, 1
    ),
}


# ---------------------------------------------------------------------------
# 1. Outcome equivalence with the real route
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("scenario_name", sorted(SCENARIOS))
def test_harness_outcome_and_call_count_equal_the_real_routes(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    suite: QualificationSuite,
    scenario_name: str,
) -> None:
    scenario = SCENARIOS[scenario_name]
    analyses = prepare_analyses(client, suite)
    server = StubServer(scenario.respond)
    select_llama(monkeypatch)
    monkeypatch.setattr(analyses_module, "create_provider", make_factory(server, []))

    provider = provider_from_settings(Settings(), factory=make_factory(server, []))
    report = run_qualification(provider, suite)
    by_key = {(r.detector_id, r.condition): r for r in report.case_results}

    compared = 0
    for condition, analysis_id in (
        (Condition.EVIDENCE_ONLY, analyses.open_id),
        (Condition.CONFIRMED_CONTEXT, analyses.finalized_id),
    ):
        finding_ids = first_finding_by_detector(client, analysis_id)
        for case in suite.cases:
            finding_id = finding_ids[case.detector_id]
            assert finding_id == case.finding_id  # the identical analysis, finding for finding
            before = len(server.bodies)
            status = route_ai_call_status(client, analysis_id, finding_id)
            route_calls = len(server.bodies) - before

            harness = by_key[(case.detector_id, condition)]
            assert harness.product_ai_call_status == status, (case.case_id, condition)
            assert status == scenario.route_status, (case.case_id, condition)
            assert harness.outcome is scenario.outcome, (case.case_id, condition)
            assert len(harness.attempts) == route_calls == scenario.provider_calls, case.case_id
            compared += 1

    assert compared == 2 * len(suite.cases)  # every case, under both conditions


# ---------------------------------------------------------------------------
# 2. The provider receives identical bytes
# ---------------------------------------------------------------------------


def test_harness_and_route_send_the_provider_identical_request_bytes(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, suite: QualificationSuite
) -> None:
    analyses = prepare_analyses(client, suite)
    route_server = StubServer(accept)
    harness_server = StubServer(accept)
    select_llama(monkeypatch)
    monkeypatch.setattr(analyses_module, "create_provider", make_factory(route_server, []))
    provider = provider_from_settings(Settings(), factory=make_factory(harness_server, []))
    report = run_qualification(provider, suite)

    # One accepted attempt per case, in condition-then-case order.
    harness_bytes = {
        (r.detector_id, r.condition): harness_server.raw[index]
        for index, r in enumerate(report.case_results)
    }
    compared = 0
    for condition, analysis_id in (
        (Condition.EVIDENCE_ONLY, analyses.open_id),
        (Condition.CONFIRMED_CONTEXT, analyses.finalized_id),
    ):
        finding_ids = first_finding_by_detector(client, analysis_id)
        for case in suite.cases:
            finding_id = finding_ids[case.detector_id]
            assert finding_id == case.finding_id
            before = len(route_server.raw)
            route_ai_call_status(client, analysis_id, finding_id)
            assert route_server.raw[before] == harness_bytes[(case.detector_id, condition)], (
                case.case_id,
                condition,
            )
            compared += 1
    assert compared == 2 * len(suite.cases)


# ---------------------------------------------------------------------------
# 3. The provider is built with the route's arguments
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "extra",
    [{}, {"LLM_TIMEOUT_SECONDS": "45", "LLM_TEMPERATURE": "0.7"}],
    ids=["defaults", "custom_timeout_and_temperature"],
)
def test_harness_builds_the_provider_with_exactly_the_arguments_the_route_passes(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    suite: QualificationSuite,
    extra: dict[str, str],
) -> None:
    analyses = prepare_analyses(client, suite)
    server = StubServer(accept)
    route_created: list[dict[str, Any]] = []
    harness_created: list[dict[str, Any]] = []
    select_llama(monkeypatch, **extra)
    monkeypatch.setattr(analyses_module, "create_provider", make_factory(server, route_created))

    finding_id = next(iter(first_finding_by_detector(client, analyses.open_id).values()))
    route_ai_call_status(client, analyses.open_id, finding_id)
    provider_from_settings(Settings(), factory=make_factory(server, harness_created))

    assert route_created and harness_created
    assert harness_created[0] == route_created[0]
    expected_timeout = float(extra.get("LLM_TIMEOUT_SECONDS", "120"))
    assert harness_created[0]["timeout_seconds"] == expected_timeout
    # `LLM_TEMPERATURE` exists in `Settings` but neither the route nor the harness
    # passes it to the factory (FUP-014): the harness measures what the product does.
    assert "temperature" not in harness_created[0]
    assert "max_tokens" not in harness_created[0]


# ---------------------------------------------------------------------------
# 4. Real provider: latency comes from the harness clock
# ---------------------------------------------------------------------------


def llama_settings() -> Settings:
    return Settings(
        llm_provider="llama_cpp",
        llm_base_url="http://llama.test:8081",
        llm_model="Qwen3.5-4B-Q4_K_M",
        llm_timeout_seconds=120,
    )


def test_per_attempt_latency_with_the_real_provider_comes_from_the_harness_clock(
    suite: QualificationSuite,
) -> None:
    clock = ManualClock()

    def slow_accept(payload: dict[str, Any], body: dict[str, Any]) -> httpx.Response:
        clock.advance(2.5)
        return chat_response(json.dumps(grounded_output(payload)))

    server = StubServer(slow_accept)
    provider = provider_from_settings(llama_settings(), factory=make_factory(server, []))
    report = run_qualification(
        provider,
        suite,
        config=QualificationConfig(conditions=(Condition.EVIDENCE_ONLY,)),
        clock=clock,
    )

    for result in report.case_results:
        assert result.outcome is CaseOutcome.ACCEPTED_FIRST_ATTEMPT
        assert [a.duration_ms for a in result.attempts] == [2500.0]
        assert result.total_duration_ms == 2500.0
    assert report.aggregate.case_latency.p95_ms == 2500.0
    assert report.aggregate.slowest_completed_attempt_ms == 2500.0


def test_a_slow_timeout_is_recorded_as_a_failed_attempt_not_a_completed_one(
    suite: QualificationSuite,
) -> None:
    clock = ManualClock()

    def slow_timeout(payload: dict[str, Any], body: dict[str, Any]) -> httpx.Response:
        clock.advance(120.0)
        raise httpx.ReadTimeout("timed out")

    server = StubServer(slow_timeout)
    provider = provider_from_settings(llama_settings(), factory=make_factory(server, []))
    report = run_qualification(
        provider,
        suite,
        config=QualificationConfig(
            conditions=(Condition.EVIDENCE_ONLY,), configured_timeout_seconds=120.0
        ),
        clock=clock,
    )

    assert report.aggregate.slowest_attempt_ms == 120_000.0
    assert report.aggregate.slowest_completed_attempt_ms == 0.0
    assert report.aggregate.provider_error_kind_counts == {"ProviderTimeoutError": len(suite.cases)}


# ---------------------------------------------------------------------------
# 5. Real provider: what each condition sends
# ---------------------------------------------------------------------------


def test_evidence_only_sends_no_context_and_confirmed_sends_only_confirmed_fields(
    suite: QualificationSuite,
) -> None:
    server = StubServer(accept)
    provider = provider_from_settings(llama_settings(), factory=make_factory(server, []))
    report = run_qualification(provider, suite)

    cases = len(suite.cases)
    payloads = [payload_of(body) for body in server.bodies]
    assert len(payloads) == 2 * cases
    for payload in payloads[:cases]:
        assert payload["confirmed_context"] == {}
    for payload in payloads[cases:]:
        sent = payload["confirmed_context"]
        assert set(sent) == EDITABLE_FIELD_NAMES
        assert not set(sent) & ROLE_FIELD_NAMES
        assert {entry["confirmation_state"] for entry in sent.values()} <= {
            "confirmed",
            "corrected",
        }
    assert report.aggregate.fill_rate == 1.0


def cite_context_field(field_name: str) -> Responder:
    def respond(payload: dict[str, Any], body: dict[str, Any]) -> httpx.Response:
        output = grounded_output(payload, use_context=False)
        output["business_impact"].append(
            {
                "statement": "This matters in light of the dataset context.",
                "evidence_ids": [],
                "context_fields": [field_name],
                "assumption": "the context describes how the data is used",
            }
        )
        return chat_response(json.dumps(output))

    return respond


def test_a_statement_citing_confirmed_context_is_accepted_only_where_it_was_sent(
    suite: QualificationSuite,
) -> None:
    server = StubServer(cite_context_field("probable_domain"))
    provider = provider_from_settings(llama_settings(), factory=make_factory(server, []))
    report = run_qualification(provider, suite)

    by_condition = report.aggregate_by_condition
    assert by_condition["evidence_only"].fill_rate == 0.0  # nothing was sent to cite
    assert by_condition["evidence_only"].outcome_counts["fell_back_rejected"] == len(suite.cases)
    assert by_condition["confirmed_context"].fill_rate == 1.0


def test_a_statement_citing_an_inferred_role_field_is_rejected_even_with_confirmed_context(
    suite: QualificationSuite,
) -> None:
    server = StubServer(cite_context_field("candidate_keys"))
    provider = provider_from_settings(llama_settings(), factory=make_factory(server, []))
    report = run_qualification(provider, suite)

    assert report.aggregate.fill_rate == 0.0  # role fields are never sent, so never citable
    assert report.aggregate_by_condition["confirmed_context"].fallback_rate == 1.0
