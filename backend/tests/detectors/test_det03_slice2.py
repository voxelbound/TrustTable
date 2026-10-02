"""Tests for `DET-03` slice 2: `validity.implausibly_old_dates` and
`validity.invalid_email_shape`.

Follows `docs/detector-framework.md` §15's detector test contract (positive,
negative, threshold boundary, null/empty and malformed input, repeatability,
configuration and known false positives) and adds the privacy proof the
email detector needs: no email value ever appears in a finding or its
evidence.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import fields, is_dataclass

import pytest

from tests.detectors.test_det03_slice1 import (
    ANALYSIS_TIMESTAMP,
    NO_EXPOSURE,
    make_profile,
    make_request,
)
from trusttable_backend.detectors.catalogue import DETECTORS
from trusttable_backend.detectors.contract import DetectorCategory, DetectorRunStatus
from trusttable_backend.detectors.engine import run_detectors
from trusttable_backend.detectors.validity import (
    ImplausiblyOldDatesDetector,
    InvalidEmailShapeDetector,
    _has_email_shape,
)
from trusttable_backend.domain.evidence import EvidenceType
from trusttable_backend.domain.value_objects import Severity
from trusttable_backend.parsers.csv_parser import parse_csv
from trusttable_backend.profiling.metrics import compute_dataset_profile
from trusttable_backend.profiling.schemas import DatasetProfile, InferredColumnType

# ---------------------------------------------------------------------------
# validity.implausibly_old_dates
# ---------------------------------------------------------------------------


def _dates(
    values: tuple[object, ...], inferred: InferredColumnType = InferredColumnType.DATE
) -> tuple[DatasetProfile, tuple[Mapping[str, object], ...]]:
    rows: tuple[Mapping[str, object], ...] = tuple({"when": value} for value in values)
    return make_profile(("when",), row_count=len(rows), inferred_type=inferred), rows


def test_old_dates_metadata_and_config() -> None:
    detector = ImplausiblyOldDatesDetector()
    assert detector.metadata.detector_id == "validity.implausibly_old_dates"
    assert detector.metadata.category is DetectorCategory.VALIDITY
    assert detector.metadata.requires_raw_rows is True
    assert detector.metadata.documented_limitations
    detector.config_schema.model_validate({})


def test_old_dates_flags_dates_before_1900_with_cutoff_and_oldest_in_evidence() -> None:
    profile, rows = _dates(("2024-05-01", "0001-01-01", "1899-12-31", "", None, "1850-06-15"))

    result = ImplausiblyOldDatesDetector().run(make_request(profile, rows))

    assert result.status is DetectorRunStatus.SUCCESS
    (finding,) = result.findings
    (evidence,) = result.evidence
    assert [ref.row_number for ref in finding.affected_row_references] == [1, 2, 5]
    assert finding.severity is Severity.LOW
    assert finding.confidence == 0.8
    assert evidence.evidence_type is EvidenceType.ROW_SET
    assert evidence.structured_payload == {
        "earliest_plausible_date": "1900-01-01",
        "old_date_count": 3,
        "oldest_date_found": "0001-01-01",
    }


@pytest.mark.parametrize(
    "values",
    [
        ("1900-01-01",),  # boundary: the cutoff itself is plausible
        ("1900-01-02", "2026-10-02"),
        ("not a date", "31/12/1850", "1850"),  # unparseable or non-ISO: never read
        ("", None, "   "),
        (),
    ],
)
def test_old_dates_does_not_flag_plausible_blank_or_unreadable_values(
    values: tuple[object, ...],
) -> None:
    profile, rows = _dates(values)

    result = ImplausiblyOldDatesDetector().run(make_request(profile, rows))

    assert result.status is DetectorRunStatus.SUCCESS
    assert result.findings == ()
    assert result.evidence == ()


def test_old_dates_boundary_is_the_day_before_the_cutoff() -> None:
    profile, rows = _dates(("1899-12-31", "1900-01-01"))

    (finding,) = ImplausiblyOldDatesDetector().run(make_request(profile, rows)).findings

    assert [ref.row_number for ref in finding.affected_row_references] == [0]


@pytest.mark.parametrize(
    "inferred",
    [InferredColumnType.TEXT, InferredColumnType.NUMERIC, InferredColumnType.UNKNOWN],
)
def test_old_dates_only_checks_date_columns(inferred: InferredColumnType) -> None:
    profile, rows = _dates(("0001-01-01",), inferred)

    assert ImplausiblyOldDatesDetector().run(make_request(profile, rows)).findings == ()


def test_old_dates_ignores_non_string_cells_without_failing() -> None:
    profile, rows = _dates((1850, "1850-01-01"))

    result = ImplausiblyOldDatesDetector().run(make_request(profile, rows))

    assert [ref.row_number for ref in result.findings[0].affected_row_references] == [1]


def test_old_dates_is_repeatable() -> None:
    profile, rows = _dates(("0001-01-01", "2020-01-01"))
    request = make_request(profile, rows)

    assert ImplausiblyOldDatesDetector().run(request) == ImplausiblyOldDatesDetector().run(request)


# ---------------------------------------------------------------------------
# validity.invalid_email_shape
# ---------------------------------------------------------------------------

_VALID = ("ann@example.com", "bo.lee@mail.example.org", "c@d.io")
_INVALID = ("ann-at-example.com", "ann@", "@example.com", "a@b", "a b@example.com", "a@@b.com")


def _emails(
    values: tuple[object, ...],
    name: str = "customer_email",
    inferred: InferredColumnType = InferredColumnType.TEXT,
) -> tuple[DatasetProfile, tuple[Mapping[str, object], ...]]:
    rows: tuple[Mapping[str, object], ...] = tuple({name: value} for value in values)
    return make_profile((name,), row_count=len(rows), inferred_type=inferred), rows


def test_email_metadata_and_config() -> None:
    detector = InvalidEmailShapeDetector()
    assert detector.metadata.detector_id == "validity.invalid_email_shape"
    assert detector.metadata.category is DetectorCategory.VALIDITY
    assert detector.metadata.requires_raw_rows is True
    assert detector.metadata.documented_limitations
    detector.config_schema.model_validate({})


@pytest.mark.parametrize("value", _VALID)
def test_email_shape_accepts_ordinary_addresses(value: str) -> None:
    assert _has_email_shape(value) is True


@pytest.mark.parametrize("value", _INVALID)
def test_email_shape_rejects_values_that_cannot_be_an_address(value: str) -> None:
    assert _has_email_shape(value) is False


def test_email_shape_check_is_linear_on_very_long_values() -> None:
    """No regular expression: pathological input cannot cause backtracking."""
    hostile = "a" * 100_000 + "@" + "a." * 50_000
    assert _has_email_shape(hostile) is False  # the empty trailing label fails


def test_email_flags_invalid_values_in_an_email_column_with_counts_only() -> None:
    profile, rows = _emails((*_VALID, "ann-at-example.com", None, "", "a b@example.com"))

    result = InvalidEmailShapeDetector().run(make_request(profile, rows))

    (finding,) = result.findings
    (evidence,) = result.evidence
    assert [ref.row_number for ref in finding.affected_row_references] == [3, 6]
    assert finding.severity is Severity.LOW
    assert finding.confidence == 0.8
    assert evidence.structured_payload == {
        "checked_value_count": 5,
        "invalid_value_count": 2,
        "expected_shape": "local@domain.tld",
    }


def _all_text(obj: object) -> list[str]:
    """Every string reachable from a finding or an evidence object."""
    if isinstance(obj, str):
        return [obj]
    if isinstance(obj, Mapping):
        return [text for item in (*obj.keys(), *obj.values()) for text in _all_text(item)]
    if isinstance(obj, (list, tuple, set, frozenset)):
        return [text for item in obj for text in _all_text(item)]
    if is_dataclass(obj) and not isinstance(obj, type):
        return [text for f in fields(obj) for text in _all_text(getattr(obj, f.name))]
    return []


def test_email_values_never_appear_in_any_finding_or_evidence_text() -> None:
    """The privacy proof: personal data stays out of every field the product
    stores, shows, reports or exports."""
    secret_valid = "grace.hopper@navy.example"
    secret_invalid = "grace.hopper-at-navy.example"
    profile, rows = _emails((secret_valid, "x@y.example", "z@w.example", secret_invalid))

    result = InvalidEmailShapeDetector().run(make_request(profile, rows))

    texts = _all_text(result.findings) + _all_text(result.evidence)
    assert texts, "the proof must scan something"
    for text in texts:
        for fragment in (secret_valid, secret_invalid, "grace", "hopper", "navy"):
            assert fragment not in text.lower(), (fragment, text)


@pytest.mark.parametrize(
    "name",
    ["Email", "customer_email", "E-Mail", "contact email address", "EmailAddress"],
)
def test_email_columns_are_found_by_name(name: str) -> None:
    profile, rows = _emails((*_VALID, "broken"), name=name)

    assert len(InvalidEmailShapeDetector().run(make_request(profile, rows)).findings) == 1


@pytest.mark.parametrize("name", ["notes", "phone", "postal_mail_code", "name"])
def test_email_check_ignores_columns_not_named_like_email(name: str) -> None:
    profile, rows = _emails((*_VALID, "broken"), name=name)

    assert InvalidEmailShapeDetector().run(make_request(profile, rows)).findings == ()


@pytest.mark.parametrize(
    "values",
    [
        _VALID,  # all valid
        ("Y", "N", "Y", "N"),  # an 'email_sent' flag: mostly invalid, so not an email column
        ("a@b.com", "x", "y", "z"),  # under half look like emails
        ("x", "y"),
        (None, "", "  "),
        (),
    ],
)
def test_email_check_does_not_flag_clean_or_non_email_content(values: tuple[object, ...]) -> None:
    profile, rows = _emails(values)

    result = InvalidEmailShapeDetector().run(make_request(profile, rows))

    assert result.status is DetectorRunStatus.SUCCESS
    assert result.findings == ()


def test_email_boundary_exactly_half_valid_is_checked() -> None:
    profile, rows = _emails(("a@b.com", "broken"))

    assert len(InvalidEmailShapeDetector().run(make_request(profile, rows)).findings) == 1


@pytest.mark.parametrize(
    "inferred",
    [InferredColumnType.NUMERIC, InferredColumnType.DATE, InferredColumnType.UNKNOWN],
)
def test_email_check_skips_out_of_scope_column_types(inferred: InferredColumnType) -> None:
    profile, rows = _emails((*_VALID, "broken"), inferred=inferred)

    assert InvalidEmailShapeDetector().run(make_request(profile, rows)).findings == ()


def test_email_ignores_non_string_cells_without_failing() -> None:
    profile, rows = _emails((*_VALID, 12345, "broken"))

    result = InvalidEmailShapeDetector().run(make_request(profile, rows))

    assert [ref.row_number for ref in result.findings[0].affected_row_references] == [4]


def test_email_is_repeatable() -> None:
    profile, rows = _emails((*_VALID, "broken"))
    request = make_request(profile, rows)

    assert InvalidEmailShapeDetector().run(request) == InvalidEmailShapeDetector().run(request)


# ---------------------------------------------------------------------------
# Registry interoperation and an end-to-end analysis
# ---------------------------------------------------------------------------


def test_both_detectors_are_registered_with_unique_ids() -> None:
    ids = [detector.metadata.detector_id for detector in DETECTORS]
    assert len(ids) == len(set(ids))
    assert {"validity.implausibly_old_dates", "validity.invalid_email_shape"} <= set(ids)


def test_end_to_end_parse_profile_detect_reports_both_problems() -> None:
    csv_bytes = (
        b"id,signed_up,contact_email\n"
        b"1,2024-01-05,ann@example.com\n"
        b"2,0001-01-01,bo@example.com\n"
        b"3,2023-07-19,not-an-email\n"
        b"4,2022-03-02,cy@example.com\n"
        b"5,2021-11-30,di@example.com\n"
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
    (old,) = by_detector["validity.implausibly_old_dates"]
    assert [ref.row_number for ref in old.affected_row_references] == [1]
    (email,) = by_detector["validity.invalid_email_shape"]
    assert [ref.row_number for ref in email.affected_row_references] == [2]
    assert [column.original_name for column in email.affected_columns] == ["contact_email"]
