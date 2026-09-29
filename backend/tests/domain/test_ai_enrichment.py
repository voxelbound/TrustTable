"""`AiEnrichmentRecord` and `model_location_for` (`EXP-01` slice 4)."""

from __future__ import annotations

import pytest

from trusttable_backend.ai_provider.location import model_location_for
from trusttable_backend.domain.ai_enrichment import (
    AiEnrichmentRecord,
    EnrichmentModelLocation,
    EnrichmentOutcome,
)

LOCAL = EnrichmentModelLocation.LOCAL
UNKNOWN = EnrichmentModelLocation.UNKNOWN


def test_the_zero_record_means_no_attempts() -> None:
    record = AiEnrichmentRecord()

    assert record.attempt_count == 0
    assert record.model_location is None
    assert not record.evidence_sent_to_model
    assert not record.confirmed_context_sent_to_model


@pytest.mark.parametrize(
    "outcome, field",
    [
        (EnrichmentOutcome.ACCEPTED, "accepted_count"),
        (EnrichmentOutcome.REJECTED, "rejected_count"),
        (EnrichmentOutcome.PROVIDER_ERROR, "provider_error_count"),
    ],
)
def test_each_outcome_increments_only_its_own_counter(
    outcome: EnrichmentOutcome, field: str
) -> None:
    record = AiEnrichmentRecord().with_call(
        outcome, evidence_sent=False, confirmed_context_sent=False, location=LOCAL
    )

    counts = {
        name: getattr(record, name)
        for name in ("accepted_count", "rejected_count", "provider_error_count")
    }
    assert counts == {name: int(name == field) for name in counts}
    assert record.attempt_count == 1
    assert record.model_location is LOCAL


def test_sent_flags_only_ever_turn_on() -> None:
    record = AiEnrichmentRecord().with_call(
        EnrichmentOutcome.ACCEPTED, evidence_sent=True, confirmed_context_sent=True, location=LOCAL
    )

    later = record.with_call(
        EnrichmentOutcome.REJECTED,
        evidence_sent=False,
        confirmed_context_sent=False,
        location=LOCAL,
    )

    assert later.evidence_sent_to_model
    assert later.confirmed_context_sent_to_model
    assert later.attempt_count == 2


def test_a_failed_attempt_can_record_that_nothing_was_sent() -> None:
    record = AiEnrichmentRecord().with_call(
        EnrichmentOutcome.PROVIDER_ERROR,
        evidence_sent=False,
        confirmed_context_sent=False,
        location=UNKNOWN,
    )

    assert record.provider_error_count == 1
    assert not record.evidence_sent_to_model


def test_differing_locations_become_unknown_not_either_one() -> None:
    first = AiEnrichmentRecord().with_call(
        EnrichmentOutcome.ACCEPTED, evidence_sent=True, confirmed_context_sent=False, location=LOCAL
    )

    second = first.with_call(
        EnrichmentOutcome.ACCEPTED,
        evidence_sent=True,
        confirmed_context_sent=False,
        location=UNKNOWN,
    )

    assert first.model_location is LOCAL
    assert second.model_location is UNKNOWN
    assert (
        second.with_call(
            EnrichmentOutcome.ACCEPTED,
            evidence_sent=True,
            confirmed_context_sent=False,
            location=LOCAL,
        ).model_location
        is UNKNOWN
    )


@pytest.mark.parametrize(
    "kwargs",
    [
        {"accepted_count": -1},
        {"evidence_sent_to_model": True},
        {"confirmed_context_sent_to_model": True},
        {"model_location": LOCAL},
        {"accepted_count": 1},
    ],
)
def test_invalid_records_are_refused(kwargs: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        AiEnrichmentRecord(**kwargs)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "provider, url, expected",
    [
        ("mock", "http://anything.example", LOCAL),
        ("llama_cpp", "http://127.0.0.1:8081", LOCAL),
        ("llama_cpp", "http://localhost:8081", LOCAL),
        ("llama_cpp", "http://LOCALHOST:8081/v1", LOCAL),
        ("llama_cpp", "http://[::1]:8081", LOCAL),
        ("llama_cpp", "http://127.5.5.5:8081", LOCAL),
        ("llama_cpp", "http://host.docker.internal:8081", LOCAL),
        ("llama_cpp", "http://192.168.1.20:8081", UNKNOWN),
        ("llama_cpp", "http://llm.example.com", UNKNOWN),
        ("llama_cpp", "http://127.0.0.1.evil.example", UNKNOWN),
        ("llama_cpp", "http://localhost.evil.example", UNKNOWN),
        ("llama_cpp", "not a url", UNKNOWN),
        ("llama_cpp", "http://[bad", UNKNOWN),
        ("disabled", "http://127.0.0.1:8081", UNKNOWN),
        ("something_else", "http://127.0.0.1:8081", UNKNOWN),
    ],
)
def test_model_location_is_local_only_for_a_known_runtime_on_this_machine(
    provider: str, url: str, expected: EnrichmentModelLocation
) -> None:
    assert model_location_for(provider, url) is expected
