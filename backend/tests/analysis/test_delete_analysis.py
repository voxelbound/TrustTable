"""`delete_analysis` and the update-only `replace` on both stores (`DEL-01`)."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from trusttable_backend.analysis.service import (
    AnalysisNotFoundError,
    AnalysisState,
    AnalysisStore,
    AnalysisStoreProtocol,
    create_analysis,
    delete_analysis,
)
from trusttable_backend.config import Settings
from trusttable_backend.persistence import SqlAnalysisStore, build_engine, run_migrations


def _sql_store(tmp_path: Path) -> SqlAnalysisStore:
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path / 'delete.db'}",
        data_directory=str(tmp_path),
    )
    engine = build_engine(settings)
    run_migrations(settings)
    return SqlAnalysisStore(engine)


@pytest.fixture(params=["memory", "sql"])
def store(request: pytest.FixtureRequest, tmp_path: Path) -> AnalysisStoreProtocol:
    if request.param == "memory":
        return AnalysisStore()
    return _sql_store(tmp_path)


def test_delete_removes_the_analysis_and_only_that_one(store: AnalysisStoreProtocol) -> None:
    doomed = create_analysis(store)
    kept = create_analysis(store)

    delete_analysis(store, doomed.analysis_id)

    assert store.get(doomed.analysis_id) is None
    assert store.get(kept.analysis_id) == kept


def test_deleting_an_unknown_or_deleted_analysis_raises(store: AnalysisStoreProtocol) -> None:
    analysis = create_analysis(store)
    delete_analysis(store, analysis.analysis_id)

    for analysis_id in (analysis.analysis_id, "never-existed"):
        with pytest.raises(AnalysisNotFoundError):
            delete_analysis(store, analysis_id)


def test_a_late_replace_cannot_bring_a_deleted_analysis_back(
    store: AnalysisStoreProtocol,
) -> None:
    """The reviewed hazard: a worker still holding the analysis writes its
    next stage after the analysis was deleted."""
    analysis = create_analysis(store)
    stale = store.get(analysis.analysis_id)
    assert stale is not None
    delete_analysis(store, analysis.analysis_id)

    store.replace(replace(stale, state=AnalysisState.PARSING, started_at=datetime.now(UTC)))
    store.replace(stale)

    assert store.get(analysis.analysis_id) is None


def test_replace_still_updates_an_existing_analysis(store: AnalysisStoreProtocol) -> None:
    analysis = create_analysis(store)

    started = replace(analysis, state=AnalysisState.PARSING, started_at=datetime.now(UTC))
    store.replace(started)

    assert store.get(analysis.analysis_id) == started


def test_a_late_enrichment_update_for_a_deleted_analysis_is_ignored(
    store: AnalysisStoreProtocol,
) -> None:
    analysis = create_analysis(store)
    delete_analysis(store, analysis.analysis_id)

    store.update_ai_enrichment(analysis.analysis_id, lambda current: current)

    assert store.get(analysis.analysis_id) is None
