"""Tests for human-readable AI provenance (`AI-08`,
`docs/decision-log.md` D-040): path sanitization, model label derivation and
provider labels.

The point of this module is that no absolute host filesystem path — Windows,
UNC, POSIX, `file://`, URL-with-credentials, tilde — can survive into what
leaves the backend, while the documented baseline model still reads as
"Qwen3.5 4B" with its quantization reported separately.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from trusttable_backend.ai_provider.display import (
    MAX_DISPLAY_LENGTH,
    describe_model,
    describe_provenance,
    sanitize_model_identifier,
)

HOSTILE_IDENTIFIERS = [
    r"C:\LocalAI\TrustTable\models\Qwen3.5-9B-Q4_K_M.gguf",
    r"c:/LocalAI/TrustTable/models/Qwen3.5-9B-Q4_K_M.gguf",
    r"\\fileserver\models\team-a\Qwen3.5-9B-Q4_K_M.gguf",
    r"D:models\Qwen3.5-9B-Q4_K_M.gguf",
    "/opt/trusttable/models/Qwen3.5-9B-Q4_K_M.gguf",
    "/home/alice/.cache/llama.cpp/Qwen3.5-9B-Q4_K_M.gguf",
    "~/models/Qwen3.5-9B-Q4_K_M.gguf",
    "file:///srv/models/Qwen3.5-9B-Q4_K_M.gguf",
    "file://C:/LocalAI/models/Qwen3.5-9B-Q4_K_M.gguf",
    "https://user:s3cret@models.internal.example/repo/Qwen3.5-9B-Q4_K_M.gguf",
    "  /opt/models//nested///Qwen3.5-9B-Q4_K_M.gguf  ",
    "/opt/models/Qwen3.5-9B-Q4_K_M.gguf\n",
    "/opt/mo\u200bdels/Qwen3.5-9B-Q4_K_M.gguf",
]

FORBIDDEN_FRAGMENTS = [
    "LocalAI",
    "TrustTable",
    "fileserver",
    "team-a",
    "/opt",
    "/home",
    "alice",
    "s3cret",
    "user:",
    "models.internal",
    "srv",
    "C:",
    "D:",
    "\\",
    "/",
    "~",
]


@pytest.mark.parametrize("raw", HOSTILE_IDENTIFIERS)
def test_every_hostile_path_form_reduces_to_the_file_name_only(raw: str) -> None:
    sanitized = sanitize_model_identifier(raw)
    assert sanitized == "Qwen3.5-9B-Q4_K_M.gguf"
    for fragment in FORBIDDEN_FRAGMENTS:
        assert fragment not in sanitized


@pytest.mark.parametrize("raw", HOSTILE_IDENTIFIERS)
def test_no_path_fragment_survives_into_any_provenance_field(raw: str) -> None:
    display = describe_provenance("llama_cpp", raw)
    rendered = " | ".join(
        str(part)
        for part in (
            display.deployment_label,
            display.runtime_label,
            display.model_label,
            display.quantization,
            display.model_identifier,
        )
    )
    for fragment in FORBIDDEN_FRAGMENTS:
        assert fragment not in rendered, (fragment, rendered)
    assert display.model_label == "Qwen3.5 9B"
    assert display.quantization == "Q4_K_M"


@pytest.mark.parametrize(
    "raw", [None, "", "   ", "\n\t", "/", "\\", "///", "file://", "~", "..", "."]
)
def test_nothing_usable_yields_none(raw: str | None) -> None:
    assert sanitize_model_identifier(raw) is None


def test_url_authority_is_never_the_surviving_segment() -> None:
    assert sanitize_model_identifier("https://user:pw@host.example") is None
    assert sanitize_model_identifier("https://user:pw@host.example/") is None


def test_control_characters_are_removed() -> None:
    assert sanitize_model_identifier("mo\x00del\x07-1B\x1b.gguf") == "model-1B.gguf"


def test_over_long_identifiers_are_bounded() -> None:
    sanitized = sanitize_model_identifier("/a/" + "x" * 500 + ".gguf")
    assert sanitized is not None
    assert len(sanitized) == MAX_DISPLAY_LENGTH


def test_whitespace_inside_the_name_is_collapsed() -> None:
    assert sanitize_model_identifier("/opt/models/My   Model \t 4B.gguf") == "My Model 4B.gguf"


def test_huggingface_style_repo_ids_keep_only_the_last_segment() -> None:
    assert sanitize_model_identifier("unsloth/Qwen3.5-4B-GGUF") == "Qwen3.5-4B-GGUF"
    assert sanitize_model_identifier("unsloth/Qwen3.5-4B-GGUF:Q4_K_M") == "Qwen3.5-4B-GGUF:Q4_K_M"


# --- model label and quantization ------------------------------------------


def test_documented_baseline_reads_as_qwen35_4b_with_separate_quantization() -> None:
    description = describe_model("Qwen3.5-4B-Q4_K_M")
    assert description is not None
    assert description.label == "Qwen3.5 4B"
    assert description.quantization == "Q4_K_M"


@pytest.mark.parametrize(
    ("identifier", "label", "quantization"),
    [
        ("Qwen3.5-4B-Q4_K_M.gguf", "Qwen3.5 4B", "Q4_K_M"),
        ("Qwen3.5-9B-Q4_K_M.gguf", "Qwen3.5 9B", "Q4_K_M"),
        ("qwen3.5-9b", "Qwen3.5 9B", None),
        ("Qwen3.5-9B-Instruct-Q5_K_S.gguf", "Qwen3.5 9B Instruct", "Q5_K_S"),
        ("llama-3.1-8b-instruct-q8_0.gguf", "Llama 3.1 8B Instruct", "Q8_0"),
        ("Mistral-7B-v0.3-IQ4_XS.gguf", "Mistral 7B V0.3", "IQ4_XS"),
        ("gemma-2-2b-it-BF16.gguf", "Gemma 2 2B It", "BF16"),
        ("unsloth_Qwen3.5-4B-GGUF", "Unsloth Qwen3.5 4B", None),
        ("Qwen3.5-4B-GGUF:Q4_K_M", "Qwen3.5 4B", "Q4_K_M"),
        ("Phi-4-mini-F16.gguf", "Phi 4 Mini", "F16"),
    ],
)
def test_model_label_and_quantization_derivation(
    identifier: str, label: str, quantization: str | None
) -> None:
    description = describe_model(identifier)
    assert description is not None
    assert (description.label, description.quantization) == (label, quantization)


@pytest.mark.parametrize("identifier", [None, "", ".gguf", "Q4_K_M.gguf", "GGUF"])
def test_no_label_can_be_formed_from_nothing_meaningful(identifier: str | None) -> None:
    description = describe_model(identifier)
    assert description is None or description.label


def test_a_quantization_tag_is_not_confused_with_a_model_family() -> None:
    description = describe_model("Qwen3.5-4B")
    assert description is not None
    assert description.quantization is None
    assert description.label == "Qwen3.5 4B"


# --- provider labels --------------------------------------------------------


def test_llama_cpp_is_presented_as_local_ai_over_llama_cpp() -> None:
    display = describe_provenance("llama_cpp", "/models/Qwen3.5-4B-Q4_K_M.gguf")
    assert display.deployment_label == "Local AI"
    assert display.runtime_label == "llama.cpp"
    assert display.model_label == "Qwen3.5 4B"
    assert display.quantization == "Q4_K_M"
    assert display.model_identifier == "Qwen3.5-4B-Q4_K_M.gguf"


def test_mock_provider_is_presented_as_test_ai_with_its_own_name() -> None:
    display = describe_provenance("mock", "mock-v1")
    assert display.deployment_label == "Test AI"
    assert display.runtime_label == "Mock provider"
    assert display.model_label == "mock-v1"
    assert display.quantization is None


def test_unknown_provider_name_is_sanitized_not_trusted() -> None:
    display = describe_provenance("/etc/secret/provider", "x.gguf")
    assert display.deployment_label == "AI"
    assert display.runtime_label == "provider"
    assert "/" not in display.runtime_label


def test_missing_identifier_gives_labels_without_a_model() -> None:
    display = describe_provenance("llama_cpp", None)
    assert display.model_label is None
    assert display.model_identifier is None
    assert display.runtime_label == "llama.cpp"


def test_module_is_pure_stdlib_and_never_touches_the_filesystem() -> None:
    source = (
        Path(__file__).resolve().parents[2]
        / "src"
        / "trusttable_backend"
        / "ai_provider"
        / "display.py"
    ).read_text(encoding="utf-8")
    imports = [line for line in source.splitlines() if re.match(r"\s*(from|import)\s+\S", line)]
    joined = "\n".join(imports)
    for forbidden in ("os", "pathlib", "fastapi", "httpx", "pydantic", "sqlalchemy", "subprocess"):
        assert not re.search(rf"\b(from|import)\s+{forbidden}\b", joined)
