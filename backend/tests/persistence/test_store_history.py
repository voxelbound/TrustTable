"""`SqlAnalysisStore.list_recent` / `find_completed_by_content_hash` and the
`content_sha256` column (`UX-03`, D-069): the durable path the HTTP tests reach
only indirectly -- the 50-row bound, ordering, the digest key and its backfill."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Engine

from trusttable_backend.analysis import (
    Analysis,
    AnalysisState,
    AnalysisStore,
    create_analysis,
    run_analysis,
)
from trusttable_backend.analysis.history import LOOKUP_LIMIT
from trusttable_backend.config import Settings
from trusttable_backend.persistence import SqlAnalysisStore, build_engine, run_migrations

_BASE = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


def _engine(tmp_path: Path) -> Engine:
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path / 'history.db'}",
        data_directory=str(tmp_path),
    )
    engine = build_engine(settings)
    run_migrations(settings)
    return engine


def _completed() -> Analysis:
    memory = AnalysisStore()
    analysis = create_analysis(memory)
    run_analysis(memory, analysis.analysis_id)
    done = memory.get(analysis.analysis_id)
    assert done is not None and done.state is AnalysisState.COMPLETED
    return done


def _copy(done: Analysis, index: int, *, created_at: datetime | None = None) -> Analysis:
    return replace(
        done,
        analysis_id=f"id-{index:03d}",
        created_at=created_at or _BASE + timedelta(seconds=index),
    )


def _digest(done: Analysis) -> str:
    return hashlib.sha256(done.content).hexdigest()


def test_the_lookup_is_bounded_and_returns_the_newest_matches_first(tmp_path: Path) -> None:
    store = SqlAnalysisStore(_engine(tmp_path))
    done = _completed()
    for index in range(LOOKUP_LIMIT + 5):
        store.add(_copy(done, index))

    found = store.find_completed_by_content_hash(_digest(done), LOOKUP_LIMIT)

    assert len(found) == LOOKUP_LIMIT
    ids = [summary.analysis_id for summary in found]
    assert ids[0] == f"id-{LOOKUP_LIMIT + 4:03d}"
    assert ids == sorted(ids, reverse=True)
    assert len(store.find_completed_by_content_hash(_digest(done), 3)) == 3
    assert store.find_completed_by_content_hash(_digest(done), 0) == ()


def test_equal_timestamps_are_ordered_by_analysis_id_in_both_stores(tmp_path: Path) -> None:
    sql = SqlAnalysisStore(_engine(tmp_path))
    memory = AnalysisStore()
    done = _completed()
    for index in (2, 0, 1):
        same_moment = _copy(done, index, created_at=_BASE)
        sql.add(same_moment)
        memory.add(same_moment)

    expected = ["id-000", "id-001", "id-002"]
    assert [s.analysis_id for s in sql.list_recent(10)] == expected
    assert [s.analysis_id for s in memory.list_recent(10)] == expected
    digest = _digest(done)
    assert [s.analysis_id for s in sql.find_completed_by_content_hash(digest, 10)] == expected
    assert [s.analysis_id for s in memory.find_completed_by_content_hash(digest, 10)] == expected


def test_both_stores_key_the_lookup_on_the_stored_bytes_not_the_dataset_field(
    tmp_path: Path,
) -> None:
    sql = SqlAnalysisStore(_engine(tmp_path))
    memory = AnalysisStore()
    done = _completed()
    wrong_field = replace(done.dataset, content_hash="0" * 64)
    liar = replace(done, analysis_id="liar", dataset=wrong_field)
    sql.add(liar)
    memory.add(liar)

    for store in (sql, memory):
        assert [s.analysis_id for s in store.find_completed_by_content_hash(_digest(done), 5)] == [
            "liar"
        ]
        assert store.find_completed_by_content_hash("0" * 64, 5) == ()


def test_only_completed_analyses_are_found(tmp_path: Path) -> None:
    store = SqlAnalysisStore(_engine(tmp_path))
    done = _completed()
    store.add(replace(done, analysis_id="done"))
    unfinished = create_analysis(AnalysisStore())  # same demo bytes, but still queued
    assert unfinished.state is AnalysisState.QUEUED
    store.add(replace(unfinished, analysis_id="queued"))
    found = store.find_completed_by_content_hash(_digest(done), 10)
    assert [s.analysis_id for s in found] == ["done"]


def test_add_backfills_a_missing_digest_and_replace_never_changes_it(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    store = SqlAnalysisStore(engine)
    done = _completed()
    store.add(replace(done, analysis_id="a"))

    def stored() -> str | None:
        with engine.connect() as connection:
            return connection.execute(
                text("SELECT content_sha256 FROM analyses WHERE analysis_id = 'a'")
            ).scalar()

    assert stored() == _digest(done)

    with engine.begin() as connection:
        connection.execute(
            text("UPDATE analyses SET content_sha256 = NULL WHERE analysis_id = 'a'")
        )
    assert stored() is None
    store.replace(replace(done, analysis_id="a"))
    assert stored() is None  # a whole-analysis update leaves the column alone
    store.add(replace(done, analysis_id="a"))
    assert stored() == _digest(done)  # a re-add fills only a missing digest

    with engine.begin() as connection:
        connection.execute(
            text("UPDATE analyses SET content_sha256 = 'kept' WHERE analysis_id = 'a'")
        )
    store.add(replace(done, analysis_id="a"))
    assert stored() == "kept"


def test_a_deleted_analysis_is_gone_from_the_list_and_the_lookup(tmp_path: Path) -> None:
    store = SqlAnalysisStore(_engine(tmp_path))
    done = _completed()
    store.add(replace(done, analysis_id="x"))
    assert store.delete("x") is True
    assert store.list_recent(5) == ()
    assert store.find_completed_by_content_hash(_digest(done), 5) == ()
