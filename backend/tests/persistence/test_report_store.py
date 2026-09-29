"""`SqlReportStore` and migration `0005` (`EXP-01` slice 3, `WP-086`)."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import inspect, text

from trusttable_backend.config import Settings
from trusttable_backend.exports.report_snapshot import (
    REPORT_SCHEMA_VERSION,
    ReportOptions,
    ReportSnapshot,
)
from trusttable_backend.persistence import SqlReportStore, build_engine, run_migrations


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path / 'reports.db'}",
        data_directory=str(tmp_path),
    )


def _snapshot(report_id: str, analysis_id: str = "a1", body: str = "# Report\n") -> ReportSnapshot:
    return ReportSnapshot(
        report_id=report_id,
        analysis_id=analysis_id,
        generated_at=datetime(2026, 9, 29, 12, 0, 0, 123456, tzinfo=UTC),
        options=ReportOptions(include_dismissed=True, include_bounded_examples=True),
        schema_version=REPORT_SCHEMA_VERSION,
        markdown=body,
        content_sha256=hashlib.sha256(body.encode("utf-8")).hexdigest(),
    )


def _store(tmp_path: Path) -> SqlReportStore:
    settings = _settings(tmp_path)
    engine = build_engine(settings)
    run_migrations(settings)
    return SqlReportStore(engine)


def test_round_trip_preserves_every_field(tmp_path: Path) -> None:
    store = _store(tmp_path)
    original = _snapshot("r1", body="# Réport ✓\n\nunicode stays exact\n")

    store.add(original)

    assert store.get("a1", "r1") == original


def test_get_is_scoped_to_the_analysis(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.add(_snapshot("r1", "a1"))

    assert store.get("a2", "r1") is None
    assert store.get("a1", "missing") is None


def test_list_is_in_insertion_order_per_analysis(tmp_path: Path) -> None:
    store = _store(tmp_path)
    for report_id in ("zz", "aa", "mm"):
        store.add(_snapshot(report_id, "a1"))
    store.add(_snapshot("other", "a2"))

    assert [s.report_id for s in store.list_for_analysis("a1")] == ["zz", "aa", "mm"]
    assert [s.report_id for s in store.list_for_analysis("a2")] == ["other"]
    assert store.list_for_analysis("none") == ()


def test_duplicate_report_id_is_rejected_not_overwritten(tmp_path: Path) -> None:
    store = _store(tmp_path)
    store.add(_snapshot("r1", body="first\n"))

    with pytest.raises(Exception, match="UNIQUE|unique|Integrity"):
        store.add(_snapshot("r1", body="second\n"))

    assert store.get("a1", "r1") == _snapshot("r1", body="first\n")


def test_a_corrupted_row_raises_instead_of_being_served(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    engine = build_engine(settings)
    run_migrations(settings)
    store = SqlReportStore(engine)
    store.add(_snapshot("r1"))

    with engine.begin() as connection:
        connection.execute(text("UPDATE reports SET markdown = 'tampered' WHERE report_id = 'r1'"))

    with pytest.raises(ValueError, match="content_sha256"):
        store.get("a1", "r1")


def test_migration_0005_upgrades_downgrades_and_reupgrades_cleanly(tmp_path: Path) -> None:
    from alembic import command
    from alembic.config import Config

    from trusttable_backend.persistence.database import _BACKEND_ROOT

    settings = _settings(tmp_path)
    engine = build_engine(settings)
    config = Config(str(_BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(_BACKEND_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", settings.database_url)

    command.upgrade(config, "0004")
    assert "reports" not in inspect(engine).get_table_names()

    command.upgrade(config, "0005")
    assert "reports" in inspect(engine).get_table_names()
    assert {index["name"] for index in inspect(engine).get_indexes("reports")} >= {
        "ix_reports_analysis_id"
    }

    command.downgrade(config, "-1")
    inspector = inspect(engine)
    assert "reports" not in inspector.get_table_names()
    assert "analyses" in inspector.get_table_names()

    command.upgrade(config, "0005")
    assert "reports" in inspect(engine).get_table_names()
