"""Tests for the untrusted-data envelope (SEC-02).

Covers this package's acceptance criteria AC-02..AC-08: `PromptEnvelope`
construction invariants and `build_untrusted_samples`'s sample-
suppression, truncation, count-limiting, and redaction-hook behavior.
"""

from __future__ import annotations

import pytest

from trusttable_backend.ai_boundary.envelope import (
    PromptEnvelope,
    UntrustedSample,
    build_untrusted_samples,
    default_redaction_hook,
)
from trusttable_backend.domain.evidence import Evidence, EvidenceType
from trusttable_backend.domain.parsing import SamplingScope
from trusttable_backend.domain.value_objects import ColumnReference


def make_evidence(**overrides: object) -> Evidence:
    fields: dict[str, object] = {
        "evidence_id": "ev-1",
        "evidence_type": EvidenceType.METRIC,
        "calculation_version": "1",
        "structured_payload": {"mean": 1.5},
        "affected_columns": (),
        "affected_row_references": (),
        "scope": SamplingScope.FULL,
        "display_safe_summary": "Mean value is 1.5",
    }
    fields.update(overrides)
    return Evidence(**fields)  # type: ignore[arg-type]


def make_column(key: str = "notes") -> ColumnReference:
    return ColumnReference(original_name=key, internal_key=key, ordinal=0)


# ---------------------------------------------------------------------------
# AC-02..AC-04: PromptEnvelope
# ---------------------------------------------------------------------------


def test_prompt_envelope_constructs_with_valid_fields() -> None:
    envelope = PromptEnvelope(
        task="Explain supplied deterministic findings.",
        computed_evidence=(make_evidence(),),
        confirmed_context={},
        untrusted_dataset_samples=(),
        sample_sending_enabled=False,
    )

    assert envelope.task == "Explain supplied deterministic findings."
    assert envelope.computed_evidence == (make_evidence(),)
    assert envelope.confirmed_context == {}
    assert envelope.untrusted_dataset_samples == ()
    assert envelope.sample_sending_enabled is False


def test_prompt_envelope_rejects_samples_when_sample_sending_disabled() -> None:
    sample = UntrustedSample(column=make_column(), value="hello", truncated=False)

    with pytest.raises(ValueError, match="sample_sending_enabled"):
        PromptEnvelope(
            task="Explain supplied deterministic findings.",
            computed_evidence=(),
            confirmed_context={},
            untrusted_dataset_samples=(sample,),
            sample_sending_enabled=False,
        )


def test_prompt_envelope_accepts_samples_when_sample_sending_enabled() -> None:
    sample = UntrustedSample(column=make_column(), value="hello", truncated=False)

    envelope = PromptEnvelope(
        task="Explain supplied deterministic findings.",
        computed_evidence=(),
        confirmed_context={},
        untrusted_dataset_samples=(sample,),
        sample_sending_enabled=True,
    )

    assert envelope.untrusted_dataset_samples == (sample,)


def test_prompt_envelope_rejects_empty_task() -> None:
    with pytest.raises(ValueError, match="task"):
        PromptEnvelope(
            task="",
            computed_evidence=(),
            confirmed_context={},
            untrusted_dataset_samples=(),
            sample_sending_enabled=False,
        )


# ---------------------------------------------------------------------------
# AC-05: build_untrusted_samples — sample suppression
# ---------------------------------------------------------------------------


def test_build_untrusted_samples_empty_when_sample_sending_disabled() -> None:
    raw_samples = [(make_column("a"), "value a"), (make_column("b"), "value b")]

    result = build_untrusted_samples(raw_samples, sample_sending_enabled=False)

    assert result == ()


# ---------------------------------------------------------------------------
# AC-06: truncation
# ---------------------------------------------------------------------------


def test_build_untrusted_samples_truncates_over_length_values() -> None:
    long_value = "x" * 250
    raw_samples = [(make_column("a"), long_value)]

    result = build_untrusted_samples(
        raw_samples, sample_sending_enabled=True, max_sample_value_length=200
    )

    assert len(result) == 1
    assert result[0].value == "x" * 200
    assert result[0].truncated is True


def test_build_untrusted_samples_does_not_mark_exact_length_value_truncated() -> None:
    exact_value = "x" * 200
    raw_samples = [(make_column("a"), exact_value)]

    result = build_untrusted_samples(
        raw_samples, sample_sending_enabled=True, max_sample_value_length=200
    )

    assert result[0].value == exact_value
    assert result[0].truncated is False


# ---------------------------------------------------------------------------
# AC-07: count limiting
# ---------------------------------------------------------------------------


def test_build_untrusted_samples_limits_to_max_sample_count_in_order() -> None:
    raw_samples = [(make_column(f"col{i}"), f"value {i}") for i in range(5)]

    result = build_untrusted_samples(raw_samples, sample_sending_enabled=True, max_sample_count=3)

    assert len(result) == 3
    assert [sample.value for sample in result] == ["value 0", "value 1", "value 2"]


# ---------------------------------------------------------------------------
# AC-08: redaction hook
# ---------------------------------------------------------------------------


def test_default_redaction_hook_is_identity() -> None:
    assert default_redaction_hook("hello") == "hello"


def test_build_untrusted_samples_invokes_custom_redaction_hook() -> None:
    raw_samples = [(make_column("a"), "hello")]

    result = build_untrusted_samples(
        raw_samples,
        sample_sending_enabled=True,
        redaction_hook=lambda value: value.upper(),
    )

    assert result[0].value == "HELLO"
