"""Tests for the generic `encode`/`decode` codec (`DB-01`, `WP-074`
AC-01..AC-03)."""

from __future__ import annotations

import base64
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime

import pytest

from trusttable_backend.domain.evidence import Evidence, EvidenceType
from trusttable_backend.domain.parsing import SampleMetadata, SamplingScope
from trusttable_backend.domain.value_objects import ColumnReference, RowReference, Severity
from trusttable_backend.persistence.serializers import decode, encode

# ---------------------------------------------------------------------------
# Primitives round-trip unchanged
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", [None, True, False, 0, 1, -5, 3.14, "", "hello"])
def test_primitives_round_trip_unchanged(value: object) -> None:
    encoded = encode(value)
    assert encoded == value
    assert decode(encoded) == value


def test_bytes_round_trip() -> None:
    original = b"\x00\x01raw bytes\xff"

    encoded = encode(original)

    assert encoded == {"__t": "bytes", "v": base64.b64encode(original).decode("ascii")}
    assert decode(encoded) == original


def test_datetime_round_trip_preserves_timezone() -> None:
    original = datetime(2026, 9, 25, 12, 0, 0, tzinfo=UTC)

    encoded = encode(original)
    decoded = decode(encoded)

    assert decoded == original
    assert decoded.tzinfo == UTC


def test_enum_round_trip() -> None:
    original = Severity.CRITICAL

    encoded = encode(original)
    decoded = decode(encoded)

    assert encoded == {
        "__t": "enum",
        "m": "trusttable_backend.domain.value_objects",
        "q": "Severity",
        "v": "critical",
    }
    assert decoded is Severity.CRITICAL


def test_tuple_round_trip_preserves_type_and_order() -> None:
    original = (1, "two", 3.0)

    decoded = decode(encode(original))

    assert decoded == original
    assert isinstance(decoded, tuple)


def test_empty_tuple_round_trips() -> None:
    assert decode(encode(())) == ()


def test_frozenset_round_trip() -> None:
    original = frozenset({"a", "b", "c"})

    decoded = decode(encode(original))

    assert decoded == original
    assert isinstance(decoded, frozenset)


def test_list_round_trip_preserves_type() -> None:
    original = [1, 2, 3]

    decoded = decode(encode(original))

    assert decoded == original
    assert isinstance(decoded, list)


def test_plain_dict_round_trips_and_is_distinguished_from_a_dataclass() -> None:
    original = {"a": 1, "b": [1, 2, {"nested": True}]}

    encoded = encode(original)
    decoded = decode(encoded)

    assert encoded["__t"] == "dict"
    assert decoded == original
    assert isinstance(decoded, dict)


# ---------------------------------------------------------------------------
# Dataclasses: reconstruction reuses the real constructor (AC-03 basis)
# ---------------------------------------------------------------------------


def test_simple_dataclass_round_trips() -> None:
    original = ColumnReference(original_name="Unit Price", internal_key="unit_price", ordinal=3)

    decoded = decode(encode(original))

    assert decoded == original
    assert type(decoded) is ColumnReference


def test_nested_dataclass_round_trips() -> None:
    original = RowReference(row_number=5, source_line_number=6, fingerprint="abc123")
    evidence = Evidence(
        evidence_id="ev-1",
        evidence_type=EvidenceType.METRIC,
        calculation_version="1.0",
        structured_payload={"mean": 4.2, "count": 10, "tags": ["a", "b"]},
        affected_columns=(ColumnReference(original_name="Total", internal_key="total", ordinal=0),),
        affected_row_references=(original,),
        scope=SamplingScope.FULL,
        display_safe_summary="Mean is 4.2",
    )

    decoded = decode(encode(evidence))

    assert decoded == evidence
    assert type(decoded) is Evidence
    assert type(decoded.affected_columns[0]) is ColumnReference
    assert decoded.structured_payload == evidence.structured_payload


def test_decoded_dataclass_is_still_frozen() -> None:
    decoded = decode(encode(ColumnReference(original_name="x", internal_key="x", ordinal=0)))

    with pytest.raises(FrozenInstanceError):
        decoded.ordinal = 1  # type: ignore[misc]


def test_decode_reruns_post_init_and_raises_on_invariant_violation() -> None:
    """AC-03's structural basis: a hand-crafted encoded node whose fields
    would violate the real dataclass's own `__post_init__` raises on
    decode — exactly what a corrupted persisted row must do.
    """
    malformed = {
        "__t": "dataclass",
        "m": "trusttable_backend.domain.value_objects",
        "q": "ColumnReference",
        "f": {
            "original_name": encode(""),  # invalid: must not be empty
            "internal_key": encode("x"),
            "ordinal": encode(0),
        },
    }

    with pytest.raises(ValueError, match="original_name"):
        decode(malformed)


def test_sample_metadata_dataclass_with_enum_field_round_trips() -> None:
    original = SampleMetadata(
        scope=SamplingScope.SAMPLED, population_size=100, sample_size=10, method="reservoir"
    )

    decoded = decode(encode(original))

    assert decoded == original
    assert decoded.scope is SamplingScope.SAMPLED


# ---------------------------------------------------------------------------
# Security: refuse to resolve a class outside this project's own package
# ---------------------------------------------------------------------------


def test_decode_refuses_to_resolve_a_disallowed_module() -> None:
    hostile = {"__t": "enum", "m": "builtins", "q": "int", "v": 1}

    with pytest.raises(ValueError, match="disallowed module"):
        decode(hostile)


def test_encode_rejects_an_unsupported_type() -> None:
    class Unsupported:
        pass

    with pytest.raises(TypeError):
        encode(Unsupported())


def test_decode_rejects_an_unknown_tag() -> None:
    with pytest.raises(ValueError, match="unknown encoded tag"):
        decode({"__t": "not_a_real_tag", "v": 1})


def test_decode_passes_through_a_dict_with_no_tag_key_unchanged() -> None:
    # A dict without "__t" is not one of this codec's own encoded nodes —
    # `decode` returns it unchanged rather than misinterpreting it.
    assert decode({"plain": "dict"}) == {"plain": "dict"}
