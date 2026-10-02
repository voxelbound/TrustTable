"""Tests for `DET-03` slice 3: `consistency.numeric_values_stored_as_text`
and `consistency.near_duplicate_categories`.

Follows `docs/detector-framework.md` §15's detector test contract (positive,
negative, threshold boundary, null/empty and malformed input, repeatability,
configuration and known false positives). The false-positive cases that
matter most are pinned by name: zero-padded codes and phone numbers are not
"numbers stored as text", and casing-only or whitespace-only differences are
not "near-duplicate categories" because other detectors own them.
"""

from __future__ import annotations

import time
from collections.abc import Mapping

import pytest

from tests.detectors.test_det03_slice1 import (
    ANALYSIS_TIMESTAMP,
    NO_EXPOSURE,
    make_profile,
    make_request,
)
from trusttable_backend.detectors.catalogue import DETECTORS
from trusttable_backend.detectors.consistency import (
    NearDuplicateCategoriesDetector,
    NumericValuesStoredAsTextDetector,
    _near_duplicate_key,
    _read_number,
)
from trusttable_backend.detectors.contract import DetectorCategory, DetectorRunStatus
from trusttable_backend.detectors.engine import run_detectors
from trusttable_backend.domain.evidence import EvidenceType
from trusttable_backend.domain.value_objects import Severity
from trusttable_backend.parsers.csv_parser import parse_csv
from trusttable_backend.profiling.metrics import compute_dataset_profile
from trusttable_backend.profiling.schemas import DatasetProfile, InferredColumnType

Rows = tuple[Mapping[str, object], ...]

# ---------------------------------------------------------------------------
# Reading a number
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "decorations"),
    [
        ("12", ()),
        ("-3.5", ()),
        ("+0.25", ()),
        (".5", ()),
        ("0", ()),
        ("0.5", ()),
        ("$12.50", ("currency symbol",)),
        ("€1,234.50", ("currency symbol", "thousands separator")),
        ("£-7", ("currency symbol",)),
        ("-$7", ("currency symbol",)),
        ("12%", ("percent sign",)),
        ("12.5%", ("percent sign",)),
        ("1,234,567", ("thousands separator",)),
        ("$1,000%", ("currency symbol", "percent sign", "thousands separator")),
        ("  $5  ", ("currency symbol",)),
    ],
)
def test_read_number_accepts_decorated_and_plain_numbers(
    value: str, decorations: tuple[str, ...]
) -> None:
    assert _read_number(value) == (True, decorations)


@pytest.mark.parametrize(
    "value",
    [
        "",
        "   ",
        "-",
        "$",
        "%",
        "abc",
        "12abc",
        "USD 12",
        "12 USD",
        "007",  # zero-padded: a code
        "$007",
        "00",
        "1,23",  # not a thousands group
        "12,34",  # European decimal comma: not recognized
        ",123",
        "1,2345",
        "5.",
        "1.2.3",
        "(555) 123-4567",  # phone number
        "555-1234",
        "(12.50)",  # accounting brackets: not recognized
        "1 234",
        "1e5",
        "٣٤",  # non-ASCII digits are not numbers here
    ],
)
def test_read_number_rejects_everything_else(value: str) -> None:
    assert _read_number(value) == (False, ())


def test_read_number_is_linear_on_a_very_long_hostile_value() -> None:
    """No regular expression runs over untrusted values: a 1,000,000-character
    value is rejected in well under a second."""
    hostile = "1," * 500_000 + "x"
    started = time.perf_counter()
    assert _read_number(hostile) == (False, ())
    assert _near_duplicate_key("a-" * 500_000) == "a" * 500_000
    assert time.perf_counter() - started < 2.0


# ---------------------------------------------------------------------------
# consistency.numeric_values_stored_as_text
# ---------------------------------------------------------------------------


def _numbers(
    values: tuple[object, ...], inferred: InferredColumnType = InferredColumnType.IDENTIFIER
) -> tuple[DatasetProfile, Rows]:
    rows: Rows = tuple({"amount": value} for value in values)
    return make_profile(("amount",), row_count=len(rows), inferred_type=inferred), rows


def test_numbers_as_text_metadata_and_config() -> None:
    detector = NumericValuesStoredAsTextDetector()
    assert detector.metadata.detector_id == "consistency.numeric_values_stored_as_text"
    assert detector.metadata.category is DetectorCategory.CONSISTENCY
    assert detector.metadata.requires_raw_rows is True
    assert detector.metadata.documented_limitations
    detector.config_schema.model_validate({})


def test_numbers_as_text_flags_a_column_of_decorated_numbers() -> None:
    profile, rows = _numbers(("$1,234.50", "$99.00", "12", None, "", "$7.25"))

    result = NumericValuesStoredAsTextDetector().run(make_request(profile, rows))

    assert result.status is DetectorRunStatus.SUCCESS
    (finding,) = result.findings
    (evidence,) = result.evidence
    assert [ref.row_number for ref in finding.affected_row_references] == [0, 1, 5]
    assert finding.severity is Severity.MEDIUM
    assert finding.confidence == 0.9
    assert evidence.evidence_type is EvidenceType.ROW_SET
    assert evidence.structured_payload == {
        "checked_value_count": 4,
        "numeric_like_count": 4,
        "decorated_value_count": 3,
        "decorations": ["currency symbol", "thousands separator"],
    }


def test_numbers_as_text_flags_percent_columns() -> None:
    profile, rows = _numbers(("12%", "15%", "9.5%"), InferredColumnType.CATEGORICAL)

    (finding,) = NumericValuesStoredAsTextDetector().run(make_request(profile, rows)).findings

    assert [ref.row_number for ref in finding.affected_row_references] == [0, 1, 2]


@pytest.mark.parametrize(
    "values",
    [
        ("12", "15", "9.5"),  # plain numbers: no decoration (and already numeric)
        ("02134", "10001", "90210"),  # zip codes: plain digits, no decoration
        ("007", "010", "$012"),  # zero-padded codes
        ("(555) 123-4567", "(555) 987-6543", "(555) 111-2222"),  # phone numbers
        ("555-1234", "555-9876"),
        ("$12.50", "n/a", "tbd", "pending", "$3"),  # fewer than 90% read as numbers
        ("$1", "$2", "$3", "$4", "$5", "$6", "$7", "$8", "none", "n/a"),  # 8 of 10 = 80%
        ("USD 12", "USD 13"),
        ("12,34", "56,78"),  # decimal commas are not recognized
        ("", None, "  "),
        (),
    ],
)
def test_numbers_as_text_does_not_flag_codes_plain_numbers_or_non_numeric_text(
    values: tuple[object, ...],
) -> None:
    profile, rows = _numbers(values)

    result = NumericValuesStoredAsTextDetector().run(make_request(profile, rows))

    assert result.status is DetectorRunStatus.SUCCESS
    assert result.findings == ()
    assert result.evidence == ()


def test_numbers_as_text_boundary_exactly_ninety_percent_is_flagged() -> None:
    values = ("$1", "$2", "$3", "$4", "$5", "$6", "$7", "$8", "$9", "none")
    profile, rows = _numbers(values)

    # 9 of 10 is exactly 0.9, which meets the threshold ("at least").
    assert len(NumericValuesStoredAsTextDetector().run(make_request(profile, rows)).findings) == 1


@pytest.mark.parametrize(
    "inferred",
    [
        InferredColumnType.NUMERIC,
        InferredColumnType.DATE,
        InferredColumnType.BOOLEAN,
        InferredColumnType.UNKNOWN,
    ],
)
def test_numbers_as_text_skips_out_of_scope_column_types(inferred: InferredColumnType) -> None:
    profile, rows = _numbers(("$1", "$2"), inferred)

    assert NumericValuesStoredAsTextDetector().run(make_request(profile, rows)).findings == ()


def test_numbers_as_text_ignores_non_string_cells_without_failing() -> None:
    profile, rows = _numbers((12, "$5", "$6"))

    result = NumericValuesStoredAsTextDetector().run(make_request(profile, rows))

    assert [ref.row_number for ref in result.findings[0].affected_row_references] == [1, 2]


def test_numbers_as_text_is_repeatable() -> None:
    profile, rows = _numbers(("$1", "$2"))
    request = make_request(profile, rows)

    assert NumericValuesStoredAsTextDetector().run(
        request
    ) == NumericValuesStoredAsTextDetector().run(request)


# ---------------------------------------------------------------------------
# consistency.near_duplicate_categories
# ---------------------------------------------------------------------------


def _categories(
    values: tuple[object, ...], inferred: InferredColumnType = InferredColumnType.CATEGORICAL
) -> tuple[DatasetProfile, Rows]:
    rows: Rows = tuple({"city": value} for value in values)
    return make_profile(("city",), row_count=len(rows), inferred_type=inferred), rows


def test_near_duplicates_metadata_and_config() -> None:
    detector = NearDuplicateCategoriesDetector()
    assert detector.metadata.detector_id == "consistency.near_duplicate_categories"
    assert detector.metadata.category is DetectorCategory.CONSISTENCY
    assert detector.metadata.requires_raw_rows is True
    assert detector.metadata.applicable_inferred_types == (InferredColumnType.CATEGORICAL,)
    assert detector.metadata.documented_limitations
    detector.config_schema.model_validate({})


def test_near_duplicates_flags_variants_that_differ_by_punctuation_or_spacing() -> None:
    profile, rows = _categories(
        ("New York", "New-York", "NewYork", "New  York", "Boston", "Boston", None, "")
    )

    result = NearDuplicateCategoriesDetector().run(make_request(profile, rows))

    (finding,) = result.findings
    (evidence,) = result.evidence
    assert [ref.row_number for ref in finding.affected_row_references] == [0, 1, 2, 3]
    assert finding.severity is Severity.LOW
    assert finding.confidence == 0.8
    assert evidence.structured_payload == {
        "variant_count": 4,
        "variants_shown": ["new  york", "new york", "new-york", "newyork"],
        "affected_row_count": 4,
    }


def test_near_duplicates_one_finding_per_group() -> None:
    profile, rows = _categories(("N.Y.", "NY", "L.A.", "LA", "Paris", "Paris"))

    result = NearDuplicateCategoriesDetector().run(make_request(profile, rows))

    assert len(result.findings) == 2
    assert [[ref.row_number for ref in f.affected_row_references] for f in result.findings] == [
        [2, 3],
        [0, 1],
    ]  # groups are reported in sorted key order: "la" before "ny"


@pytest.mark.parametrize(
    "values",
    [
        ("New York", "new york", "NEW YORK"),  # casing only: inconsistent_capitalization's
        ("Boston", " Boston", "Boston "),  # outer whitespace only: leading_trailing_whitespace's
        ("Boston", "boston ", " BOSTON"),  # both of the above combined
        ("1.5", "15"),  # digits only: punctuation changes the number
        ("1-2", "12"),
        ("-", "--", "."),  # no letters or digits: empty key
        ("A", "A."),  # key shorter than two characters
        ("Paris", "Berlin", "Rome"),
        ("", None, "  "),
        (),
    ],
)
def test_near_duplicates_does_not_flag_what_other_detectors_own_or_unrelated_values(
    values: tuple[object, ...],
) -> None:
    profile, rows = _categories(values)

    result = NearDuplicateCategoriesDetector().run(make_request(profile, rows))

    assert result.status is DetectorRunStatus.SUCCESS
    assert result.findings == ()
    assert result.evidence == ()


def test_near_duplicates_boundary_two_variants_is_enough_one_is_not() -> None:
    profile, rows = _categories(("a-b", "ab"))
    assert len(NearDuplicateCategoriesDetector().run(make_request(profile, rows)).findings) == 1

    profile, rows = _categories(("a-b", "a-b"))
    assert NearDuplicateCategoriesDetector().run(make_request(profile, rows)).findings == ()


@pytest.mark.parametrize(
    "inferred",
    [
        InferredColumnType.TEXT,
        InferredColumnType.IDENTIFIER,
        InferredColumnType.NUMERIC,
        InferredColumnType.MIXED,
    ],
)
def test_near_duplicates_only_checks_categorical_columns(inferred: InferredColumnType) -> None:
    profile, rows = _categories(("New York", "New-York"), inferred)

    assert NearDuplicateCategoriesDetector().run(make_request(profile, rows)).findings == ()


def test_near_duplicates_bounds_the_variants_it_records() -> None:
    base = "x" * 80
    separators = ["-", ".", "_", " ", "/", ",", ";", ":", "+", "*", "&", "#", ""]
    values = tuple(f"{base}{separator}z" for separator in separators)  # 13 variants, one key
    profile, rows = _categories(values)

    result = NearDuplicateCategoriesDetector().run(make_request(profile, rows))

    (evidence,) = result.evidence
    shown = evidence.structured_payload["variants_shown"]
    assert evidence.structured_payload["variant_count"] == 13
    assert isinstance(shown, list) and len(shown) == 10  # capped
    assert all(len(variant) <= 60 for variant in shown)  # truncated


def test_near_duplicates_ignores_non_string_cells_without_failing() -> None:
    profile, rows = _categories((12, "a-b", "ab"))

    result = NearDuplicateCategoriesDetector().run(make_request(profile, rows))

    assert [ref.row_number for ref in result.findings[0].affected_row_references] == [1, 2]


def test_near_duplicates_is_repeatable() -> None:
    profile, rows = _categories(("a-b", "ab"))
    request = make_request(profile, rows)

    assert NearDuplicateCategoriesDetector().run(request) == NearDuplicateCategoriesDetector().run(
        request
    )


# ---------------------------------------------------------------------------
# Registry interoperation and an end-to-end analysis
# ---------------------------------------------------------------------------


def test_both_detectors_are_registered_with_unique_ids() -> None:
    ids = [detector.metadata.detector_id for detector in DETECTORS]
    assert len(ids) == len(set(ids))
    assert {
        "consistency.numeric_values_stored_as_text",
        "consistency.near_duplicate_categories",
    } <= set(ids)


def test_end_to_end_parse_profile_detect_reports_both_and_not_codes() -> None:
    csv_bytes = (
        b"id,amount,city,zip,phone\n"
        b"1,$1234.50,New York,02134,(555) 100-0001\n"
        b"2,$99.00,New-York,10001,(555) 100-0002\n"
        b"3,$12.10,NewYork,90210,(555) 100-0003\n"
        b"4,$7.25,Boston,02134,(555) 100-0004\n"
        b"5,$8.40,Boston,10001,(555) 100-0005\n"
        b"6,$3.99,Boston,90210,(555) 100-0006\n"
        b"7,$5.05,Boston,02134,(555) 100-0007\n"
        b"8,$6.60,Boston,10001,(555) 100-0008\n"
    )
    parsed = parse_csv(csv_bytes)
    profile = compute_dataset_profile(
        parsed.parsed_dataset.columns,
        parsed.rows,
        parsed.parsed_dataset.sampling,
        as_of=ANALYSIS_TIMESTAMP.date(),
    )
    keyed = tuple(
        {column.internal_key: row[column.ordinal] for column in parsed.parsed_dataset.columns}
        for row in parsed.rows
    )

    results = run_detectors(
        list(DETECTORS),
        dataset_profile=profile,
        rows=keyed,
        row_references=parsed.parsed_dataset.row_references,
        confirmed_context=None,
        security_exposure=NO_EXPOSURE,
        analysis_timestamp=ANALYSIS_TIMESTAMP,
    )

    by_detector = {result.detector_id: result.findings for result in results if result.findings}
    (amounts,) = by_detector["consistency.numeric_values_stored_as_text"]
    assert [column.original_name for column in amounts.affected_columns] == ["amount"]
    (cities,) = by_detector["consistency.near_duplicate_categories"]
    assert [ref.row_number for ref in cities.affected_row_references] == [0, 1, 2]
    # Only the amount column is "numbers as text": the zip and phone columns are
    # not, and no casing finding claims the near-duplicate city values.
    assert len(by_detector["consistency.numeric_values_stored_as_text"]) == 1
    assert "consistency.inconsistent_capitalization" not in by_detector
