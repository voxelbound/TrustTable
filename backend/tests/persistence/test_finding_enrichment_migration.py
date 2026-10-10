"""Migration `0011` (`UX-05b`, D-066 item 7): additive and reversible; it touches
no existing table, and a downgrade loses nothing durable."""

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


def test_migration_0011_adds_the_table_downgrades_and_reupgrades_cleanly(tmp_path: Path) -> None:
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path / 'migration.db'}",
        data_directory=str(tmp_path),
    )
    engine = build_engine(settings)
    config = _config(settings)

    command.upgrade(config, "0010")
    assert "finding_enrichments" not in inspect(engine).get_table_names()
    analyses_columns = {c["name"] for c in inspect(engine).get_columns("analyses")}

    command.upgrade(config, "0011")
    inspector = inspect(engine)
    columns = {c["name"]: c for c in inspector.get_columns("finding_enrichments")}
    assert set(columns) == {
        "analysis_id",
        "finding_id",
        "status",
        "binding_digest",
        "reason",
        "ai_call_status",
        "evidence_sent_to_model",
        "confirmed_context_sent_to_model",
        "result_json",
        "created_at",
        "updated_at",
    }
    assert inspector.get_pk_constraint("finding_enrichments")["constrained_columns"] == [
        "analysis_id",
        "finding_id",
    ]
    assert columns["result_json"]["nullable"] is True
    assert columns["binding_digest"]["nullable"] is False
    assert {i["name"] for i in inspector.get_indexes("finding_enrichments")} == {
        "ix_finding_enrichments_status"
    }
    # No existing table is touched.
    assert {c["name"] for c in inspector.get_columns("analyses")} == analyses_columns

    command.downgrade(config, "-1")
    assert "finding_enrichments" not in inspect(engine).get_table_names()
    assert {c["name"] for c in inspect(engine).get_columns("analyses")} == analyses_columns

    command.upgrade(config, "0011")
    assert "finding_enrichments" in inspect(engine).get_table_names()
    engine.dispose()
