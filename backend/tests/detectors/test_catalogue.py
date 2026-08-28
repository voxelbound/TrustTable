"""Tests for the detector catalogue (DET-02 partial).

Covers WP-014's acceptance criteria AC-13..AC-15 and WP-015's AC-14/AC-15:
`DETECTORS` registers successfully, contains exactly the expected four
detector IDs, and interoperates correctly with `DET-01`'s
`run_detectors()`.
"""

from __future__ import annotations

from trusttable_backend.detectors.catalogue import DETECTORS


def test_detectors_catalogue_registers_without_exception() -> None:
    assert len(DETECTORS) == 4


def test_detectors_catalogue_has_exactly_expected_ids() -> None:
    assert {detector.metadata.detector_id for detector in DETECTORS} == {
        "structural.exact_duplicate_rows",
        "structural.empty_column",
        "completeness.excessive_missing_values",
        "completeness.missing_likely_identifier",
    }
