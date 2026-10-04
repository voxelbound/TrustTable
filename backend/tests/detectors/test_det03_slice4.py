"""Tests for `DET-03` slice 4: `structural.duplicate_normalized_column_name`.

Follows `docs/detector-framework.md` §15's detector test contract (positive,
negative, threshold boundary, empty and malformed input, repeatability,
configuration and known false positives). The false positive that matters
most is pinned against the real CSV parser: its ASCII-only internal key maps
every non-Latin character to `_`, so unrelated non-Latin headers collide
there, but they are *not* the same name and the detector must stay silent.
"""

from __future__ import annotations

import time
import unicodedata

import pytest

from tests.detectors.test_det03_slice1 import (
    ANALYSIS_TIMESTAMP,
    NO_EXPOSURE,
    make_request,
)
from trusttable_backend.detectors.catalogue import DETECTORS
from trusttable_backend.detectors.contract import (
    DetectorCategory,
    DetectorRunResult,
    DetectorRunStatus,
)
from trusttable_backend.detectors.engine import run_detectors
from trusttable_backend.detectors.structural import (
    DuplicateNormalizedColumnNameDetector,
    _column_name_key,
)
from trusttable_backend.domain.evidence import EvidenceType
from trusttable_backend.domain.parsing import SampleMetadata, SamplingScope
from trusttable_backend.domain.value_objects import ColumnReference, Severity
from trusttable_backend.parsers.csv_parser import parse_csv
from trusttable_backend.profiling.metrics import compute_dataset_profile
from trusttable_backend.profiling.schemas import (
    ColumnProfile,
    DatasetProfile,
    InferredColumnType,
    ProfilingTiming,
)

DETECTOR_ID = "structural.duplicate_normalized_column_name"


def _profile(names: tuple[str, ...]) -> DatasetProfile:
    """A profile whose columns carry exactly `names` (distinct internal keys)."""
    profiles = tuple(
        ColumnProfile(
            column=ColumnReference(original_name=name, internal_key=f"c{ordinal}", ordinal=ordinal),
            inferred_type=InferredColumnType.CATEGORICAL,
            null_count=0,
            distinct_count=0,
            metrics={},
            warnings=(),
        )
        for ordinal, name in enumerate(names)
    )
    return DatasetProfile(
        schema_version="1",
        dataset_metrics={"row_count": 0},
        column_profiles=profiles,
        sampling=SampleMetadata(scope=SamplingScope.FULL, population_size=0, sample_size=0),
        warnings=(),
        timing=ProfilingTiming(
            started_at=ANALYSIS_TIMESTAMP, completed_at=ANALYSIS_TIMESTAMP, duration_ms=1
        ),
    )


def _run(names: tuple[str, ...]) -> DetectorRunResult:
    return DuplicateNormalizedColumnNameDetector().run(make_request(_profile(names), ()))


# ---------------------------------------------------------------------------
# The comparison key
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("Order ID", "order_id"),
        ("Order ID", "ORDER-ID"),
        ("order.id", "Order  Id"),
        ("Amount", "Amount"),
        ("Straße", "STRASSE"),  # casefold, not lower
        ("Ｏrder", "Order"),  # fullwidth letter, compatibility-folded
        ("Café", unicodedata.normalize("NFD", "Café")),  # composed versus decomposed
        ("名前", "名前 "),  # non-Latin names still collide with themselves
        ("col_1", "col1"),
    ],
)
def test_column_name_key_equates_names_that_differ_only_by_case_spacing_or_punctuation(
    first: str, second: str
) -> None:
    assert _column_name_key(first) == _column_name_key(second)


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ("名前", "価格"),  # different non-Latin names: the parser key makes these collide
        ("Café", "Cafe"),  # an accent is a letter difference
        ("col1", "col2"),  # digits matter
        ("Order ID", "Order No"),
        ("?", "#"),  # nothing alphanumeric: only identical names group
        ("a", "b"),
        # Combining marks distinguish names in scripts that cannot compose them
        # into a base letter, so dropping them would merge unrelated names.
        ("कि", "कु"),  # Devanagari ki versus ku
        ("ไก่", "ไก"),  # Thai: with versus without a tone mark
        ("كتب", "كَتَب"),  # Arabic: with fatha marks
        ("é", "e"),  # a combining accent that composes to a different letter
    ],
)
def test_column_name_key_keeps_genuinely_different_names_apart(first: str, second: str) -> None:
    assert _column_name_key(first) != _column_name_key(second)


@pytest.mark.parametrize(
    "names",
    [
        ("कि", "कु"),  # Devanagari
        ("ไก่", "ไก"),  # Thai
        ("كتب", "كَتَب"),  # Arabic
    ],
)
def test_detector_does_not_flag_names_that_differ_only_by_combining_marks(
    names: tuple[str, ...],
) -> None:
    assert _run(names).findings == ()


def test_combining_marks_do_not_hide_a_real_collision() -> None:
    """The same marked name written with different punctuation still collides."""
    (finding,) = _run(("कि-कु", "कि कु")).findings

    assert [column.ordinal for column in finding.affected_columns] == [0, 1]


# ---------------------------------------------------------------------------
# structural.duplicate_normalized_column_name
# ---------------------------------------------------------------------------


def test_metadata_and_config() -> None:
    detector = DuplicateNormalizedColumnNameDetector()
    assert detector.metadata.detector_id == DETECTOR_ID
    assert detector.metadata.category is DetectorCategory.STRUCTURAL
    assert detector.metadata.requires_raw_rows is False
    assert detector.metadata.requires_confirmed_context is False
    assert detector.metadata.documented_limitations
    detector.config_schema.model_validate({})


def test_flags_names_that_differ_only_by_case_spacing_or_punctuation() -> None:
    result = _run(("id", "Order ID", "amount", "order_id"))

    assert result.status is DetectorRunStatus.SUCCESS
    (finding,) = result.findings
    (evidence,) = result.evidence
    assert [column.original_name for column in finding.affected_columns] == ["Order ID", "order_id"]
    assert finding.severity is Severity.MEDIUM
    assert finding.confidence == 0.9  # same name only after normalization
    assert finding.affected_row_references == ()
    assert finding.evidence_ids == (evidence.evidence_id,)
    assert evidence.evidence_type is EvidenceType.METRIC
    assert evidence.structured_payload == {
        "column_count": 2,
        "ordinals": [1, 3],
        "identical_as_written": False,
    }
    assert "'Order ID', 'order_id'" in finding.calculated_observation


def test_identical_names_are_flagged_with_full_confidence() -> None:
    (finding,) = _run(("Amount", "Quantity", "Amount")).findings

    assert finding.confidence == 1.0
    assert [column.ordinal for column in finding.affected_columns] == [0, 2]


def test_one_finding_per_colliding_group_in_column_order() -> None:
    result = _run(("Total", "Date", "total", "date", "DATE", "Region"))

    assert [[column.ordinal for column in f.affected_columns] for f in result.findings] == [
        [0, 2],
        [1, 3, 4],
    ]
    assert len({evidence.evidence_id for evidence in result.evidence}) == 2


@pytest.mark.parametrize(
    "names",
    [
        ("名前", "価格", "Имя", "Цена"),  # different non-Latin names are different names
        ("Café", "Cafe"),
        ("col1", "col2", "col3"),
        ("Order ID", "Order No", "Order Date"),
        ("?", "#", "!"),  # no letters or digits: only identical text would group
        ("only",),
        (),
    ],
)
def test_does_not_flag_distinct_names_or_trivial_inputs(names: tuple[str, ...]) -> None:
    result = _run(names)

    assert result.status is DetectorRunStatus.SUCCESS
    assert result.findings == ()
    assert result.evidence == ()


def test_names_with_no_letters_or_digits_group_only_when_identical() -> None:
    (finding,) = _run(("?", "#", "?")).findings

    assert [column.ordinal for column in finding.affected_columns] == [0, 2]
    assert finding.confidence == 1.0


def test_boundary_two_columns_are_enough_one_is_not() -> None:
    assert len(_run(("a b", "a_b")).findings) == 1
    assert _run(("a b", "a c")).findings == ()


def test_decomposed_and_composed_accents_are_the_same_name() -> None:
    names = ("Café", unicodedata.normalize("NFD", "Café"))

    assert len(_run(names).findings) == 1


def test_large_groups_name_only_a_bounded_number_of_columns() -> None:
    names = tuple(f"{'x' * 100}{separator}" for separator in "-._ /,;:+*&#")  # 12 columns
    result = _run(names)

    (finding,) = result.findings
    (evidence,) = result.evidence
    assert evidence.structured_payload["column_count"] == 12
    assert len(finding.affected_columns) == 12
    assert "and 7 more" in finding.calculated_observation
    assert "x" * 61 not in finding.calculated_observation  # names are truncated for display


def test_reads_column_names_only_and_ignores_rows() -> None:
    profile = _profile(("a b", "a_b"))
    with_rows = DuplicateNormalizedColumnNameDetector().run(
        make_request(profile, ({"c0": "secret", "c1": object()},))
    )
    without_rows = DuplicateNormalizedColumnNameDetector().run(make_request(profile, ()))

    assert with_rows == without_rows
    assert "secret" not in repr(with_rows)


def test_is_repeatable() -> None:
    request = make_request(_profile(("Order ID", "order_id", "x")), ())

    assert DuplicateNormalizedColumnNameDetector().run(
        request
    ) == DuplicateNormalizedColumnNameDetector().run(request)


def test_is_linear_at_the_column_limit_and_on_a_very_long_name() -> None:
    """No regular expression runs over untrusted names: 500 columns (the
    parser's limit) and a 1,000,000-character name finish well inside a second."""
    names = tuple(f"column_{n}" if n % 2 == 0 else f"Column {n - 1}" for n in range(500))
    started = time.perf_counter()
    result = _run(names)
    assert _column_name_key("a-" * 500_000) == (True, "a" * 500_000)
    assert time.perf_counter() - started < 2.0
    assert len(result.findings) == 250  # every adjacent odd/even pair collides


# ---------------------------------------------------------------------------
# Real parser output, registry interoperation and an end-to-end analysis
# ---------------------------------------------------------------------------


def test_non_latin_headers_collide_in_the_parser_key_but_are_not_flagged() -> None:
    """The parser maps both headers to the ASCII fallback `column` and renames
    the second to `column_2`; they are different names, so there is no finding."""
    parsed = parse_csv("名前,価格\nAlice,10\nBob,20\n".encode())
    columns = parsed.parsed_dataset.columns
    assert [column.internal_key for column in columns] == ["column", "column_2"]
    assert "parsing.duplicate_column_name" in {
        warning.code for warning in parsed.parsed_dataset.parsing_warnings
    }
    profile = compute_dataset_profile(
        columns,
        parsed.rows,
        parsed.parsed_dataset.sampling,
        as_of=ANALYSIS_TIMESTAMP.date(),
    )

    result = DuplicateNormalizedColumnNameDetector().run(make_request(profile, ()))

    assert result.findings == ()


def test_the_detector_is_registered_with_a_unique_id() -> None:
    ids = [detector.metadata.detector_id for detector in DETECTORS]
    assert len(ids) == len(set(ids))
    assert DETECTOR_ID in ids


def test_end_to_end_parse_profile_detect_reports_colliding_headers() -> None:
    csv_bytes = b"Order ID,order_id,Amount,Region\n1,A1,10,North\n2,A2,20,South\n3,A3,30,North\n"
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
    (finding,) = by_detector[DETECTOR_ID]
    assert [column.original_name for column in finding.affected_columns] == ["Order ID", "order_id"]
    assert [column.internal_key for column in finding.affected_columns] == [
        "order_id",
        "order_id_2",
    ]
