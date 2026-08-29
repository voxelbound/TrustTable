"""The "AI boundary" backend layer (`SEC-02`), matching
`docs/architecture.md` §3/§7: a framework-independent untrusted-data
envelope, safe prompt builder, and model-output validator that every
future AI-facing package (`AI-01`/`AI-02`, `DET-SEC-01`) sits behind.

No real LLM provider, API endpoint, or UI exists yet — this package is
pure domain-layer logic exercised by synthetic test fixtures.
"""

from __future__ import annotations

from .envelope import (
    DEFAULT_MAX_SAMPLE_COUNT,
    DEFAULT_MAX_SAMPLE_VALUE_LENGTH,
    PromptEnvelope,
    RedactionHook,
    UntrustedSample,
    build_prompt_envelope,
    build_untrusted_samples,
    default_redaction_hook,
)
from .prompt import PROMPT_TEMPLATE_VERSION, SafePrompt, build_safe_prompt
from .validation import (
    MODEL_OUTPUT_SCHEMA_VERSION,
    RejectionReason,
    ValidationOutcome,
    validate_model_output,
)

__all__ = [
    "DEFAULT_MAX_SAMPLE_COUNT",
    "DEFAULT_MAX_SAMPLE_VALUE_LENGTH",
    "MODEL_OUTPUT_SCHEMA_VERSION",
    "PROMPT_TEMPLATE_VERSION",
    "PromptEnvelope",
    "RedactionHook",
    "RejectionReason",
    "SafePrompt",
    "UntrustedSample",
    "ValidationOutcome",
    "build_prompt_envelope",
    "build_safe_prompt",
    "build_untrusted_samples",
    "default_redaction_hook",
    "validate_model_output",
]
