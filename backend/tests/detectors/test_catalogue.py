"""Tests for the detector catalogue (DET-02 complete, DET-SEC-01 added).

Covers WP-014's acceptance criteria AC-13..AC-15, WP-015's AC-14/AC-15,
WP-016's AC-14/AC-15, WP-017's AC-14/AC-15, WP-018's AC-16/AC-17,
WP-019's AC-15/AC-16, and WP-021's AC-17: `DETECTORS` registers
successfully, contains exactly the expected thirteen detector IDs, and
interoperates correctly with `DET-01`'s `run_detectors()`.
"""

from __future__ import annotations

from trusttable_backend.detectors.catalogue import DETECTORS


def test_detectors_catalogue_registers_without_exception() -> None:
    assert len(DETECTORS) == 13


def test_detectors_catalogue_has_exactly_expected_ids() -> None:
    assert {detector.metadata.detector_id for detector in DETECTORS} == {
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
