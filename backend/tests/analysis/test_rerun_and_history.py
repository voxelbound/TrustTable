"""Service-level proof for `rerun_analysis`, summaries and the in-memory lookup
(`UX-03`, D-069). The HTTP and SQL behaviour is covered in
`tests/api/test_analysis_history.py`."""

from __future__ import annotations

from dataclasses import replace

import pytest

from trusttable_backend.analysis import (
    AnalysisNotFoundError,
    AnalysisNotRerunnableError,
    AnalysisState,
    AnalysisStore,
    AnalysisSummary,
    create_analysis,
    rerun_analysis,
    run_analysis,
    summarize_analysis,
)
from trusttable_backend.analysis.history import (
    LOOKUP_LIMIT,
    PreviousAnalysisKind,
    find_previous_analysis_notice,
)


def _completed(store: AnalysisStore):  # type: ignore[no-untyped-def]
    analysis = create_analysis(store)
    run_analysis(store, analysis.analysis_id)
    done = store.get(analysis.analysis_id)
    assert done is not None and done.state is AnalysisState.COMPLETED
    return done


def test_rerun_of_a_completed_analysis_is_new_empty_and_unlinked() -> None:
    store = AnalysisStore()
    original = _completed(store)

    rerun = rerun_analysis(store, original.analysis_id)

    assert rerun.analysis_id != original.analysis_id
    assert rerun.dataset.dataset_id != original.dataset.dataset_id
    assert rerun.state is AnalysisState.QUEUED
    assert rerun.content == original.content
    assert rerun.findings == () and rerun.rules == () and rerun.finding_reviews == {}
    fresh = create_analysis(AnalysisStore())
    assert rerun.context is None
    assert rerun.ai_enrichment == fresh.ai_enrichment  # a brand-new, empty record
    assert rerun.retry_source_analysis_id is None
    assert store.get(original.analysis_id) == original


def test_rerun_refuses_an_unfinished_analysis_and_an_unknown_one() -> None:
    store = AnalysisStore()
    queued = create_analysis(store)
    with pytest.raises(AnalysisNotRerunnableError):
        rerun_analysis(store, queued.analysis_id)
    with pytest.raises(AnalysisNotFoundError):
        rerun_analysis(store, "missing")


def test_a_summary_holds_no_content_hash_or_findings() -> None:
    summary = summarize_analysis(_completed(AnalysisStore()))
    fields = set(AnalysisSummary.__dataclass_fields__)
    assert not any("hash" in f or "content" in f or "sha" in f for f in fields)
    assert "findings" not in fields
    assert summary.trust_label is not None


def test_the_in_memory_lookup_is_bounded_completed_only_and_forgets_deleted() -> None:
    store = AnalysisStore()
    done = _completed(store)
    digest = done.dataset.content_hash
    store.add(replace(create_analysis(store)))  # a queued twin: not counted

    notice = find_previous_analysis_notice(
        store, content_sha256=digest, filename="somethingelse.csv"
    )
    assert notice is not None
    assert notice.kind is PreviousAnalysisKind.SAME_FILE
    assert notice.count == 1 and notice.latest.analysis_id == done.analysis_id
    assert len(store.find_completed_by_content_hash(digest, 0)) == 0
    assert len(store.list_recent(0)) == 0

    store.delete(done.analysis_id)
    assert find_previous_analysis_notice(store, content_sha256=digest, filename="x.csv") is None


def test_lookup_limit_caps_the_count() -> None:
    store = AnalysisStore()
    base = _completed(store)
    for _ in range(LOOKUP_LIMIT + 5):
        copy = create_analysis(store)
        store.replace(replace(base, analysis_id=copy.analysis_id))
    notice = find_previous_analysis_notice(
        store, content_sha256=base.dataset.content_hash, filename="x.csv"
    )
    assert notice is not None and notice.count == LOOKUP_LIMIT
