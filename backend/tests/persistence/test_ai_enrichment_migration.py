"""Migration `0006` (`EXP-01` slice 4, `WP-087`): additive, reversible, and
existing rows read back as *not recorded*."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text

from trusttable_backend.analysis.service import AnalysisStore, create_analysis
from trusttable_backend.config import Settings
from trusttable_backend.persistence import SqlAnalysisStore, build_engine
from trusttable_backend.persistence.database import _BACKEND_ROOT


def _config(settings: Settings) -> Config:
    config = Config(str(_BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(_BACKEND_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", settings.database_url)
    return config


def _settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path / 'migration.db'}",
        data_directory=str(tmp_path),
    )


def test_migration_0006_upgrades_downgrades_and_reupgrades_cleanly(tmp_path: Path) -> None:
    settings = _settings(tmp_path)
    engine = build_engine(settings)
    config = _config(settings)

    command.upgrade(config, "0005")
    assert "ai_enrichment_json" not in {c["name"] for c in inspect(engine).get_columns("analyses")}

    command.upgrade(config, "0006")
    columns = {c["name"]: c for c in inspect(engine).get_columns("analyses")}
    assert columns["ai_enrichment_json"]["nullable"] is True

    command.downgrade(config, "-1")
    remaining = {c["name"] for c in inspect(engine).get_columns("analyses")}
    assert "ai_enrichment_json" not in remaining
    assert {"finding_reviews_json", "rules_json"} <= remaining
    assert "reports" in inspect(engine).get_table_names()

    command.upgrade(config, "0006")
    assert "ai_enrichment_json" in {c["name"] for c in inspect(engine).get_columns("analyses")}
    engine.dispose()


def test_a_row_written_before_the_column_existed_reads_back_as_not_recorded(
    tmp_path: Path,
) -> None:
    settings = _settings(tmp_path)
    engine = build_engine(settings)
    config = _config(settings)
    command.upgrade(config, "0006")
    store = SqlAnalysisStore(engine)
    analysis = create_analysis(AnalysisStore())
    store.add(analysis)
    with engine.begin() as connection:
        connection.execute(text("UPDATE analyses SET ai_enrichment_json = NULL"))

    loaded = store.get(analysis.analysis_id)

    assert loaded is not None
    assert loaded.ai_enrichment is None
    engine.dispose()
