"""Evidence contracts (`PROF-01`), matching `docs/domain-model.md` §13.

Placed under `domain/` rather than `profiling/`: `docs/domain-model.md`'s
aggregate diagram (§2) roots `Evidence` under `Analysis` -> `Finding`, not
under `DatasetProfile`, and the future detector packages (`DET-*`) will
need `Evidence` just as much as profiling does — a disclosed, reversible
placement decision, not a change to any fixed field list.

Framework-independent: no FastAPI/SQLAlchemy/pydantic import. Stdlib only
(`dataclasses`, `enum`, `collections.abc.Mapping`).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum

from .parsing import SamplingScope
from .value_objects import ColumnReference, RowReference


class EvidenceType(StrEnum):
    """Closed set of evidence types (`docs/domain-model.md` §13 "Types")."""

    METRIC = "metric"
    DISTRIBUTION = "distribution"
    ROW_SET = "row_set"
    CATEGORY_FREQUENCY = "category_frequency"
    CROSS_FIELD_COMPARISON = "cross_field_comparison"
    TEMPORAL_PATTERN = "temporal_pattern"
    SECURITY_PATTERN = "security_pattern"
    DETECTOR_CONFIGURATION = "detector_configuration"
    REPRESENTATIVE_SAMPLE = "representative_sample"


@dataclass(frozen=True, slots=True)
class Evidence:
    """Auditable support for a finding (`docs/domain-model.md` §13).

    Fields follow §13's exact field list. `structured_payload` is
    intentionally open (`Mapping[str, object]`) — its shape depends on
    `evidence_type` and no document fixes a single schema for it.

    Two of §13's invariants are not mechanically enforced by this type
    and are recorded here rather than silently ignored: "raw sensitive
    values are not embedded unless explicitly allowed" (no generic way to
    detect "sensitive" values at this layer; deferred to the redaction
    package, `PRIV-01`) and "row evidence is bounded for display" (no
    document specifies a concrete bound; deferred to the future
    report/display package that renders evidence).
    """

    evidence_id: str
    evidence_type: EvidenceType
    calculation_version: str
    structured_payload: Mapping[str, object]
    affected_columns: tuple[ColumnReference, ...]
    affected_row_references: tuple[RowReference, ...]
    scope: SamplingScope
    display_safe_summary: str

    def __post_init__(self) -> None:
        if not self.evidence_id:
            raise ValueError("Evidence.evidence_id must not be empty")
        if not self.calculation_version:
            raise ValueError("Evidence.calculation_version must not be empty")
        if not self.display_safe_summary:
            raise ValueError("Evidence.display_safe_summary must not be empty")
