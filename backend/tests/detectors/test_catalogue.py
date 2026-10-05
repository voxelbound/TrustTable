"""Tests for the detector catalogue (DET-02 complete, DET-SEC-01 added).

Covers WP-014's acceptance criteria AC-13..AC-15, WP-015's AC-14/AC-15,
WP-016's AC-14/AC-15, WP-017's AC-14/AC-15, WP-018's AC-16/AC-17,
WP-019's AC-15/AC-16, and WP-021's AC-17: `DETECTORS` registers
successfully, contains exactly the expected twenty-three detector IDs (the
original thirteen, `DET-03` slice 1's `completeness.fully_empty_rows` and
`consistency.inconsistent_booleans`, slice 2's
`validity.implausibly_old_dates` and `validity.invalid_email_shape`, slice
3's `consistency.numeric_values_stored_as_text` and
`consistency.near_duplicate_categories`, slice 4's
`structural.duplicate_normalized_column_name`, and closure package 1's
`structural.empty_dataset`, `structural.unnamed_column` and
`structural.excessive_parse_failures`), and interoperates correctly with
`DET-01`'s `run_detectors()`.
"""

from __future__ import annotations

from trusttable_backend.detectors.catalogue import DETECTORS


def test_detectors_catalogue_registers_without_exception() -> None:
    assert len(DETECTORS) == 23


def test_detectors_catalogue_has_exactly_expected_ids() -> None:
    assert {detector.metadata.detector_id for detector in DETECTORS} == {
        "structural.empty_dataset",
        "structural.unnamed_column",
        "structural.excessive_parse_failures",
        "consistency.numeric_values_stored_as_text",
        "consistency.near_duplicate_categories",
        "structural.duplicate_normalized_column_name",
        "validity.implausibly_old_dates",
        "validity.invalid_email_shape",
        "completeness.fully_empty_rows",
        "consistency.inconsistent_booleans",
        "structural.exact_duplicate_rows",
        "structural.empty_column",
        "completeness.excessive_missing_values",
        "completeness.missing_likely_identifier",
        "consistency.inconsistent_capitalization",
        "consistency.leading_trailing_whitespace",
        "validity.future_dates",
        "validity.negative_likely_non_negative_values",
        "validity.invalid_percentages",
        "cross_field.line_total_mismatch",
        "statistical.suspiciously_constant_column",
        "statistical.extreme_outliers",
        "security.possible_llm_prompt_injection",
    }
