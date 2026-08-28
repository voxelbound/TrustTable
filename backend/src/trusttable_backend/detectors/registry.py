"""Detector registration (`DET-01`), matching
`docs/detector-framework.md` §9 (Registration): explicit registration
only (no dynamic entry-point discovery), with startup validation for
unique IDs, valid versions, valid configuration, and declared
dependencies.

No `DETECTORS = [...]` catalogue constant is created here — `DET-02` is
the package that provides the first real registrations, importing
`register_detectors()` from this module.
"""

from __future__ import annotations

from collections.abc import Sequence

from pydantic import ValidationError

from .contract import Detector


def register_detectors(detectors: Sequence[Detector]) -> tuple[Detector, ...]:
    """Validate and return `detectors` in stable, deterministic (input)
    order.

    Raises `ValueError` when:
    - a `detector_id` is duplicated across `detectors`
    - a detector's `metadata.default_configuration` fails validation
      against its own `config_schema`

    "Declared dependencies exist" (`docs/detector-framework.md` §9) is
    checked structurally only: `DetectorMetadata.__post_init__` already
    rejects any empty `required_profile_fields` entry. Deep existence-
    checking against `DatasetProfile`'s actual field names is not
    mechanically possible — `PROF-03` deliberately left
    `dataset_metrics`/`ColumnProfile.metrics` as open
    `Mapping[str, object]` containers, not a fixed schema.
    """
    seen_ids: set[str] = set()
    for detector in detectors:
        detector_id = detector.metadata.detector_id
        if detector_id in seen_ids:
            raise ValueError(f"register_detectors: duplicate detector_id {detector_id!r}")
        seen_ids.add(detector_id)

        try:
            detector.config_schema.model_validate(detector.metadata.default_configuration)
        except ValidationError as exc:
            raise ValueError(
                f"register_detectors: {detector_id!r} default_configuration is invalid "
                f"against its own config_schema: {exc}"
            ) from exc

    return tuple(detectors)
