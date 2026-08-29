"""The untrusted-data envelope (`SEC-02`), matching
`docs/architecture.md` §7's exact shape (`task`/`computed_evidence`/
`confirmed_context`/`untrusted_dataset_samples`) and
`docs/product-requirements.md` §12's contract ("The model receives only
required information. Sample values are disabled by default. When
enabled, samples are: length-limited, redacted, serialized in a
dedicated untrusted-data field, never concatenated into system
instructions.").

Framework-independent: no FastAPI/SQLAlchemy/pydantic import. Stdlib
only (`dataclasses`, `collections.abc`).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass

from ..domain.evidence import Evidence
from ..domain.value_objects import ColumnReference

#: Matches `Settings.llm_max_sample_values`'s existing default
#: (`config.py`, `FND-02`) so a future API-layer package wiring
#: `Settings` into this module needs no value translation.
DEFAULT_MAX_SAMPLE_COUNT = 10

#: A new constant (no document specifies an exact number): a prompt
#: "sample" is a short representative excerpt sent to a small local
#: model, not the full analysis-time value. Deliberately much smaller
#: than `Settings.max_text_value_length_for_analysis` (`10_000`), which
#: governs a different, unrelated concern (general analysis-time value
#: handling).
DEFAULT_MAX_SAMPLE_VALUE_LENGTH = 200

#: A pluggable extension point applied to every untrusted sample value
#: before inclusion. Substantive redaction logic is deferred to a future
#: `PRIV-01`, following `domain.evidence.Evidence`'s own already-disclosed
#: precedent for the same deferral; the default implementation below is
#: an identity no-op.
RedactionHook = Callable[[str], str]


def default_redaction_hook(value: str) -> str:
    """Identity redaction hook (no-op). See `RedactionHook`."""
    return value


@dataclass(frozen=True, slots=True)
class UntrustedSample:
    """One untrusted dataset value considered for inclusion in a prompt.

    `value` has already been passed through a `RedactionHook` and
    truncated to at most the configured maximum length by the time this
    object is constructed (see `build_untrusted_samples`); `truncated`
    records whether truncation actually occurred.
    """

    column: ColumnReference
    value: str
    truncated: bool


@dataclass(frozen=True, slots=True)
class PromptEnvelope:
    """The untrusted-data envelope sent to a (future) model provider,
    matching `docs/architecture.md` §7's exact shape.

    Fields:
        task: trusted, application-authored instruction text (e.g.
            "Explain supplied deterministic findings.") — never
            dataset-derived.
        computed_evidence: trusted, already-computed `Evidence` objects
            grounding the task.
        confirmed_context: a generic, caller-supplied mapping. Kept
            generic (not `DatasetContext`, `CTX-01`, not yet built) —
            architecture.md §7 classifies this as untrusted user context
            regardless of confirmation state.
        untrusted_dataset_samples: dataset-derived sample values,
            already redacted/truncated. Structurally guaranteed empty
            whenever `sample_sending_enabled` is `False`.
        sample_sending_enabled: `False` by default
            (`docs/product-requirements.md` §12's "Sample values are
            disabled by default").
    """

    task: str
    computed_evidence: tuple[Evidence, ...]
    confirmed_context: Mapping[str, object]
    untrusted_dataset_samples: tuple[UntrustedSample, ...]
    sample_sending_enabled: bool = False

    def __post_init__(self) -> None:
        if not self.task:
            raise ValueError("PromptEnvelope.task must not be empty")
        if not self.sample_sending_enabled and self.untrusted_dataset_samples:
            raise ValueError(
                "PromptEnvelope.untrusted_dataset_samples must be empty when "
                "sample_sending_enabled is False"
            )


def build_untrusted_samples(
    raw_samples: Sequence[tuple[ColumnReference, str]],
    *,
    sample_sending_enabled: bool,
    max_sample_count: int = DEFAULT_MAX_SAMPLE_COUNT,
    max_sample_value_length: int = DEFAULT_MAX_SAMPLE_VALUE_LENGTH,
    redaction_hook: RedactionHook = default_redaction_hook,
) -> tuple[UntrustedSample, ...]:
    """Build the `untrusted_dataset_samples` tuple for a `PromptEnvelope`.

    Returns an empty tuple whenever `sample_sending_enabled` is `False`,
    regardless of how many `raw_samples` are supplied — sample sending is
    disabled by default as a structural guarantee, not merely a default
    argument value (`PromptEnvelope.__post_init__` enforces the same
    invariant independently). Otherwise, takes at most
    `max_sample_count` entries in input order, passes each value through
    `redaction_hook`, then truncates to at most `max_sample_value_length`
    characters.
    """
    if not sample_sending_enabled:
        return ()
    built: list[UntrustedSample] = []
    for column, raw_value in raw_samples[:max_sample_count]:
        redacted = redaction_hook(raw_value)
        truncated = len(redacted) > max_sample_value_length
        value = redacted[:max_sample_value_length] if truncated else redacted
        built.append(UntrustedSample(column=column, value=value, truncated=truncated))
    return tuple(built)


def build_prompt_envelope(
    *,
    task: str,
    computed_evidence: Sequence[Evidence] = (),
    confirmed_context: Mapping[str, object] | None = None,
    raw_samples: Sequence[tuple[ColumnReference, str]] = (),
    sample_sending_enabled: bool = False,
    max_sample_count: int = DEFAULT_MAX_SAMPLE_COUNT,
    max_sample_value_length: int = DEFAULT_MAX_SAMPLE_VALUE_LENGTH,
    redaction_hook: RedactionHook = default_redaction_hook,
) -> PromptEnvelope:
    """Convenience constructor: builds untrusted samples via
    `build_untrusted_samples` and assembles a `PromptEnvelope`.
    """
    samples = build_untrusted_samples(
        raw_samples,
        sample_sending_enabled=sample_sending_enabled,
        max_sample_count=max_sample_count,
        max_sample_value_length=max_sample_value_length,
        redaction_hook=redaction_hook,
    )
    return PromptEnvelope(
        task=task,
        computed_evidence=tuple(computed_evidence),
        confirmed_context=confirmed_context if confirmed_context is not None else {},
        untrusted_dataset_samples=samples,
        sample_sending_enabled=sample_sending_enabled,
    )


__all__ = [
    "DEFAULT_MAX_SAMPLE_COUNT",
    "DEFAULT_MAX_SAMPLE_VALUE_LENGTH",
    "PromptEnvelope",
    "RedactionHook",
    "UntrustedSample",
    "build_prompt_envelope",
    "build_untrusted_samples",
    "default_redaction_hook",
]
