"""Tests for `persistence.database` (`DB-01`, `WP-074` AC-06)."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import inspect, text

from trusttable_backend.config import Settings
from trusttable_backend.persistence import (
    build_engine,
    build_session_factory,
    ensure_data_directory,
    is_schema_ready,
    run_migrations,
)
from trusttable_backend.persistence.database import current_revision, head_revision


def _settings(tmp_path: Path, name: str = "trusttable.db") -> Settings:
    return Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path / name}",
        data_directory=str(tmp_path),
    )


def test_ensure_data_directory_creates_a_missing_directory(tmp_path: Path) -> None:
    missing = tmp_path / "nested" / "data"
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite:///{missing / 'trusttable.db'}",
        data_directory=str(missing),
    )

    assert not missing.exists()
    ensure_data_directory(settings)
    assert missing.is_dir()


def test_ensure_data_directory_is_idempotent(tmp_path: Path) -> None:
    settings = _settings(tmp_path)

    ensure_data_directory(settings)
    ensure_data_directory(settings)  # must not raise on an already-existing directory

    assert tmp_path.is_dir()


def test_build_engine_creates_a_connectable_sqlite_engine(tmp_path: Path) -> None:
    settings = _settings(tmp_path)

    engine = build_engine(settings)

    with engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT 1").scalar() == 1


def test_build_session_factory_returns_working_sessions(tmp_path: Path) -> None:
    engine = build_engine(_settings(tmp_path))
    factory = build_session_factory(engine)

    with factory() as session:
        assert session.execute(text("SELECT 1")).scalar() == 1


def test_run_migrations_creates_the_analyses_table(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    engine = build_engine(settings)

    run_migrations(settings)

    inspector = inspect(engine)
    assert "analyses" in inspector.get_table_names()


def test_run_migrations_is_idempotent(tmp_path: Path) -> None:
    settings = _settings(tmp_path)

    run_migrations(settings)
    run_migrations(settings)  # must not raise re-applying an already-current schema


def test_head_revision_matches_current_revision_after_migration(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    engine = build_engine(settings)

    run_migrations(settings)

    assert head_revision() is not None
    assert current_revision(engine) == head_revision()


def test_is_schema_ready_false_before_migration_true_after(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    engine = build_engine(settings)

    assert is_schema_ready(engine) is False

    run_migrations(settings)

    assert is_schema_ready(engine) is True


def test_is_schema_ready_false_for_unreachable_database() -> None:
    from sqlalchemy import create_engine

    # A malformed, never-connectable URL for this driver: `is_schema_ready`
    # must report `False`, never raise.
    engine = create_engine("sqlite:////this/path/does/not/exist/trusttable.db")

    assert is_schema_ready(engine) is False
