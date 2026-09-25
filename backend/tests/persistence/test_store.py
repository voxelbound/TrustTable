"""Tests for `SqlAnalysisStore` (`DB-01`, `WP-074` AC-02/AC-03)."""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest

from trusttable_backend.analysis.service import (
    Analysis,
    AnalysisFailure,
    AnalysisState,
    confirm_context_fields,
    create_analysis,
    finalize_context,
    get_or_infer_context,
    run_analysis,
)
from trusttable_backend.analysis.service import (
    AnalysisStore as InMemoryStore,
)
from trusttable_backend.config import Settings
from trusttable_backend.detectors.contract import SecurityExposureState
from trusttable_backend.domain.context import ContextField
from trusttable_backend.persistence import SqlAnalysisStore, build_engine, run_migrations
from trusttable_backend.persistence.models import AnalysisRecord


@pytest.fixture
def store(tmp_path: Path) -> SqlAnalysisStore:
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path / 'trusttable.db'}",
        data_directory=str(tmp_path),
    )
    run_migrations(settings)
    return SqlAnalysisStore(build_engine(settings))


def test_get_returns_none_for_an_unknown_analysis_id(store: SqlAnalysisStore) -> None:
    assert store.get("does-not-exist") is None


def test_add_then_get_round_trips_a_queued_analysis(store: SqlAnalysisStore) -> None:
    # `create_analysis` needs *some* store to construct against; a plain
    # in-memory one is enough since only the resulting `Analysis` value
    # (not that store) is persisted through `SqlAnalysisStore` below.
    analysis = create_analysis(InMemoryStore())

    store.add(analysis)
    round_tripped = store.get(analysis.analysis_id)

    assert round_tripped == analysis


def test_replace_upserts_an_unknown_analysis_id(store: SqlAnalysisStore) -> None:
    analysis = create_analysis(InMemoryStore())

    store.replace(analysis)  # never previously added

    assert store.get(analysis.analysis_id) == analysis


def test_replace_overwrites_an_existing_row(store: SqlAnalysisStore) -> None:
    analysis = create_analysis(InMemoryStore())
    store.add(analysis)

    cancelled = replace(analysis, state=AnalysisState.CANCELLED, cancelled_at=datetime.now(UTC))
    store.replace(cancelled)

    assert store.get(analysis.analysis_id) == cancelled


def test_failed_analysis_round_trips_byte_identical(store: SqlAnalysisStore) -> None:
    now = datetime.now(UTC)
    failed = Analysis(
        analysis_id="a-failed",
        dataset=create_analysis(InMemoryStore()).dataset,
        content=b"irrelevant,content\n1,2\n",
        state=AnalysisState.FAILED,
        security_exposure=SecurityExposureState(
            model_provider_enabled=False, sample_transmission_enabled=False
        ),
        dataset_profile=None,
        findings=(),
        priority_scores=(),
        evidence=(),
        trust_assessment=None,
        failure=AnalysisFailure(code="analysis.pipeline_failed", message="boom"),
        created_at=now,
        started_at=now,
        completed_at=None,
        failed_at=now,
        cancelled_at=None,
    )

    store.add(failed)

    assert store.get("a-failed") == failed


def test_completed_analysis_with_full_context_round_trips_byte_identical(
    store: SqlAnalysisStore,
) -> None:
    working_store = InMemoryStore()
    analysis = create_analysis(working_store)
    completed = run_analysis(working_store, analysis.analysis_id)
    assert completed.state is AnalysisState.COMPLETED
    assert completed.findings  # the demo dataset must yield at least one finding

    get_or_infer_context(working_store, completed.analysis_id)
    confirm_context_fields(
        working_store,
        completed.analysis_id,
        {ContextField.PROBABLE_DOMAIN: "sales"},
        expected_version=1,
    )
    finalized = finalize_context(working_store, completed.analysis_id, expected_version=2)

    store.add(finalized)
    round_tripped = store.get(finalized.analysis_id)

    assert round_tripped == finalized
    assert round_tripped is not None
    assert round_tripped.context is not None
    assert round_tripped.context.probable_domain.value == "sales"
    assert round_tripped.context_finalized is True
    assert round_tripped.content == finalized.content


# ---------------------------------------------------------------------------
# AC-03: a malformed persisted row raises on read
# ---------------------------------------------------------------------------


def test_get_raises_on_a_corrupted_persisted_row(store: SqlAnalysisStore) -> None:
    analysis = create_analysis(InMemoryStore())
    store.add(analysis)

    # Corrupt the row directly at the database layer (bypassing the store's
    # own write path entirely) to violate `Dataset.__post_init__`'s
    # non-empty `original_filename` invariant.
    with store._session_factory() as session:  # noqa: SLF001 - white-box corruption for this test only
        row = session.get(AnalysisRecord, analysis.analysis_id)
        assert row is not None
        dataset_json = dict(row.dataset_json)
        dataset_json["f"] = dict(dataset_json["f"])
        dataset_json["f"]["original_filename"] = ""
        row.dataset_json = dataset_json
        session.commit()

    with pytest.raises(ValueError, match="original_filename"):
        store.get(analysis.analysis_id)


def test_non_terminal_analysis_ids_excludes_terminal_states(store: SqlAnalysisStore) -> None:
    working_store = InMemoryStore()
    queued = create_analysis(working_store)
    completed = run_analysis(working_store, create_analysis(working_store).analysis_id)

    store.add(queued)
    store.add(completed)

    non_terminal = store.non_terminal_analysis_ids()

    assert queued.analysis_id in non_terminal
    assert completed.analysis_id not in non_terminal
