"""The dashboard summary (`UX-04`, `docs/decision-log.md` D-070).

Three figures the Overview needs and a browser cannot derive from the list
responses it already has: how many *distinct* rows the findings point at, how
many rows and columns were analysed, and how complete the data is.

Honesty rules this module enforces by construction:

- **Distinct rows.** Findings overlap, so the per-finding row counts are never
  added up; the row numbers are unioned and counted once.
- **Only what findings name.** A finding about a whole column names no row. The
  summary reports how many such findings exist so the interface can say that
  rows affected counts only rows findings point at, never "all other rows are
  clean".
- **Scope is carried, not assumed.** Completeness comes from the dataset
  profile; its sampled-or-full scope travels with the figure.
- **No content.** Only counts and the sampling scope; no cell value, no row
  number list, no hash.

Framework-independent: no FastAPI or SQLAlchemy import.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from trusttable_backend.detectors.contract import FindingCandidate
from trusttable_backend.domain.parsing import SamplingScope
from trusttable_backend.profiling.schemas import DatasetProfile


@dataclass(frozen=True, slots=True)
class CompletenessSummary:
    """Missing values across the profiled cells.

    `scope` is `"full"` or `"sampled"` exactly as the profile recorded it.
    `missing_share` is `None` when there are no cells to measure.
    """

    scope: Literal["full", "sampled"]
    population_size: int
    sample_size: int
    cells_total: int
    cells_missing: int
    missing_share: float | None


@dataclass(frozen=True, slots=True)
class DashboardSummary:
    """Bounded, content-free dashboard figures for one completed analysis."""

    row_count: int
    column_count: int
    rows_affected: int
    findings_total: int
    findings_without_row_detail: int
    completeness: CompletenessSummary


def _int_metric(profile: DatasetProfile, key: str) -> int:
    value = profile.dataset_metrics.get(key, 0)
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def distinct_affected_rows(findings: tuple[FindingCandidate, ...]) -> int:
    """Rows named by at least one finding, each counted once."""
    rows: set[int] = set()
    for finding in findings:
        rows.update(reference.row_number for reference in finding.affected_row_references)
    return len(rows)


def build_dashboard_summary(
    profile: DatasetProfile, findings: tuple[FindingCandidate, ...]
) -> DashboardSummary:
    """Compute the summary from a completed analysis's profile and findings."""
    row_count = _int_metric(profile, "row_count")
    column_count = _int_metric(profile, "column_count")
    cells_total = row_count * column_count
    cells_missing = min(sum(entry.null_count for entry in profile.column_profiles), cells_total)
    sampling = profile.sampling
    scope: Literal["full", "sampled"] = (
        "full" if sampling.scope is SamplingScope.FULL else "sampled"
    )
    completeness = CompletenessSummary(
        scope=scope,
        population_size=sampling.population_size,
        sample_size=sampling.sample_size,
        cells_total=cells_total,
        cells_missing=cells_missing,
        missing_share=(cells_missing / cells_total) if cells_total > 0 else None,
    )
    return DashboardSummary(
        row_count=row_count,
        column_count=column_count,
        rows_affected=distinct_affected_rows(findings),
        findings_total=len(findings),
        findings_without_row_detail=sum(
            1 for finding in findings if not finding.affected_row_references
        ),
        completeness=completeness,
    )
