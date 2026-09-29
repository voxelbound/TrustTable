"""`SqlAnalysisStore.delete` and the guarded report insert (`DEL-01`)."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Engine

from trusttable_backend.analysis.service import AnalysisStore, create_analysis
from trusttable_backend.config import Settings
from trusttable_backend.exports.report_snapshot import (
    REPORT_SCHEMA_VERSION,
    ReportOptions,
    ReportSnapshot,
)
from trusttable_backend.persistence import (
    SqlAnalysisStore,
    SqlReportStore,
    build_engine,
    run_migrations,
)


def _engine(tmp_path: Path) -> Engine:
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path / 'delete.db'}",
        data_directory=str(tmp_path),
    )
    engine = build_engine(settings)
    run_migrations(settings)
    return engine


def _snapshot(report_id: str, analysis_id: str) -> ReportSnapshot:
    body = f"# {report_id}\n"
    return ReportSnapshot(
        report_id=report_id,
        analysis_id=analysis_id,
        generated_at=datetime(2026, 9, 29, tzinfo=UTC),
        options=ReportOptions(),
        schema_version=REPORT_SCHEMA_VERSION,
        markdown=body,
        content_sha256=hashlib.sha256(body.encode("utf-8")).hexdigest(),
    )


def _count(engine: Engine, table: str) -> int:
    with engine.connect() as connection:
        return int(connection.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one())  # noqa: S608


def test_delete_removes_the_analysis_and_all_of_its_reports_and_no_others(
    tmp_path: Path,
) -> None:
    engine = _engine(tmp_path)
    analyses, reports = SqlAnalysisStore(engine), SqlReportStore(engine)
    template = create_analysis(AnalysisStore())
    for analysis_id in ("doomed", "kept"):
        analyses.add(replace(template, analysis_id=analysis_id))
    assert reports.add(_snapshot("d1", "doomed"))
    assert reports.add(_snapshot("d2", "doomed"))
    assert reports.add(_snapshot("k1", "kept"))

    assert analyses.delete("doomed") is True

    assert analyses.get("doomed") is None
    assert reports.list_for_analysis("doomed") == ()
    assert analyses.get("kept") is not None
    assert [s.report_id for s in reports.list_for_analysis("kept")] == ["k1"]
    assert (_count(engine, "analyses"), _count(engine, "reports")) == (1, 1)


def test_delete_of_an_unknown_analysis_reports_false_and_changes_nothing(
    tmp_path: Path,
) -> None:
    engine = _engine(tmp_path)
    analyses, reports = SqlAnalysisStore(engine), SqlReportStore(engine)
    analyses.add(replace(create_analysis(AnalysisStore()), analysis_id="kept"))
    reports.add(_snapshot("k1", "kept"))

    assert analyses.delete("missing") is False

    assert (_count(engine, "analyses"), _count(engine, "reports")) == (1, 1)


def test_a_report_is_never_stored_for_an_analysis_that_does_not_exist(
    tmp_path: Path,
) -> None:
    engine = _engine(tmp_path)
    analyses, reports = SqlAnalysisStore(engine), SqlReportStore(engine)
    analyses.add(replace(create_analysis(AnalysisStore()), analysis_id="gone"))
    analyses.delete("gone")

    assert reports.add(_snapshot("late", "gone")) is False
    assert reports.add(_snapshot("never", "never-existed")) is False

    assert _count(engine, "reports") == 0


def test_secure_delete_is_on_for_every_connection(tmp_path: Path) -> None:
    engine = _engine(tmp_path)

    for _ in range(3):
        with engine.connect() as connection:
            assert connection.execute(text("PRAGMA secure_delete")).scalar_one() != 0
