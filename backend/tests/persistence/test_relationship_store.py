"""`SqlRelationshipStore` and migration `0007` (`DET-03`)."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError

from trusttable_backend.analysis.service import AnalysisStore, create_analysis
from trusttable_backend.config import Settings
from trusttable_backend.domain.confirmed_relationship import (
    ConfirmationSource,
    Rejection,
    RejectionCode,
    RelationshipKind,
    RelationshipVersion,
    RoleColumn,
    Transition,
    TransitionRequest,
    next_version,
)
from trusttable_backend.persistence import (
    SqlAnalysisStore,
    SqlRelationshipStore,
    build_engine,
    run_migrations,
)
from trusttable_backend.persistence.database import _BACKEND_ROOT

NOW = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)
START = RoleColumn("start_date", 0)
END = RoleColumn("end_date", 1)


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path / 'relationships.db'}",
        data_directory=str(tmp_path),
    )


def _engine(tmp_path: Path, analysis_ids: tuple[str, ...] = ("a1", "a2")) -> Engine:
    settings = _settings(tmp_path)
    engine = build_engine(settings)
    run_migrations(settings)
    analyses = SqlAnalysisStore(engine)
    template = create_analysis(AnalysisStore())
    for analysis_id in analysis_ids:
        analyses.add(replace(template, analysis_id=analysis_id))
    return engine


def _request(transition: Transition, **overrides: object) -> TransitionRequest:
    fields: dict[str, object] = {
        "transition": transition,
        "kind": RelationshipKind.START_END_DATE,
        "source": ConfirmationSource.DIRECT,
    }
    if transition is Transition.CONFIRM:
        fields.update(start=START, end=END)
    elif transition is Transition.REPLACE:
        fields.update(relationship_id="r1", expected_version=1, start=END, end=START)
    else:
        fields.update(relationship_id="r1", expected_version=1)
    fields.update(overrides)
    return TransitionRequest(**fields)  # type: ignore[arg-type]


def _decider(
    analysis_id: str, request: TransitionRequest, new_id: str = "r1"
) -> Callable[[tuple[RelationshipVersion, ...]], RelationshipVersion | Rejection]:
    def decide(
        versions: tuple[RelationshipVersion, ...],
    ) -> RelationshipVersion | Rejection:
        return next_version(
            request, versions, new_relationship_id=new_id, recorded_at=NOW, analysis_id=analysis_id
        )

    return decide


def _count(engine: Engine, analysis_id: str | None = None) -> int:
    query = "SELECT COUNT(*) FROM confirmed_relationship_versions"
    params: dict[str, str] = {}
    if analysis_id is not None:
        query += " WHERE analysis_id = :analysis_id"
        params["analysis_id"] = analysis_id
    with engine.connect() as connection:
        return int(connection.execute(text(query), params).scalar_one())


def test_round_trip_preserves_every_field_in_insertion_order(tmp_path: Path) -> None:
    store = SqlRelationshipStore(_engine(tmp_path))

    first = store.append("a1", _decider("a1", _request(Transition.CONFIRM)))
    second = store.append("a1", _decider("a1", _request(Transition.REPLACE)))
    third = store.append("a1", _decider("a1", _request(Transition.WITHDRAW, expected_version=2)))

    assert isinstance(first, RelationshipVersion)
    assert isinstance(second, RelationshipVersion)
    assert isinstance(third, RelationshipVersion)
    assert store.list_versions("a1") == (first, second, third)
    assert store.list_versions("a2") == ()
    assert first.recorded_at == NOW
    assert second.start == END and second.end == START


def test_a_refusal_stores_nothing(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    store = SqlRelationshipStore(engine)
    store.append("a1", _decider("a1", _request(Transition.CONFIRM)))

    stale = store.append("a1", _decider("a1", _request(Transition.REPLACE, expected_version=9)))

    assert isinstance(stale, Rejection)
    assert stale.code is RejectionCode.VERSION_CONFLICT
    assert _count(engine) == 1


def test_a_write_for_a_missing_analysis_stores_nothing(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    store = SqlRelationshipStore(engine)

    result = store.append("gone", _decider("gone", _request(Transition.CONFIRM)))

    assert result is None
    assert _count(engine) == 0


def test_a_late_write_after_deletion_cannot_recreate_rows(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    analyses = SqlAnalysisStore(engine)
    store = SqlRelationshipStore(engine)
    store.append("a1", _decider("a1", _request(Transition.CONFIRM)))

    def decide_after_delete(
        versions: tuple[RelationshipVersion, ...],
    ) -> RelationshipVersion | Rejection:
        # The analysis is deleted after the history was read, before the insert.
        assert analyses.delete("a1") is True
        return next_version(
            _request(Transition.REPLACE),
            versions,
            new_relationship_id="r1",
            recorded_at=NOW,
            analysis_id="a1",
        )

    result = store.append("a1", decide_after_delete)

    assert result is None
    assert _count(engine) == 0


def test_delete_removes_only_the_deleted_analysis_versions(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    analyses, store = SqlAnalysisStore(engine), SqlRelationshipStore(engine)
    for analysis_id in ("a1", "a2"):
        store.append(analysis_id, _decider(analysis_id, _request(Transition.CONFIRM)))
        store.append(analysis_id, _decider(analysis_id, _request(Transition.REPLACE)))
    assert _count(engine) == 4

    assert analyses.delete("a1") is True

    assert _count(engine, "a1") == 0
    assert _count(engine, "a2") == 2
    assert len(store.list_versions("a2")) == 2


def test_two_writers_with_the_same_expected_version_yield_exactly_one_winner(
    tmp_path: Path,
) -> None:
    """Two independent stores share no lock, so only the unique key can stop
    the second writer. Both read the same history before either inserts."""
    engine = _engine(tmp_path)
    first_store, second_store = SqlRelationshipStore(engine), SqlRelationshipStore(engine)
    first_store.append("a1", _decider("a1", _request(Transition.CONFIRM)))
    barrier = threading.Barrier(2, timeout=10)
    results: list[object] = []

    def write(store: SqlRelationshipStore) -> None:
        inner = _decider("a1", _request(Transition.REPLACE))
        calls = {"n": 0}

        def decide(
            versions: tuple[RelationshipVersion, ...],
        ) -> RelationshipVersion | Rejection:
            calls["n"] += 1
            if calls["n"] == 1:
                barrier.wait()
            return inner(versions)

        results.append(store.append("a1", decide))

    threads = [threading.Thread(target=write, args=(s,)) for s in (first_store, second_store)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    winners = [r for r in results if isinstance(r, RelationshipVersion)]
    losers = [r for r in results if isinstance(r, Rejection)]
    assert len(winners) == 1 and len(losers) == 1
    assert losers[0].code is RejectionCode.VERSION_CONFLICT
    assert [v.version for v in first_store.list_versions("a1")] == [1, 2]


def test_many_threads_on_one_store_produce_one_new_version(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    store = SqlRelationshipStore(engine)
    store.append("a1", _decider("a1", _request(Transition.CONFIRM)))
    results: list[object] = []

    def write() -> None:
        results.append(store.append("a1", _decider("a1", _request(Transition.REPLACE))))

    threads = [threading.Thread(target=write) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert sum(isinstance(r, RelationshipVersion) for r in results) == 1
    assert sum(isinstance(r, Rejection) for r in results) == 7
    assert [v.version for v in store.list_versions("a1")] == [1, 2]


def test_the_unique_key_rejects_a_duplicate_version_directly(tmp_path: Path) -> None:
    engine = _engine(tmp_path)
    store = SqlRelationshipStore(engine)
    store.append("a1", _decider("a1", _request(Transition.CONFIRM)))
    duplicate = (
        "INSERT INTO confirmed_relationship_versions (analysis_id, relationship_id, version, "
        "kind, transition, start_key, start_ordinal, end_key, end_ordinal, source, recorded_at) "
        "VALUES ('a1', 'r1', 1, 'start_end_date', 'confirm', 's', 0, 'e', 1, 'direct', 'x')"
    )

    with pytest.raises(IntegrityError), engine.begin() as connection:
        connection.execute(text(duplicate))


def test_migration_0007_upgrades_downgrades_and_reupgrades_cleanly(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    engine = build_engine(settings)
    config = Config(str(_BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(_BACKEND_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", settings.database_url)

    command.upgrade(config, "0006")
    assert "confirmed_relationship_versions" not in inspect(engine).get_table_names()

    command.upgrade(config, "0007")
    tables = inspect(engine).get_table_names()
    assert "confirmed_relationship_versions" in tables
    columns = {c["name"] for c in inspect(engine).get_columns("confirmed_relationship_versions")}
    assert columns == {
        "seq",
        "analysis_id",
        "relationship_id",
        "version",
        "kind",
        "transition",
        "start_key",
        "start_ordinal",
        "end_key",
        "end_ordinal",
        "source",
        "recorded_at",
    }

    command.downgrade(config, "-1")
    remaining = inspect(engine).get_table_names()
    assert "confirmed_relationship_versions" not in remaining
    assert {"analyses", "reports"} <= set(remaining)

    command.upgrade(config, "0007")
    assert "confirmed_relationship_versions" in inspect(engine).get_table_names()
    engine.dispose()
