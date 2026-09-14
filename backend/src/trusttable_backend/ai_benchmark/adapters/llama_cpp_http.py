"""Benchmark-only llama.cpp (`llama-server`) HTTP adapter.

`LlamaCppHttpProvider` structurally satisfies `ai_provider.contract.
AIProvider` (`AI-01`) so `ai_benchmark.runner.run_benchmark` (`AI-06`)
can exercise a real, locally running `llama-server` instance during the
"hands-on benchmark/model evaluation" step (`docs/decision-log.md`
D-032/D-033) — without implementing `AI-03` and without changing any
product-facing provider selection.

**This is evaluation tooling only.** `provider_name` is deliberately a
self-describing, non-product string (`PROVIDER_NAME`), never
`"disabled"`/`"mock"`/`"ollama"` — it cannot collide with, and is never
read by, `Settings.llm_provider`/`ai_provider.factory.create_provider`.
Endpoint, timeout, temperature, and token-limit are all caller-supplied
constructor arguments; none of them read or reuse `Settings.
llm_base_url`/`llm_model`/`llm_timeout_seconds` (product configuration,
out of scope for benchmark tooling). Nothing here is reachable from any
FastAPI route or application service, and nothing here is re-exported
from `ai_benchmark`'s own top-level `__init__.py`.

`complete()` reuses `ai_boundary.prompt.build_safe_prompt` unmodified —
the existing trust-boundary seam is never re-implemented or bypassed —
and performs transport/JSON parsing only. It never calls `ai_boundary.
validation.validate_model_output` itself; `runner.py`'s existing central
call to that validator remains the sole grading/acceptance authority,
exactly as it already is for `MockProvider`/`DisabledProvider`.

Talks to `llama-server`'s OpenAI-compatible `/v1/chat/completions`
endpoint via `httpx` (already a declared backend dependency — no new
dependency). Tests use `httpx.MockTransport` (already part of the
installed `httpx` package) — no real network access anywhere in this
module's own test suite.

`AI-03` (the real local-inference provider, selected only after the
human-owned runtime/model/quantization decision gate) remains fully
unstarted. This module's existence does not select, imply, or anchor
any runtime, model, or quantization choice.

Example (illustrative only — not an executable script; requires a
`llama-server` instance the caller has already started, out of scope
for this module):

    from trusttable_backend.ai_benchmark.adapters.llama_cpp_http import (
        LlamaCppHttpProvider,
    )
    from trusttable_backend.ai_benchmark.fixtures import build_fixture_tasks
    from trusttable_backend.ai_benchmark.runner import run_benchmark
    from trusttable_backend.ai_benchmark.persistence import (
        CandidateMetadata,
        save_report,
    )

    provider = LlamaCppHttpProvider(
        base_url="http://127.0.0.1:8080",
        model_identifier="<exact model under evaluation>",
    )
    report = run_benchmark(provider, build_fixture_tasks())
    save_report(
        report,
        config=...,
        path="benchmark-run.json",
        candidate=CandidateMetadata(
            runtime_identifier="llama.cpp",
            model_identifier="<exact model under evaluation>",
            quantization_identifier="<exact quantization>",
            hardware_profile="baseline",
        ),
    )
"""

from __future__ import annotations

import json
from time import perf_counter
from typing import Any

import httpx

from ...ai_boundary.prompt import build_safe_prompt
from ...ai_provider.contract import (
    ProviderConnectionError,
    ProviderHealth,
    ProviderInvalidResponseError,
    ProviderRequest,
    ProviderResponse,
    ProviderTimeoutError,
)

#: `AIProvider.provider_name` for this adapter. Deliberately distinct
#: from every `config.LlmProvider` value (`"disabled"`, `"mock"`,
#: `"ollama"`) so it can never be mistaken for, or wired to, a product
#: provider selection.
PROVIDER_NAME = "llama_cpp_http_benchmark_only"

#: Bound on how much of a non-2xx response body or malformed model
#: output is included in a raised exception's message — avoids an
#: unbounded-length error message, not a security control (this is
#: local benchmark tooling, not the product's untrusted-data boundary).
_MAX_ERROR_EXCERPT_CHARS = 500

#: Fixed, benchmark-owned instruction appended to `build_safe_prompt`'s
#: `system_instructions`, telling the model the exact JSON shape
#: `ai_boundary.validation.validate_model_output` expects. First-pass
#: benchmark scaffolding (`docs/decision-log.md` D-032's disclosed
#: "future benchmark-design work" allowance) — not a scoring decision,
#: not model-specific tuning, and never sent as an application
#: instruction reused by anything else in the product.
_JSON_OUTPUT_INSTRUCTIONS = (
    "Respond with a single JSON object only: no other text, no markdown "
    "code fences. The JSON object must use exactly these top-level "
    'keys: "schema_version" (string, use "1"), "narrative" (string), '
    '"provenance" (string, use "ai_interpretation"), and, only when '
    'relevant, any of: "referenced_evidence_ids" (array of strings), '
    '"referenced_columns" (array of strings), "numeric_claims" (object '
    'mapping a claim label to a number), "severity" (string). Do not '
    "include any key not listed here."
)


class LlamaCppHttpProvider:
    """Benchmark-only `AIProvider` for a locally running `llama-server`.

    Satisfies the `AIProvider` Protocol structurally (`AI-01`,
    `ai_provider.contract`) — no explicit inheritance, no registration
    in `ai_provider.factory`.

    `client`, when supplied, replaces the real `httpx.Client` this
    provider otherwise constructs — the seam tests use to inject an
    `httpx.MockTransport`-backed client instead of performing real
    network I/O.
    """

    def __init__(
        self,
        *,
        base_url: str,
        model_identifier: str,
        timeout_seconds: float = 120.0,
        temperature: float = 0.0,
        max_tokens: int = 512,
        client: httpx.Client | None = None,
    ) -> None:
        if not base_url:
            raise ValueError("LlamaCppHttpProvider.base_url must not be empty")
        if not model_identifier:
            raise ValueError("LlamaCppHttpProvider.model_identifier must not be empty")
        if timeout_seconds <= 0:
            raise ValueError("LlamaCppHttpProvider.timeout_seconds must be positive")
        self._base_url = base_url.rstrip("/")
        self._model_identifier = model_identifier
        self._timeout_seconds = timeout_seconds
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._client = client if client is not None else httpx.Client()

    @property
    def provider_name(self) -> str:
        return PROVIDER_NAME

    def health_check(self) -> ProviderHealth:
        """Probe `{base_url}/health`. Never raises — a transport failure
        is reported as `available=False`, matching every other
        `AIProvider.health_check()` implementation's contract.
        """
        try:
            response = self._client.get(f"{self._base_url}/health", timeout=self._timeout_seconds)
        except httpx.HTTPError as exc:
            return ProviderHealth(
                available=False,
                provider_name=self.provider_name,
                model_identifier=self._model_identifier,
                detail=(
                    f"benchmark-only llama-server health check failed: {type(exc).__name__}: {exc}"
                ),
            )
        available = 200 <= response.status_code < 300
        return ProviderHealth(
            available=available,
            provider_name=self.provider_name,
            model_identifier=self._model_identifier,
            detail=f"benchmark-only llama-server /health returned HTTP {response.status_code}",
        )

    def complete(self, request: ProviderRequest) -> ProviderResponse:
        """Send `request` to `llama-server`'s OpenAI-compatible
        `/v1/chat/completions` endpoint and return the parsed
        `ProviderResponse`. Never validates `raw_output` itself —
        `runner.py`'s central `validate_model_output` call remains the
        sole acceptance authority.
        """
        safe_prompt = build_safe_prompt(request.envelope)
        system_instructions = f"{safe_prompt.system_instructions}\n\n{_JSON_OUTPUT_INSTRUCTIONS}"
        user_content = json.dumps(safe_prompt.data_payload, sort_keys=True)
        if request.retry_feedback:
            user_content = (
                f"{user_content}\n\nYour previous response was rejected: "
                f"{request.retry_feedback} Correct it and respond again with "
                "JSON only, using exactly the required keys."
            )
        payload: dict[str, Any] = {
            "model": self._model_identifier,
            "messages": [
                {"role": "system", "content": system_instructions},
                {"role": "user", "content": user_content},
            ],
            "temperature": self._temperature,
            "max_tokens": self._max_tokens,
        }

        start = perf_counter()
        try:
            response = self._client.post(
                f"{self._base_url}/v1/chat/completions",
                json=payload,
                timeout=self._timeout_seconds,
            )
        except httpx.TimeoutException as exc:
            raise ProviderTimeoutError(
                "benchmark-only llama-server request timed out after "
                f"{self._timeout_seconds}s: {type(exc).__name__}"
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderConnectionError(
                f"benchmark-only llama-server request failed: {type(exc).__name__}: {exc}"
            ) from exc
        duration_ms = (perf_counter() - start) * 1000

        if not (200 <= response.status_code < 300):
            body_excerpt = response.text[:_MAX_ERROR_EXCERPT_CHARS]
            raise ProviderInvalidResponseError(
                f"benchmark-only llama-server returned HTTP {response.status_code}: {body_excerpt}"
            )

        try:
            body = response.json()
            message_content = body["choices"][0]["message"]["content"]
        except (json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
            raise ProviderInvalidResponseError(
                "benchmark-only llama-server response did not match the expected "
                f"OpenAI-compatible chat-completions shape: {type(exc).__name__}: {exc}"
            ) from exc

        try:
            raw_output = json.loads(message_content)
        except json.JSONDecodeError as exc:
            excerpt = str(message_content)[:_MAX_ERROR_EXCERPT_CHARS]
            raise ProviderInvalidResponseError(
                f"benchmark-only llama-server model output was not valid JSON "
                f"({type(exc).__name__}): {excerpt}"
            ) from exc
        if not isinstance(raw_output, dict):
            raise ProviderInvalidResponseError(
                "benchmark-only llama-server model output JSON was not an object "
                f"(got {type(raw_output).__name__})"
            )

        return ProviderResponse(
            raw_output=raw_output,
            provider_name=self.provider_name,
            model_identifier=self._model_identifier,
            duration_ms=duration_ms,
        )


__all__ = ["PROVIDER_NAME", "LlamaCppHttpProvider"]
