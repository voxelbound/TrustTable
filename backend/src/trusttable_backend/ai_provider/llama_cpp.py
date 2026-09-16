"""The real local-inference provider (`AI-03`).

`LlamaCppProvider` is the concrete `AIProvider` a future caller
constructs (via `factory.create_provider`) when `Settings.llm_provider
== "llama_cpp"` (`docs/decision-log.md` D-035: `llama.cpp` selected as
the v0.2 baseline local-inference runtime; `D-034`: Qwen3.5-4B-Q4_K_M
selected as the baseline-profile model).

Structurally mirrors the already-proven benchmark-only adapter
(`ai_benchmark.adapters.llama_cpp_http.LlamaCppHttpProvider`, `WP-044`)
-- same transport (`llama-server`'s OpenAI-compatible
`/v1/chat/completions` endpoint via `httpx`), same reuse of
`ai_boundary.prompt.build_safe_prompt` unmodified, same JSON-output
instruction appended after it (proven necessary, not optional, during
the hands-on evaluation this decision is built on -- every accepted
result recorded in `docs/evaluation/ai-06-first-round-model-screening-
2026-09-16.md` was produced with this exact instruction present).
`complete()` never calls `ai_boundary.validation.validate_model_output`
itself; that remains the caller's responsibility, exactly like every
other provider (`DisabledProvider`/`MockProvider`) -- this module
introduces no caller.

Distinct from the benchmark adapter in every way that matters for
being a real product provider rather than evaluation tooling:
`provider_name` is `"llama_cpp"`, the real `Settings.llm_provider`
value (`config.py`); `temperature`/`timeout_seconds` are meant to be
supplied from `Settings.llm_temperature`/`llm_timeout_seconds` by a
future caller (this module does not import `config.py` itself --
`ai_provider` stays framework-independent, matching `factory.py`'s own
existing constraint); it is registered in `ai_provider.factory` and
re-exported from `ai_provider`'s own top-level package.

No FastAPI route, application service, or analysis-pipeline calls this
provider yet -- that remains a separate, later package (`CTX-01`/`CTX-
02`/`CTX-03`). `Settings.llm_provider`'s default is unchanged
(`"disabled"`); AI remains off by default.

Framework-independent except for `httpx` (already a declared backend
dependency, matching the benchmark adapter's own precedent): no
FastAPI/SQLAlchemy/pydantic import.
"""

from __future__ import annotations

import json
from time import perf_counter
from typing import Any

import httpx

from ..ai_boundary.prompt import build_safe_prompt
from .contract import (
    ProviderConnectionError,
    ProviderHealth,
    ProviderInvalidResponseError,
    ProviderRequest,
    ProviderResponse,
    ProviderTimeoutError,
)

#: `AIProvider.provider_name` for this provider, and the `Settings.
#: llm_provider` value (`config.py`, `D-035`) it corresponds to.
LLAMA_CPP_PROVIDER_NAME = "llama_cpp"

#: Bound on how much of a non-2xx response body or malformed model
#: output is included in a raised exception's message -- avoids an
#: unbounded-length error message. Not a security control; this
#: provider talks only to a locally configured `llama-server` instance,
#: not the untrusted-data boundary `ai_boundary` already owns.
_MAX_ERROR_EXCERPT_CHARS = 500

#: Instruction appended after `build_safe_prompt`'s own unmodified
#: `system_instructions`, telling the model the exact JSON shape
#: `ai_boundary.validation.validate_model_output` expects. Mirrors the
#: benchmark-only adapter's own instruction exactly (same wording,
#: proven necessary and sufficient for schema-valid output from the
#: evaluated candidates during the hands-on evaluation this decision is
#: built on) -- not new model-specific tuning, and never a modification
#: of `build_safe_prompt` itself.
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


class LlamaCppProvider:
    """`AIProvider` for `llm_provider == "llama_cpp"` (`AI-03`, `D-035`).

    Satisfies the `AIProvider` Protocol structurally (`AI-01`,
    `contract.py`) -- no explicit inheritance required.

    `client`, when supplied, replaces the real `httpx.Client` this
    provider otherwise constructs -- the seam tests use to inject an
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
            raise ValueError("LlamaCppProvider.base_url must not be empty")
        if not model_identifier:
            raise ValueError("LlamaCppProvider.model_identifier must not be empty")
        if timeout_seconds <= 0:
            raise ValueError("LlamaCppProvider.timeout_seconds must be positive")
        self._base_url = base_url.rstrip("/")
        self._model_identifier = model_identifier
        self._timeout_seconds = timeout_seconds
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._client = client if client is not None else httpx.Client()

    @property
    def provider_name(self) -> str:
        return LLAMA_CPP_PROVIDER_NAME

    def health_check(self) -> ProviderHealth:
        """Probe `{base_url}/health`. Never raises -- a transport failure
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
                detail=f"llama-server health check failed: {type(exc).__name__}: {exc}",
            )
        available = 200 <= response.status_code < 300
        return ProviderHealth(
            available=available,
            provider_name=self.provider_name,
            model_identifier=self._model_identifier,
            detail=f"llama-server /health returned HTTP {response.status_code}",
        )

    def complete(self, request: ProviderRequest) -> ProviderResponse:
        """Send `request` to `llama-server`'s OpenAI-compatible
        `/v1/chat/completions` endpoint and return the parsed
        `ProviderResponse`. Never validates `raw_output` itself -- a
        future caller's own `validate_model_output` call remains the
        sole acceptance authority, exactly as it already is for
        `MockProvider`/`DisabledProvider`.
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
                f"llama-server request timed out after {self._timeout_seconds}s: "
                f"{type(exc).__name__}"
            ) from exc
        except httpx.HTTPError as exc:
            raise ProviderConnectionError(
                f"llama-server request failed: {type(exc).__name__}: {exc}"
            ) from exc
        duration_ms = (perf_counter() - start) * 1000

        if not (200 <= response.status_code < 300):
            body_excerpt = response.text[:_MAX_ERROR_EXCERPT_CHARS]
            raise ProviderInvalidResponseError(
                f"llama-server returned HTTP {response.status_code}: {body_excerpt}"
            )

        try:
            body = response.json()
            message_content = body["choices"][0]["message"]["content"]
        except (json.JSONDecodeError, KeyError, IndexError, TypeError) as exc:
            raise ProviderInvalidResponseError(
                "llama-server response did not match the expected "
                f"OpenAI-compatible chat-completions shape: {type(exc).__name__}: {exc}"
            ) from exc

        try:
            raw_output = json.loads(message_content)
        except json.JSONDecodeError as exc:
            excerpt = str(message_content)[:_MAX_ERROR_EXCERPT_CHARS]
            raise ProviderInvalidResponseError(
                f"llama-server model output was not valid JSON ({type(exc).__name__}): {excerpt}"
            ) from exc
        if not isinstance(raw_output, dict):
            raise ProviderInvalidResponseError(
                "llama-server model output JSON was not an object "
                f"(got {type(raw_output).__name__})"
            )

        return ProviderResponse(
            raw_output=raw_output,
            provider_name=self.provider_name,
            model_identifier=self._model_identifier,
            duration_ms=duration_ms,
        )


__all__ = ["LLAMA_CPP_PROVIDER_NAME", "LlamaCppProvider"]
