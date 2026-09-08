"""v0.1 performance baseline evidence (PERF-01, scoped, WP-031).

Measures the real, already-implemented deterministic pipeline
(`parse_csv` -> `compute_dataset_profile` -> `run_detectors` ->
`calculate_finding_priority_scores` -> `calculate_trust_assessment`,
the same integration pattern proven in
`backend/tests/risk/test_scoring.py`'s end-to-end determinism check)
against synthetic, in-memory CSV content at 10,000, 100,000, and
250,000 rows, plus one wide-column (500 columns, the configured
`max_columns` limit) case.

This is scoped v0.1 release-qualification evidence, not the full v1.0
`PERF-01` backlog item (XLSX scale, AI-path timing, and any tuning work
remain open — see `WP-031-v01-performance-baseline.md`'s
`backlog_remaining`).

Skipped by default (opt in with `--run-performance`, registered by the
sibling `conftest.py`), matching `docs/testing-strategy.md` §8's
placement of "performance benchmark review" under release-candidate CI
gates, not pull-request gates. The default `backend` CI job
(`uv run pytest tests -v`, no `--run-performance` flag) collects these
tests and reports them skipped; it does not run them.

Synthetic content is generated in-memory with a fixed `random.Random`
seed per case and is deliberately independent of
`trusttable_backend.demo_data.generator` (not imported here — `DEMO-01`
has its own byte-identical-reproducibility contract that this package
does not touch or risk).
"""

from __future__ import annotations

import random
import time
import tracemalloc
from dataclasses import dataclass
from datetime import UTC, date, datetime

import pytest

from trusttable_backend.detectors.catalogue import DETECTORS
from trusttable_backend.detectors.contract import SecurityExposureState
from trusttable_backend.detectors.engine import run_detectors
from trusttable_backend.parsers.csv_parser import parse_csv
from trusttable_backend.profiling.metrics import compute_dataset_profile
from trusttable_backend.risk.scoring import (
    TrustAssessment,
    calculate_finding_priority_scores,
    calculate_trust_assessment,
)

NO_EXPOSURE = SecurityExposureState(model_provider_enabled=False, sample_transmission_enabled=False)
ANALYSIS_TIMESTAMP = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)
AS_OF = date(2026, 9, 7)

_CATEGORIES = ("Widgets", "Gadgets", "Components", "Accessories")
_REGIONS = ("North", "South", "East", "West")


def _make_mixed_csv(n_rows: int, *, seed: int) -> bytes:
    """A 12-column, mixed-type CSV mirroring the shape of a real sales dataset.

    Columns: a unique text identifier, an ISO date, two categorical/text
    columns of differing cardinality, four numeric measures (one
    derived), one mostly-empty text column, and one near-constant flag
    column — chosen so every detector category (structural, completeness,
    consistency, validity, statistical) has at least one applicable
    column to exercise at scale, not only numeric columns.
    """
    rng = random.Random(seed)
    header = (
        "order_id,order_date,customer_name,category,region,quantity,"
        "unit_price,discount_pct,tax_pct,line_total,notes,status_flag"
    )
    lines = [header]
    for i in range(n_rows):
        order_id = f"ORD-{i:08d}"
        order_date = f"2026-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}"
        customer_name = f"Customer_{rng.randint(1, max(1, n_rows // 5))}"
        category = rng.choice(_CATEGORIES)
        region = rng.choice(_REGIONS)
        quantity = rng.randint(1, 500)
        unit_price = round(rng.uniform(1, 500), 2)
        discount_pct = round(rng.uniform(0, 20), 2)
        tax_pct = round(rng.uniform(0, 15), 2)
        line_total = round(
            quantity * unit_price * (1 - discount_pct / 100) * (1 + tax_pct / 100), 2
        )
        notes = "Reviewed" if i % 500 == 0 else ""
        status_flag = "ACTIVE"
        lines.append(
            f"{order_id},{order_date},{customer_name},{category},{region},"
            f"{quantity},{unit_price},{discount_pct},{tax_pct},{line_total},"
            f"{notes},{status_flag}"
        )
    return ("\n".join(lines)).encode("utf-8")


def _make_wide_csv(n_rows: int, n_cols: int, *, seed: int) -> bytes:
    """An all-numeric CSV at the configured `max_columns` limit (column-dimension scale)."""
    rng = random.Random(seed)
    header = ",".join(f"measure_{c}" for c in range(n_cols))
    lines = [header]
    for _ in range(n_rows):
        lines.append(",".join(str(rng.randint(0, 100_000)) for _ in range(n_cols)))
    return ("\n".join(lines)).encode("utf-8")


@dataclass(frozen=True)
class _RunResult:
    duration_seconds: float
    peak_memory_bytes: int
    assessment: TrustAssessment


def _run_pipeline(content: bytes) -> _RunResult:
    tracemalloc.start()
    start = time.perf_counter()

    parsed = parse_csv(content)
    columns = parsed.parsed_dataset.columns
    dataset_profile = compute_dataset_profile(
        columns, parsed.rows, parsed.parsed_dataset.sampling, as_of=AS_OF
    )
    mapping_rows = tuple(
        {column.internal_key: row[column.ordinal] for column in columns} for row in parsed.rows
    )
    results = run_detectors(
        list(DETECTORS),
        dataset_profile=dataset_profile,
        rows=mapping_rows,
        row_references=parsed.parsed_dataset.row_references,
        confirmed_context=None,
        security_exposure=NO_EXPOSURE,
        analysis_timestamp=ANALYSIS_TIMESTAMP,
    )
    findings = tuple(finding for result in results for finding in result.findings)
    priority_scores = calculate_finding_priority_scores(findings, dataset_profile=dataset_profile)
    assessment = calculate_trust_assessment(
        findings, priority_scores, security_exposure=NO_EXPOSURE
    )

    duration = time.perf_counter() - start
    _current, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    return _RunResult(duration_seconds=duration, peak_memory_bytes=peak, assessment=assessment)


# Ceilings are ~3x the actual first observed value on the implementer's local
# development machine (WSL2, 2026-09-07), recorded verbatim in
# project-ops/quality/performance-baseline-v0.1.md, not pre-guessed numbers.
# They exist to catch a gross (e.g. superlinear) regression, not to assert a
# tight SLA — real observed local values were: 10k rows 1.802s/22.0MiB,
# 100k rows 19.538s/222.4MiB, 250k rows 49.330s/553.9MiB,
# wide (500 cols x 2,000 rows) 9.468s/146.3MiB. The near-linear row scaling
# (10k -> 100k: ~10.8x time for 10x rows; 100k -> 250k: ~2.5x time for 2.5x
# rows) shows no evidence of superlinear blow-up in the current pure-Python
# (no pandas/NumPy) profiling/detector implementation at this scale.
_CEILINGS_SECONDS = {
    10_000: 6.0,
    100_000: 60.0,
    250_000: 150.0,
    "wide": 30.0,
}


@pytest.mark.parametrize("n_rows", [10_000, 100_000, 250_000])
def test_mixed_pipeline_completes_within_ceiling(n_rows: int) -> None:
    content = _make_mixed_csv(n_rows, seed=42)
    result = _run_pipeline(content)

    assert result.assessment is not None
    assert result.assessment.finding_count >= 0
    assert result.duration_seconds < _CEILINGS_SECONDS[n_rows], (
        f"n_rows={n_rows}: pipeline took {result.duration_seconds:.2f}s, "
        f"exceeding the {_CEILINGS_SECONDS[n_rows]}s ceiling"
    )
    print(
        f"\n[performance] mixed n_rows={n_rows}: "
        f"duration={result.duration_seconds:.3f}s "
        f"peak_memory={result.peak_memory_bytes / (1024 * 1024):.1f}MiB "
        f"finding_count={result.assessment.finding_count}"
    )


def test_wide_columns_pipeline_completes_within_ceiling() -> None:
    n_rows, n_cols = 2_000, 500  # 500 columns is the configured max_columns limit.
    content = _make_wide_csv(n_rows, n_cols, seed=7)
    result = _run_pipeline(content)

    assert result.assessment is not None
    assert result.assessment.finding_count >= 0
    assert result.duration_seconds < _CEILINGS_SECONDS["wide"], (
        f"wide n_cols={n_cols}: pipeline took {result.duration_seconds:.2f}s, "
        f"exceeding the {_CEILINGS_SECONDS['wide']}s ceiling"
    )
    print(
        f"\n[performance] wide n_rows={n_rows} n_cols={n_cols}: "
        f"duration={result.duration_seconds:.3f}s "
        f"peak_memory={result.peak_memory_bytes / (1024 * 1024):.1f}MiB "
        f"finding_count={result.assessment.finding_count}"
    )
