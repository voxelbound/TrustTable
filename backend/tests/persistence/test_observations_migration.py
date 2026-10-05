"""Migration `0008` (`DET-03` closure package 2, `WP-109`): additive,
reversible, and existing rows read back as no observations."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from trusttable_backend.config import Settings
from trusttable_backend.persistence import build_engine
from trusttable_backend.persistence.database import _BACKEND_ROOT


def _config(settings: Settings) -> Config:
    config = Config(str(_BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(_BACKEND_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", settings.database_url)
    return config


def test_migration_0008_upgrades_downgrades_and_reupgrades_cleanly(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path / 'migration.db'}",
        data_directory=str(tmp_path),
    )
    engine = build_engine(settings)
    config = _config(settings)

    command.upgrade(config, "0007")
    assert "observations_json" not in {c["name"] for c in inspect(engine).get_columns("analyses")}

    command.upgrade(config, "0008")
    columns = {c["name"]: c for c in inspect(engine).get_columns("analyses")}
    assert columns["observations_json"]["nullable"] is True

    command.downgrade(config, "-1")
    remaining = {c["name"] for c in inspect(engine).get_columns("analyses")}
    assert "observations_json" not in remaining
    assert "ai_enrichment_json" in remaining
    assert "confirmed_relationship_versions" in inspect(engine).get_table_names()

    command.upgrade(config, "0008")
    assert "observations_json" in {c["name"] for c in inspect(engine).get_columns("analyses")}
    engine.dispose()
