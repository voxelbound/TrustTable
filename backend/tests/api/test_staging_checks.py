"""The "what will be checked" summary is derived from the real detector registry
(`UX-02`, D-068), so it cannot describe a check that does not exist, and a new
detector category cannot ship without a business-language group.
"""

from __future__ import annotations

import pytest

from trusttable_backend.detectors.catalogue import DETECTORS
from trusttable_backend.detectors.contract import DetectorCategory
from trusttable_backend.staging_inspection import _CHECK_GROUPS, check_groups


def test_every_detector_category_has_a_business_language_group() -> None:
    assert set(_CHECK_GROUPS) == set(DetectorCategory)


def test_one_group_per_registered_category_and_none_for_an_unregistered_one() -> None:
    registered = {detector.metadata.category for detector in DETECTORS}
    expected_titles = [
        _CHECK_GROUPS[category][0] for category in DetectorCategory if category in registered
    ]

    assert [group.title for group in check_groups()] == expected_titles


def test_a_category_with_no_registered_detector_is_not_listed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    kept = [d for d in DETECTORS if d.metadata.category is not DetectorCategory.CROSS_FIELD]
    monkeypatch.setattr("trusttable_backend.staging_inspection.DETECTORS", kept)

    titles = [group.title for group in check_groups()]

    assert _CHECK_GROUPS[DetectorCategory.CROSS_FIELD][0] not in titles
    assert len(titles) == len({d.metadata.category for d in kept})


def test_no_group_names_a_detector_or_uses_internal_vocabulary() -> None:
    suffixes = {detector.metadata.detector_id.split(".", 1)[1] for detector in DETECTORS}
    for group in check_groups():
        combined = f"{group.title} {group.description}".lower()
        assert "_" not in combined
        for suffix in suffixes:
            assert suffix not in combined
        for banned in ("detector", "severity", "confidence", "category", "internal"):
            assert banned not in combined
