"""HTTP and unit tests for the dashboard summary (`UX-04`, D-070).

The properties under test: rows affected is the number of *distinct* rows, not
the sum of per-finding counts; whole-column findings are counted separately so
the figure is never read as "the rest is clean"; the sampled-or-full scope of
completeness is carried; and the response holds counts only.
"""

from __future__ import annotations

import hashlib
import time
from types import SimpleNamespace
from typing import Any, cast

from fastapi.testclient import TestClient

from trusttable_backend.analysis import create_analysis
from trusttable_backend.analysis.summary import build_dashboard_summary, distinct_affected_rows
from trusttable_backend.detectors.contract import FindingCandidate
from trusttable_backend.domain.parsing import SamplingScope
from trusttable_backend.profiling.schemas import DatasetProfile

# Two identical rows (duplicate findings) that also share a missing value, so
# several findings point at the same rows.
_CSV = b"id,name,amount\n1,Ada,10\n2,Grace,\n2,Grace,\n3,Linus,30\n4,,40\n5,Alan,50\n"
_DIGEST = hashlib.sha256(_CSV).hexdigest()
_TERMINAL = {"completed", "failed", "cancelled"}


def _wait_terminal(client: TestClient, analysis_id: str, timeout: float = 15.0) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        state = client.get(f"/api/v1/analyses/{analysis_id}/status").json()["state"]
        if state in _TERMINAL:
            return str(state)
        time.sleep(0.01)
    raise AssertionError("analysis did not finish")


def _analyse(client: TestClient, content: bytes = _CSV) -> str:
    staged = client.post(
        "/api/v1/staged-uploads", files={"file": ("data.csv", content, "text/csv")}
    )
    ref = staged.json()["staging_ref"]
    run = client.post("/api/v1/staged-uploads/run", json={"staging_ref": ref, "worksheet": None})
    assert run.status_code == 202
    analysis_id = str(run.json()["analysis"]["analysis_id"])
    assert _wait_terminal(client, analysis_id) == "completed"
    return analysis_id


def _finding(rows: tuple[int, ...]) -> FindingCandidate:
    refs = tuple(SimpleNamespace(row_number=row) for row in rows)
    return cast(FindingCandidate, SimpleNamespace(affected_row_references=refs))


# --- distinct rows (pure) ---------------------------------------------------


def test_distinct_rows_are_counted_once_across_overlapping_findings() -> None:
    findings = (_finding((1, 2, 3)), _finding((2, 3, 4)), _finding((3,)))
    assert distinct_affected_rows(findings) == 4  # not 7


def test_distinct_rows_is_zero_with_no_findings_or_only_column_wide_findings() -> None:
    assert distinct_affected_rows(()) == 0
    assert distinct_affected_rows((_finding(()), _finding(()))) == 0


# --- build_dashboard_summary with stand-in profiles (pure) --------------------


def _profile(
    *,
    row_count: int,
    column_count: int,
    nulls: tuple[int, ...],
    scope: SamplingScope,
    population: int,
    sample: int,
) -> DatasetProfile:
    return cast(
        DatasetProfile,
        SimpleNamespace(
            dataset_metrics={"row_count": row_count, "column_count": column_count},
            column_profiles=tuple(SimpleNamespace(null_count=n) for n in nulls),
            sampling=SimpleNamespace(scope=scope, population_size=population, sample_size=sample),
        ),
    )


def test_summary_carries_a_sampled_scope_and_its_sizes() -> None:
    profile = _profile(
        row_count=50,
        column_count=2,
        nulls=(5, 0),
        scope=SamplingScope.SAMPLED,
        population=1000,
        sample=50,
    )

    summary = build_dashboard_summary(profile, (_finding((1, 2)), _finding((2,))))

    completeness = summary.completeness
    assert completeness.scope == "sampled"
    assert (completeness.population_size, completeness.sample_size) == (1000, 50)
    assert completeness.cells_total == 100  # profiled rows x columns, not population
    assert completeness.cells_missing == 5
    assert summary.row_count == 50  # the profiled rows, the same rows as the share
    assert summary.rows_affected == 2
    assert summary.findings_total == 2


def test_summary_full_scope_is_reported_as_full() -> None:
    profile = _profile(
        row_count=10,
        column_count=1,
        nulls=(0,),
        scope=SamplingScope.FULL,
        population=10,
        sample=10,
    )
    assert build_dashboard_summary(profile, ()).completeness.scope == "full"


def test_summary_clamps_missing_cells_to_the_cell_total() -> None:
    profile = _profile(
        row_count=2,
        column_count=1,
        nulls=(9,),
        scope=SamplingScope.FULL,
        population=2,
        sample=2,
    )
    completeness = build_dashboard_summary(profile, ()).completeness
    assert completeness.cells_missing == completeness.cells_total == 2
    assert completeness.missing_share == 1.0


def test_summary_with_no_cells_is_not_measured_rather_than_zero() -> None:
    profile = _profile(
        row_count=0,
        column_count=3,
        nulls=(0, 0, 0),
        scope=SamplingScope.FULL,
        population=0,
        sample=0,
    )
    completeness = build_dashboard_summary(profile, ()).completeness
    assert completeness.cells_total == 0
    assert completeness.missing_share is None


# --- the route --------------------------------------------------------------


def test_summary_rows_affected_equals_the_union_of_finding_rows(client: TestClient) -> None:
    analysis_id = _analyse(client)

    summary = client.get(f"/api/v1/analyses/{analysis_id}/summary").json()
    items = client.get(f"/api/v1/analyses/{analysis_id}/findings").json()["items"]
    union: set[int] = set()
    summed = 0
    column_wide = 0
    for item in items:
        detail = client.get(f"/api/v1/analyses/{analysis_id}/findings/{item['finding_id']}").json()
        rows = detail["affected_row_numbers"]
        union.update(rows)
        summed += len(rows)
        if not rows:
            column_wide += 1

    assert summary["analysis_id"] == analysis_id
    assert summary["rows_affected"] == len(union)
    assert summary["findings_total"] == len(items)
    assert summary["findings_without_row_detail"] == column_wide
    assert summary["rows_affected"] <= summary["row_count"]
    # The fixture is built so that findings overlap; the figure must not be the sum.
    assert summed > summary["rows_affected"]


def test_summary_reports_shape_and_completeness_with_scope(client: TestClient) -> None:
    analysis_id = _analyse(client)

    summary = client.get(f"/api/v1/analyses/{analysis_id}/summary").json()

    assert summary["row_count"] == 6
    assert summary["column_count"] == 3
    completeness = summary["completeness"]
    assert completeness["scope"] == "full"  # a 6-row file is never sampled
    assert completeness["population_size"] == completeness["sample_size"] == 6
    assert completeness["cells_total"] == 18
    assert 0 < completeness["cells_missing"] <= completeness["cells_total"]
    assert completeness["missing_share"] == (
        completeness["cells_missing"] / completeness["cells_total"]
    )
    if completeness["scope"] == "full":
        assert completeness["sample_size"] == completeness["population_size"]


def test_summary_is_counts_only_with_no_content_or_digest(client: TestClient) -> None:
    analysis_id = _analyse(client)

    response = client.get(f"/api/v1/analyses/{analysis_id}/summary")

    assert set(cast(dict[str, Any], response.json())) == {
        "analysis_id",
        "row_count",
        "column_count",
        "rows_affected",
        "findings_total",
        "findings_without_row_detail",
        "completeness",
    }
    assert _DIGEST not in response.text
    assert "content_hash" not in response.text
    assert "Grace" not in response.text
    assert "Linus" not in response.text


def test_summary_unknown_analysis_is_not_found(client: TestClient) -> None:
    response = client.get("/api/v1/analyses/does-not-exist/summary")
    assert response.status_code == 404


def test_summary_before_completion_is_a_conflict(client: TestClient) -> None:
    # A queued analysis is created directly (no worker runs it), so the state is
    # deterministic. The route must refuse rather than return zeroed figures that
    # look like a clean result.
    queued = create_analysis(client.app.state.analysis_store)  # type: ignore[attr-defined]

    response = client.get(f"/api/v1/analyses/{queued.analysis_id}/summary")

    assert response.status_code == 409
    assert "INVALID_ANALYSIS_STATE" in response.text
