"""Tests for `reconcile_interrupted_analyses` (`DB-01`, `WP-074`
AC-05)."""

from __future__ import annotations

from pathlib import Path

import pytest

from trusttable_backend.analysis.service import (
    AnalysisState,
    create_analysis,
    run_analysis,
)
from trusttable_backend.analysis.service import (
    AnalysisStore as InMemoryStore,
)
from trusttable_backend.config import Settings
from trusttable_backend.persistence import SqlAnalysisStore, build_engine, run_migrations
from trusttable_backend.persistence.reconciliation import (
    INTERRUPTED_BY_RESTART_CODE,
    reconcile_interrupted_analyses,
)


@pytest.fixture
def store(tmp_path: Path) -> SqlAnalysisStore:
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path / 'trusttable.db'}",
        data_directory=str(tmp_path),
    )
    run_migrations(settings)
    return SqlAnalysisStore(build_engine(settings))


def test_reconciles_a_queued_analysis_to_failed_with_the_fixed_code(
    store: SqlAnalysisStore,
) -> None:
    queued = create_analysis(InMemoryStore())
    store.add(queued)

    transitioned = reconcile_interrupted_analyses(store)

    assert transitioned == (queued.analysis_id,)
    reconciled = store.get(queued.analysis_id)
    assert reconciled is not None
    assert reconciled.state is AnalysisState.FAILED
    assert reconciled.failure is not None
    assert reconciled.failure.code == INTERRUPTED_BY_RESTART_CODE
    assert reconciled.failed_at is not None


def test_leaves_a_completed_analysis_completely_unchanged(store: SqlAnalysisStore) -> None:
    working_store = InMemoryStore()
    completed = run_analysis(working_store, create_analysis(working_store).analysis_id)
    assert completed.state is AnalysisState.COMPLETED
    store.add(completed)

    transitioned = reconcile_interrupted_analyses(store)

    assert transitioned == ()
    assert store.get(completed.analysis_id) == completed


def test_reconciles_only_non_terminal_siblings_leaving_completed_ones_untouched(
    store: SqlAnalysisStore,
) -> None:
    working_store = InMemoryStore()
    interrupted = create_analysis(working_store)
    completed = run_analysis(working_store, create_analysis(working_store).analysis_id)
    store.add(interrupted)
    store.add(completed)

    transitioned = reconcile_interrupted_analyses(store)

    assert set(transitioned) == {interrupted.analysis_id}
    reconciled = store.get(interrupted.analysis_id)
    assert reconciled is not None
    assert reconciled.state is AnalysisState.FAILED
    assert store.get(completed.analysis_id) == completed


def test_no_op_when_no_analysis_is_persisted(store: SqlAnalysisStore) -> None:
    assert reconcile_interrupted_analyses(store) == ()


def test_is_idempotent_a_second_run_finds_nothing_left_to_reconcile(
    store: SqlAnalysisStore,
) -> None:
    queued = create_analysis(InMemoryStore())
    store.add(queued)

    first = reconcile_interrupted_analyses(store)
    second = reconcile_interrupted_analyses(store)

    assert first == (queued.analysis_id,)
    assert second == ()
