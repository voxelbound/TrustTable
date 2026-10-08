"""`SqlStagingStore` and migration `0009` (`UX-02`, D-068): temporary storage of
a chosen file behind an opaque single-use reference.

These tests exercise the real SQLite store, including concurrent consumption
from several threads, because the properties that matter (one consume wins, the
bounds cannot be raced past) are properties of single SQL statements.
"""

from __future__ import annotations

import hashlib
import threading
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import func, inspect, select, text
from sqlalchemy.engine import Engine

from trusttable_backend.config import Settings
from trusttable_backend.persistence import (
    SqlStagingStore,
    StagingFullError,
    build_engine,
    build_session_factory,
    reference_digest,
    run_migrations,
)
from trusttable_backend.persistence.database import _BACKEND_ROOT
from trusttable_backend.persistence.models import StagedUploadRecord

_CSV = b"id,name\n1,Ada\n2,Grace\n"


class _Clock:
    """A settable clock so expiry is tested without sleeping."""

    def __init__(self) -> None:
        self.now = datetime(2026, 10, 8, 12, 0, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, **kwargs: int) -> None:
        self.now += timedelta(**kwargs)


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path / 'staging.db'}",
        data_directory=str(tmp_path),
    )


@pytest.fixture
def engine(tmp_path: Path) -> Iterator[Engine]:
    settings = _settings(tmp_path)
    built = build_engine(settings)
    run_migrations(settings)
    yield built
    built.dispose()


def _store(
    engine: Engine,
    clock: _Clock | None = None,
    *,
    max_count: int = 3,
    max_total_bytes: int = 1000,
    ttl_minutes: int = 60,
) -> SqlStagingStore:
    return SqlStagingStore(
        engine,
        max_count=max_count,
        max_total_bytes=max_total_bytes,
        ttl=timedelta(minutes=ttl_minutes),
        clock=clock or _Clock(),
    )


def _row_count(engine: Engine) -> int:
    with build_session_factory(engine)() as session:
        return int(session.scalar(select(func.count()).select_from(StagedUploadRecord)) or 0)


# --- migration 0009 ---------------------------------------------------------


def test_migration_0009_creates_the_table_and_is_reversible(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    engine = build_engine(settings)
    config = Config(str(_BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(_BACKEND_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", settings.database_url)

    command.upgrade(config, "0008")
    assert "staged_uploads" not in inspect(engine).get_table_names()

    command.upgrade(config, "0009")
    inspector = inspect(engine)
    assert "staged_uploads" in inspector.get_table_names()
    columns = {column["name"] for column in inspector.get_columns("staged_uploads")}
    assert columns == {
        "ref_digest",
        "created_at",
        "expires_at",
        "filename",
        "format",
        "byte_size",
        "content_sha256",
        "content",
    }
    assert inspector.get_pk_constraint("staged_uploads")["constrained_columns"] == ["ref_digest"]

    command.downgrade(config, "-1")
    after = inspect(engine)
    assert "staged_uploads" not in after.get_table_names()
    assert "analyses" in after.get_table_names()
    assert "reports" in after.get_table_names()

    command.upgrade(config, "0009")
    assert "staged_uploads" in inspect(engine).get_table_names()
    engine.dispose()


# --- staging and reading ----------------------------------------------------


def test_stage_returns_an_unguessable_reference_and_stores_only_its_digest(
    engine: Engine,
) -> None:
    store = _store(engine)

    reference, staged = store.stage(filename="data.csv", file_format="csv", content=_CSV)

    assert len(reference) == 43
    assert staged.content_sha256 == hashlib.sha256(_CSV).hexdigest()
    digest = reference_digest(reference)
    assert digest is not None
    with build_session_factory(engine)() as session:
        row = session.scalars(select(StagedUploadRecord)).one()
        assert row.ref_digest == digest
        assert row.ref_digest != reference
        # The reference itself appears nowhere in the stored row.
        stored_text = " ".join(
            str(value) for value in (row.ref_digest, row.filename, row.format, row.content_sha256)
        )
        assert reference not in stored_text
        assert reference.encode("ascii") not in row.content


def test_two_references_are_different_and_independent(engine: Engine) -> None:
    store = _store(engine)

    first, _ = store.stage(filename="a.csv", file_format="csv", content=b"a\n1\n")
    second, _ = store.stage(filename="b.csv", file_format="csv", content=b"b\n2\n")

    assert first != second
    peeked = store.peek(first)
    assert peeked is not None and peeked.filename == "a.csv"
    other = store.peek(second)
    assert other is not None and other.filename == "b.csv"


def test_peek_returns_the_staged_bytes_without_consuming_them(engine: Engine) -> None:
    store = _store(engine)
    reference, _ = store.stage(filename="data.csv", file_format="csv", content=_CSV)

    first = store.peek(reference)
    second = store.peek(reference)

    assert first is not None and first.content == _CSV
    assert second is not None and second.content == _CSV
    assert _row_count(engine) == 1


@pytest.mark.parametrize(
    "bad",
    [
        "",
        "short",
        "a" * 42,
        "a" * 44,
        "a" * 42 + "!",
        "a" * 42 + " ",
        "../" + "a" * 40,
        "a" * 42 + "\n",
        "é" * 43,
        "' OR 1=1 --" + "a" * 32,
    ],
)
def test_a_malformed_reference_is_unavailable_everywhere_and_never_reaches_the_database(
    engine: Engine, bad: str
) -> None:
    store = _store(engine)
    store.stage(filename="data.csv", file_format="csv", content=_CSV)

    assert reference_digest(bad) is None
    assert store.peek(bad) is None
    assert store.consume(bad, content_sha256=hashlib.sha256(_CSV).hexdigest()) is None
    store.discard(bad)
    assert _row_count(engine) == 1


def test_an_unknown_well_formed_reference_is_unavailable(engine: Engine) -> None:
    store = _store(engine)
    unknown = "A" * 43

    assert store.peek(unknown) is None
    assert store.consume(unknown, content_sha256="0" * 64) is None


# --- consume: single use, integrity ----------------------------------------


def test_consume_returns_the_bytes_once_and_a_second_consume_gets_nothing(
    engine: Engine,
) -> None:
    store = _store(engine)
    reference, staged = store.stage(filename="data.csv", file_format="csv", content=_CSV)

    first = store.consume(reference, content_sha256=staged.content_sha256)
    second = store.consume(reference, content_sha256=staged.content_sha256)

    assert first is not None and first.content == _CSV
    assert second is None
    assert store.peek(reference) is None
    assert _row_count(engine) == 0


def test_consume_requires_the_recorded_content_digest(engine: Engine) -> None:
    store = _store(engine)
    reference, staged = store.stage(filename="data.csv", file_format="csv", content=_CSV)

    wrong = hashlib.sha256(b"something else").hexdigest()

    assert store.consume(reference, content_sha256=wrong) is None
    # A refused consume does not spend the reference.
    again = store.consume(reference, content_sha256=staged.content_sha256)
    assert again is not None and again.content == _CSV


def test_exactly_one_of_many_concurrent_consumers_obtains_the_file(engine: Engine) -> None:
    store = _store(engine)
    reference, staged = store.stage(filename="data.csv", file_format="csv", content=_CSV)
    workers = 12
    barrier = threading.Barrier(workers)
    results: list[object] = []
    lock = threading.Lock()

    def consume() -> None:
        barrier.wait()
        outcome = store.consume(reference, content_sha256=staged.content_sha256)
        with lock:
            results.append(outcome)

    threads = [threading.Thread(target=consume) for _ in range(workers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    winners = [outcome for outcome in results if outcome is not None]
    assert len(results) == workers
    assert len(winners) == 1
    assert _row_count(engine) == 0


# --- discard ----------------------------------------------------------------


def test_discard_removes_the_file_and_is_silent_when_it_is_absent(engine: Engine) -> None:
    store = _store(engine)
    reference, _ = store.stage(filename="data.csv", file_format="csv", content=_CSV)

    store.discard(reference)
    store.discard(reference)
    store.discard("B" * 43)

    assert store.peek(reference) is None
    assert _row_count(engine) == 0


# --- expiry -----------------------------------------------------------------


def test_a_staged_file_is_available_until_its_expiry_and_gone_after(engine: Engine) -> None:
    clock = _Clock()
    store = _store(engine, clock, ttl_minutes=60)
    reference, staged = store.stage(filename="data.csv", file_format="csv", content=_CSV)
    assert staged.expires_at == clock.now + timedelta(minutes=60)

    clock.advance(minutes=59, seconds=59)
    assert store.peek(reference) is not None

    clock.advance(seconds=1)
    assert store.peek(reference) is None
    assert _row_count(engine) == 0


def test_consume_refuses_an_expired_file_even_if_nothing_purged_it_yet(engine: Engine) -> None:
    clock = _Clock()
    store = _store(engine, clock, ttl_minutes=1)
    reference, staged = store.stage(filename="data.csv", file_format="csv", content=_CSV)

    clock.advance(minutes=2)

    # Straight to consume, with no read in between that would purge it first.
    assert store.consume(reference, content_sha256=staged.content_sha256) is None


def test_peek_does_not_extend_the_expiry(engine: Engine) -> None:
    clock = _Clock()
    store = _store(engine, clock, ttl_minutes=10)
    reference, staged = store.stage(filename="data.csv", file_format="csv", content=_CSV)

    clock.advance(minutes=9)
    again = store.peek(reference)
    assert again is not None and again.expires_at == staged.expires_at

    clock.advance(minutes=2)
    assert store.peek(reference) is None


def test_purge_expired_deletes_only_expired_rows_and_reports_how_many(engine: Engine) -> None:
    clock = _Clock()
    store = _store(engine, clock, ttl_minutes=30)
    old, _ = store.stage(filename="old.csv", file_format="csv", content=b"a\n1\n")
    clock.advance(minutes=20)
    fresh, _ = store.stage(filename="fresh.csv", file_format="csv", content=b"b\n2\n")
    clock.advance(minutes=15)

    assert store.purge_expired() == 1

    assert store.peek(old) is None
    assert store.peek(fresh) is not None


def test_expired_rows_are_purged_before_a_new_file_is_staged(engine: Engine) -> None:
    clock = _Clock()
    store = _store(engine, clock, max_count=1, ttl_minutes=5)
    store.stage(filename="a.csv", file_format="csv", content=b"a\n1\n")
    clock.advance(minutes=6)

    # The only slot is held by an expired file; staging reclaims it.
    reference, _ = store.stage(filename="b.csv", file_format="csv", content=b"b\n2\n")

    assert store.peek(reference) is not None
    assert _row_count(engine) == 1


# --- bounds -----------------------------------------------------------------


def test_the_count_bound_refuses_the_file_over_the_limit_and_stores_nothing(
    engine: Engine,
) -> None:
    store = _store(engine, max_count=2)
    store.stage(filename="1.csv", file_format="csv", content=b"a\n1\n")
    store.stage(filename="2.csv", file_format="csv", content=b"a\n2\n")

    with pytest.raises(StagingFullError):
        store.stage(filename="3.csv", file_format="csv", content=b"a\n3\n")

    assert _row_count(engine) == 2


def test_the_total_bytes_bound_counts_every_staged_file(engine: Engine) -> None:
    store = _store(engine, max_count=10, max_total_bytes=100)
    store.stage(filename="a.csv", file_format="csv", content=b"x" * 60)

    with pytest.raises(StagingFullError):
        store.stage(filename="b.csv", file_format="csv", content=b"y" * 41)
    store.stage(filename="c.csv", file_format="csv", content=b"z" * 40)  # exactly at the bound

    assert _row_count(engine) == 2


def test_a_consumed_or_discarded_file_frees_its_slot_and_bytes(engine: Engine) -> None:
    store = _store(engine, max_count=1, max_total_bytes=50)
    reference, staged = store.stage(filename="a.csv", file_format="csv", content=b"x" * 50)
    with pytest.raises(StagingFullError):
        store.stage(filename="b.csv", file_format="csv", content=b"y")

    store.consume(reference, content_sha256=staged.content_sha256)

    store.stage(filename="b.csv", file_format="csv", content=b"y" * 50)


def test_the_bounds_cannot_be_raced_past_by_concurrent_stagings(engine: Engine) -> None:
    store = _store(engine, max_count=3, max_total_bytes=10_000)
    workers = 12
    barrier = threading.Barrier(workers)
    outcomes: list[str] = []
    lock = threading.Lock()

    def stage(index: int) -> None:
        barrier.wait()
        try:
            store.stage(filename=f"{index}.csv", file_format="csv", content=b"a\n1\n")
            result = "stored"
        except StagingFullError:
            result = "full"
        with lock:
            outcomes.append(result)

    threads = [threading.Thread(target=stage, args=(index,)) for index in range(workers)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert outcomes.count("stored") == 3
    assert outcomes.count("full") == workers - 3
    assert _row_count(engine) == 3


def test_invalid_bounds_are_rejected_at_construction(engine: Engine) -> None:
    for kwargs in (
        {"max_count": 0},
        {"max_total_bytes": 0},
        {"ttl_minutes": 0},
    ):
        with pytest.raises(ValueError, match="positive"):
            _store(engine, **kwargs)  # type: ignore[arg-type]


# --- deletion is secure -----------------------------------------------------


def test_secure_delete_is_enabled_so_freed_staged_bytes_are_zeroed(engine: Engine) -> None:
    with engine.connect() as connection:
        assert connection.execute(text("PRAGMA secure_delete")).scalar() == 1


def test_the_stored_expiry_strings_order_in_time_even_across_microsecond_boundaries(
    engine: Engine,
) -> None:
    clock = _Clock()
    store = _store(engine, clock, ttl_minutes=1)
    _, first = store.stage(filename="a.csv", file_format="csv", content=b"a\n1\n")
    clock.now += timedelta(microseconds=1)
    _, second = store.stage(filename="b.csv", file_format="csv", content=b"b\n2\n")

    with build_session_factory(engine)() as session:
        stored = [
            row.expires_at
            for row in session.scalars(
                select(StagedUploadRecord).order_by(StagedUploadRecord.expires_at)
            )
        ]
    assert first.expires_at < second.expires_at
    assert stored == sorted(stored)
    # Always microsecond-precise, so lexicographic order is chronological order.
    assert all("." in value for value in stored)
