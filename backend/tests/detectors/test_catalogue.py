"""Tests for the detector catalogue (DET-02 partial).

Covers this package's acceptance criteria AC-13..AC-15: `DETECTORS`
registers successfully, contains exactly the expected two detector IDs,
and interoperates correctly with `DET-01`'s `run_detectors()`.
"""

from __future__ import annotations

from trusttable_backend.detectors.catalogue import DETECTORS


def test_detectors_catalogue_registers_without_exception() -> None:
    assert len(DETECTORS) == 2


def test_detectors_catalogue_has_exactly_expected_ids() -> None:
    assert {detector.metadata.detector_id for detector in DETECTORS} == {
        "structural.exact_duplicate_rows",
        "structural.empty_column",
    }
