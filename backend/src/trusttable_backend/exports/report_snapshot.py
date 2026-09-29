"""Immutable report snapshot and its explicit inputs (`EXP-01` slice 2).

Lives in the `exports` package rather than a `reports` one because the
repository's `.gitignore` ignores any directory named `reports/`.

Framework-independent: no FastAPI/SQLAlchemy/pydantic/`ai_provider` import.

`AiEnrichmentDisclosure` exists because the analysis aggregate does not
record per-request AI calls (finding explanations, context augmentation):
`Analysis.security_exposure` describes only the deterministic detection
pipeline's own posture (`docs/decision-log.md` D-037/D-038). The report
must therefore never infer "no AI was used" from the aggregate. A caller
that has a real record supplies it here; when it supplies none, the
report says the matter is not recorded instead of asserting an answer.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

REPORT_SCHEMA_VERSION = "1"

#: Upper bound on affected row numbers listed per finding when the
#: bounded-examples option is set. Row numbers only, never cell values.
MAX_EXAMPLE_ROWS = 5


class ModelLocation(StrEnum):
    """Where a model that received bounded metadata runs."""

    LOCAL = "local"
    REMOTE = "remote"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ReportOptions:
    """The three request options of `docs/api-specification.md` §12."""

    include_dismissed: bool = False
    include_technical_appendix: bool = False
    include_bounded_examples: bool = False


@dataclass(frozen=True, slots=True)
class ReportVersions:
    """Application, detector, prompt and model versions to disclose.

    `detector_versions` is `(detector_id, version)` pairs. `prompt_version`
    and `model_name` are `None` when not recorded/applicable, and the
    report then says so rather than omitting the line.
    """

    application_version: str
    detector_versions: tuple[tuple[str, str], ...] = ()
    prompt_version: str | None = None
    model_name: str | None = None

    def __post_init__(self) -> None:
        if not self.application_version:
            raise ValueError("ReportVersions.application_version must not be empty")


@dataclass(frozen=True, slots=True)
class AiEnrichmentDisclosure:
    """A caller-supplied record of the optional per-request AI enrichment.

    Counts are of enrichment calls by outcome (`ai_call_status` vocabulary
    of `docs/api-specification.md`). `protections` are the exact labels
    the caller attests were applied; the report prints them verbatim and
    never adds protections of its own.
    """

    accepted_count: int
    rejected_count: int
    provider_error_count: int
    evidence_sent_to_model: bool
    confirmed_context_sent_to_model: bool
    model_location: ModelLocation
    protections: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for name in ("accepted_count", "rejected_count", "provider_error_count"):
            if getattr(self, name) < 0:
                raise ValueError(f"AiEnrichmentDisclosure.{name} must not be negative")
        attempts = self.accepted_count + self.rejected_count + self.provider_error_count
        if attempts == 0 and (self.evidence_sent_to_model or self.confirmed_context_sent_to_model):
            raise ValueError("AiEnrichmentDisclosure reports data sent to a model with no attempts")

    @property
    def attempt_count(self) -> int:
        return self.accepted_count + self.rejected_count + self.provider_error_count


@dataclass(frozen=True, slots=True)
class ReportSnapshot:
    """An immutable rendered report. `markdown` is byte-identical for
    identical inputs; `generated_at` is metadata only and never rendered.
    """

    report_id: str
    analysis_id: str
    generated_at: datetime
    options: ReportOptions
    schema_version: str
    markdown: str
    content_sha256: str

    def __post_init__(self) -> None:
        if not self.report_id:
            raise ValueError("ReportSnapshot.report_id must not be empty")
        if not self.analysis_id:
            raise ValueError("ReportSnapshot.analysis_id must not be empty")
        expected = hashlib.sha256(self.markdown.encode("utf-8")).hexdigest()
        if self.content_sha256 != expected:
            raise ValueError("ReportSnapshot.content_sha256 does not match markdown")
