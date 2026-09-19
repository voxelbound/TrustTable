"""Human-readable AI provenance for normal user-facing display (`AI-08`,
`docs/decision-log.md` D-040).

`Settings.llm_model` is an operator-supplied string. For `llama.cpp` it is
often a filesystem path or a repository id (`llama-server` ignores the value
but echoes it back), so passing it straight through to the API and the UI
leaks an absolute host path (for example a Windows or Linux model
directory). This module is the single place that turns the raw configured
value and the provider name into:

- a **sanitized identifier** — the final path segment only, bounded and
  free of control characters, URL credentials, drive prefixes and every
  directory component — kept for diagnostics; and
- **display labels** — a deployment label (`"Local AI"`), a runtime label
  (`"llama.cpp"`) and a model label (`"Qwen3.5 4B"`) with the quantization
  (`"Q4_K_M"`) reported separately.

The provider itself still receives the raw configured value it needs; only
what leaves the backend is derived here. Pure and framework-independent:
stdlib only, no I/O, no filesystem access.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Final

#: Longest sanitized identifier or label returned. Bounds what an
#: operator-supplied string can put on screen or in a response.
MAX_DISPLAY_LENGTH: Final[int] = 80

_SCHEME_RE = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*://")
_SEPARATORS_RE = re.compile(r"[\\/]+")
_GGUF_EXTENSION_RE = re.compile(r"\.gguf$", re.IGNORECASE)
_GGUF_TOKEN_RE = re.compile(r"(?:^|[-_.: ])GGUF(?=$|[-_.: ])", re.IGNORECASE)
_QUANTIZATION_RE = re.compile(
    r"(?:^|[-_.: ])((?:IQ|Q)\d(?:_[A-Z0-9]+)*|BF16|F16|F32)(?=$|[-_.: ])",
    re.IGNORECASE,
)
_SIZE_TOKEN_RE = re.compile(r"^(\d+(?:\.\d+)?)b$", re.IGNORECASE)
_TOKEN_SPLIT_RE = re.compile(r"[-_:\s]+")
_WHITESPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True, slots=True)
class ModelDescription:
    """A model's human-readable label and quantization, both derived from
    its sanitized identifier."""

    label: str
    quantization: str | None


@dataclass(frozen=True, slots=True)
class AiProvenanceDisplay:
    """What normal user-facing UI and API responses may show about the AI
    that produced an interpretation. Never a filesystem path.

    Fields:
        deployment_label: where the AI runs, in plain words (for example
            `"Local AI"`).
        runtime_label: the runtime or provider (for example `"llama.cpp"`).
        model_label: a readable model name (for example `"Qwen3.5 4B"`),
            or `None` when no identifier was available.
        quantization: the quantization tag (for example `"Q4_K_M"`), or
            `None`.
        model_identifier: the sanitized identifier kept for diagnostics
            (final path segment only), or `None`.
    """

    deployment_label: str
    runtime_label: str
    model_label: str | None
    quantization: str | None
    model_identifier: str | None


def _strip_control_characters(text: str) -> str:
    return "".join(ch for ch in text if not unicodedata.category(ch).startswith("C"))


def sanitize_model_identifier(raw: str | None) -> str | None:
    """Reduce an operator-supplied model identifier to a safe, bounded,
    path-free identifier, or `None` when nothing usable remains.

    Handles Windows drive and UNC paths, POSIX and tilde paths, `file://`
    and other URLs (including embedded credentials and authorities),
    Hugging Face style repository ids, control characters and over-long
    values. Only the final path segment survives — never a directory.
    """
    if raw is None:
        return None
    text = _strip_control_characters(raw).strip()
    if not text:
        return None

    drop_first_segment = False
    scheme_match = _SCHEME_RE.match(text)
    if scheme_match:
        text = text[scheme_match.end() :]
        # What follows a scheme is `authority/path`; the authority can carry
        # credentials, so it is never eligible to be the surviving segment.
        drop_first_segment = True

    segments = [segment for segment in _SEPARATORS_RE.split(text) if segment]
    if drop_first_segment:
        segments = segments[1:]
    if not segments:
        return None

    last = segments[-1].strip()
    # A drive-relative name such as `C:model.gguf` (no separator after the
    # colon) still carries a drive prefix.
    if len(last) >= 3 and last[0].isalpha() and last[1] == ":" and last[2] != ":":
        last = last[2:]
    if last in {".", "..", "~"}:
        return None
    last = _WHITESPACE_RE.sub(" ", last).strip()
    if not last:
        return None
    return last[:MAX_DISPLAY_LENGTH]


def _titleize(token: str) -> str:
    size_match = _SIZE_TOKEN_RE.match(token)
    if size_match:
        return f"{size_match.group(1)}B"
    if token[0].islower():
        return token[0].upper() + token[1:]
    return token


def describe_model(identifier: str | None) -> ModelDescription | None:
    """Derive a readable label and quantization from an already-sanitized
    model identifier, or `None` when no label can be formed.

    `Qwen3.5-4B-Q4_K_M.gguf` -> label `Qwen3.5 4B`, quantization `Q4_K_M`.
    A repository-style id such as `unsloth/Qwen3.5-4B-GGUF` is expected to
    be sanitized to its last segment first.
    """
    if not identifier:
        return None
    stem = _GGUF_EXTENSION_RE.sub("", identifier.strip())
    quantization: str | None = None
    quant_match = _QUANTIZATION_RE.search(stem)
    if quant_match:
        quantization = quant_match.group(1).upper()
        stem = stem[: quant_match.start()] + stem[quant_match.end() :]
    stem = _GGUF_TOKEN_RE.sub("", stem)
    tokens = [token for token in _TOKEN_SPLIT_RE.split(stem) if token]
    if not tokens:
        return None
    label = " ".join(_titleize(token) for token in tokens)[:MAX_DISPLAY_LENGTH]
    return ModelDescription(label=label, quantization=quantization)


_LOCAL_RUNTIMES: Final[dict[str, tuple[str, str]]] = {
    "llama_cpp": ("Local AI", "llama.cpp"),
    "mock": ("Test AI", "Mock provider"),
}


def describe_provenance(provider_name: str, model_identifier: str | None) -> AiProvenanceDisplay:
    """Build the user-facing provenance display for `provider_name` and the
    raw configured `model_identifier` (which is sanitized here).

    `provider_name` is a closed, application-defined value
    (`Settings.llm_provider`), never operator free text, but an unknown
    value is still rendered through the same sanitizer rather than trusted.
    """
    sanitized = sanitize_model_identifier(model_identifier)
    deployment_label, runtime_label = _LOCAL_RUNTIMES.get(
        provider_name,
        ("AI", sanitize_model_identifier(provider_name) or "unknown runtime"),
    )
    if provider_name == "mock":
        # The mock provider's identifier is a fixed, human-chosen test name
        # ("mock-v1"), not a model file name: show it as is.
        return AiProvenanceDisplay(
            deployment_label=deployment_label,
            runtime_label=runtime_label,
            model_label=sanitized,
            quantization=None,
            model_identifier=sanitized,
        )
    description = describe_model(sanitized)
    return AiProvenanceDisplay(
        deployment_label=deployment_label,
        runtime_label=runtime_label,
        model_label=description.label if description else None,
        quantization=description.quantization if description else None,
        model_identifier=sanitized,
    )


__all__ = [
    "MAX_DISPLAY_LENGTH",
    "AiProvenanceDisplay",
    "ModelDescription",
    "describe_model",
    "describe_provenance",
    "sanitize_model_identifier",
]
