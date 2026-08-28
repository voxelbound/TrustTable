"""Tests for detector registration (DET-01).

Covers this package's acceptance criteria AC-14..AC-16:
`register_detectors()` rejects duplicate `detector_id` values and
detectors whose `default_configuration` fails their own `config_schema`,
and returns detectors in stable, deterministic (input) order.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from trusttable_backend.detectors.contract import (
    DetectorCategory,
    DetectorMetadata,
    DetectorRunRequest,
    DetectorRunResult,
    DetectorSupportRequest,
    PerformanceClass,
)
from trusttable_backend.detectors.registry import register_detectors


class _EmptyConfig(BaseModel):
    pass


class _ThresholdConfig(BaseModel):
    threshold: float


def make_metadata(**overrides: object) -> DetectorMetadata:
    fields: dict[str, object] = {
        "detector_id": "structural.exact_duplicate_rows",
        "version": "1",
        "name": "Exact duplicate rows",
        "category": DetectorCategory.STRUCTURAL,
        "description": "Flags rows that are byte-identical to another row.",
        "applicable_inferred_types": (),
        "required_profile_fields": (),
        "requires_raw_rows": False,
        "requires_confirmed_context": False,
        "default_configuration": {},
        "performance_class": PerformanceClass.LINEAR_BY_ROW,
        "documented_limitations": (),
    }
    fields.update(overrides)
    return DetectorMetadata(**fields)  # type: ignore[arg-type]


class StubDetector:
    """A minimal `Detector`-shaped test double. `supports()`/`run()` are
    never called by `register_detectors()` and raise if invoked, so any
    accidental call in a registration test is caught immediately.
    """

    def __init__(
        self,
        *,
        detector_id: str = "structural.exact_duplicate_rows",
        config_schema: type[BaseModel] = _EmptyConfig,
        default_configuration: dict[str, object] | None = None,
    ) -> None:
        self.metadata = make_metadata(
            detector_id=detector_id, default_configuration=default_configuration or {}
        )
        self.config_schema = config_schema

    def supports(self, request: DetectorSupportRequest) -> bool:
        raise AssertionError("supports() must not be called by register_detectors()")

    def run(self, request: DetectorRunRequest) -> DetectorRunResult:
        raise AssertionError("run() must not be called by register_detectors()")


# ---------------------------------------------------------------------------
# AC-14: duplicate detector_id
# ---------------------------------------------------------------------------


def test_register_detectors_accepts_unique_ids() -> None:
    a = StubDetector(detector_id="structural.exact_duplicate_rows")
    b = StubDetector(detector_id="structural.empty_column")
    result = register_detectors([a, b])
    assert result == (a, b)


def test_register_detectors_rejects_duplicate_detector_id() -> None:
    a = StubDetector(detector_id="structural.exact_duplicate_rows")
    b = StubDetector(detector_id="structural.exact_duplicate_rows")
    with pytest.raises(ValueError, match="duplicate detector_id"):
        register_detectors([a, b])


# ---------------------------------------------------------------------------
# AC-15: default_configuration validated against config_schema
# ---------------------------------------------------------------------------


def test_register_detectors_accepts_valid_default_configuration() -> None:
    detector = StubDetector(
        config_schema=_ThresholdConfig, default_configuration={"threshold": 0.5}
    )
    result = register_detectors([detector])
    assert result == (detector,)


def test_register_detectors_rejects_invalid_default_configuration() -> None:
    detector = StubDetector(config_schema=_ThresholdConfig, default_configuration={})
    with pytest.raises(ValueError, match="default_configuration is invalid"):
        register_detectors([detector])


def test_register_detectors_rejects_default_configuration_with_wrong_type() -> None:
    detector = StubDetector(
        config_schema=_ThresholdConfig, default_configuration={"threshold": "not-a-number"}
    )
    with pytest.raises(ValueError, match="default_configuration is invalid"):
        register_detectors([detector])


# ---------------------------------------------------------------------------
# AC-16: stable, deterministic order
# ---------------------------------------------------------------------------


def test_register_detectors_preserves_input_order() -> None:
    detectors = [
        StubDetector(detector_id="structural.b"),
        StubDetector(detector_id="structural.a"),
        StubDetector(detector_id="structural.c"),
    ]
    result = register_detectors(detectors)
    assert [d.metadata.detector_id for d in result] == [
        "structural.b",
        "structural.a",
        "structural.c",
    ]


def test_register_detectors_accepts_empty_sequence_boundary() -> None:
    assert register_detectors([]) == ()
