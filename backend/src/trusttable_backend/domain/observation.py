"""The minimal Observation foundation (`DET-03` closure package 2,
`docs/decision-log.md` D-061).

An *Observation* states a pattern that can be seen in the data. It is not a
`Finding`:

- it has **no severity, no confidence and no priority**, so there is nothing
  for trust scoring or prioritisation to read;
- it makes no claim that a business role or rule is true; it may only describe
  what was counted;
- it is never promoted or converted into a finding. A later finding is a new
  object and the observation stays unchanged.

There is exactly one kind today, `value_evidence`. A later kind (for example
the `NOT_CHECKED` kind planned for `CCX-01`) is a **new** `ObservationKind`
member, never a change to `value_evidence`.

Observations are stored with the analysis and read through one read-only API
route. They are deliberately **not** counted by trust scoring or priority, not
sent in any AI payload, and not part of an export or report. That exclusion is
enforced by a negative allowlist test, not by the absence of wiring.

Stdlib only; framework-independent per `docs/architecture.md` §3.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from .parsing import SamplingScope
from .value_objects import ColumnReference, RowReference


class ObservationKind(StrEnum):
    """Closed set of observation kinds. One member today; extend only by
    adding a member (`docs/detector-framework.md` §16, package 2)."""

    VALUE_EVIDENCE = "value_evidence"


#: Upper bound on example row references kept on one observation. Counts in the
#: structured payload stay exact; only the example references are capped.
MAX_OBSERVATION_ROW_REFERENCES: Final[int] = 20

#: Upper bound on affected columns kept on one observation.
MAX_OBSERVATION_COLUMNS: Final[int] = 50


@dataclass(frozen=True, slots=True)
class Observation:
    """One neutral, read-only statement about observable data.

    `structured_payload` holds counts, ratios, ordinals and fixed labels only;
    a producer never puts a raw cell value in it. `summary` is a short,
    display-safe sentence of the same facts.
    """

    observation_id: str
    kind: ObservationKind
    producer_detector_id: str
    producer_version: str
    summary: str
    affected_columns: tuple[ColumnReference, ...]
    affected_row_references: tuple[RowReference, ...]
    scope: SamplingScope
    structured_payload: Mapping[str, object] = field(default_factory=lambda: MappingProxyType({}))

    def __post_init__(self) -> None:
        if not self.observation_id:
            raise ValueError("Observation.observation_id must not be empty")
        if not self.producer_detector_id or "." not in self.producer_detector_id:
            raise ValueError("Observation.producer_detector_id must be a namespaced detector id")
        if not self.producer_version:
            raise ValueError("Observation.producer_version must not be empty")
        if not self.summary:
            raise ValueError("Observation.summary must not be empty")
        if len(self.affected_row_references) > MAX_OBSERVATION_ROW_REFERENCES:
            raise ValueError("Observation.affected_row_references exceeds its bound")
        if len(self.affected_columns) > MAX_OBSERVATION_COLUMNS:
            raise ValueError("Observation.affected_columns exceeds its bound")
