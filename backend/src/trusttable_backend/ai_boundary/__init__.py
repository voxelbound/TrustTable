"""The "AI boundary" backend layer (`SEC-02`), matching
`docs/architecture.md` §3/§7: a framework-independent untrusted-data
envelope, safe prompt builder, and model-output validator that every
AI-facing package sits behind — plus (`AI-08`) the versioned structured
`finding_analysis_v1` output contract and its role-aware validator.

Pure domain-layer logic: no provider, network, HTTP or UI code lives here.
"""

from __future__ import annotations

from .claim_screen import (
    CLAIM_FAMILY_IDS,
    CLAIM_SCREEN_VERSION,
    normalize_narrative,
    screen_narrative,
)
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
from .finding_analysis import (
    FINDING_ANALYSIS_CONTRACT_NAME,
    FINDING_ANALYSIS_SCHEMA_VERSION,
    build_finding_analysis_contract,
    finding_analysis_json_schema,
    validate_finding_analysis_output,
)
from .output_contract import OutputContract
from .prompt import PROMPT_TEMPLATE_VERSION, SafePrompt, build_safe_prompt
from .validation import (
    MODEL_OUTPUT_SCHEMA_VERSION,
    RejectionReason,
    ValidationOutcome,
    validate_model_output,
)

__all__ = [
    "CLAIM_FAMILY_IDS",
    "CLAIM_SCREEN_VERSION",
    "DEFAULT_MAX_SAMPLE_COUNT",
    "DEFAULT_MAX_SAMPLE_VALUE_LENGTH",
    "FINDING_ANALYSIS_CONTRACT_NAME",
    "FINDING_ANALYSIS_SCHEMA_VERSION",
    "MODEL_OUTPUT_SCHEMA_VERSION",
    "PROMPT_TEMPLATE_VERSION",
    "OutputContract",
    "PromptEnvelope",
    "RedactionHook",
    "RejectionReason",
    "SafePrompt",
    "UntrustedSample",
    "ValidationOutcome",
    "build_finding_analysis_contract",
    "build_prompt_envelope",
    "build_safe_prompt",
    "build_untrusted_samples",
    "default_redaction_hook",
    "finding_analysis_json_schema",
    "normalize_narrative",
    "screen_narrative",
    "validate_finding_analysis_output",
    "validate_model_output",
]
