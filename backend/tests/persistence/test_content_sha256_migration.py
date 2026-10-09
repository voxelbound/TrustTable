"""Migration `0010` (`UX-03`, D-069): additive, reversible, and existing rows are
backfilled so the lookup also recognises analyses created before it."""

from __future__ import annotations

import hashlib
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text

from trusttable_backend.config import Settings
from trusttable_backend.persistence import build_engine
from trusttable_backend.persistence.database import _BACKEND_ROOT


def _config(settings: Settings) -> Config:
    config = Config(str(_BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(_BACKEND_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", settings.database_url)
    return config


def test_migration_0010_backfills_upgrades_downgrades_and_reupgrades_cleanly(
    tmp_path: Path,
) -> None:
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path / 'migration.db'}",
        data_directory=str(tmp_path),
    )
    engine = build_engine(settings)
    config = _config(settings)
    content = b"id,name\n1,Ada\n"

    command.upgrade(config, "0009")
    assert "content_sha256" not in {c["name"] for c in inspect(engine).get_columns("analyses")}
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO analyses (analysis_id, state, created_at, content, dataset_json, "
                "security_exposure_json, findings_json, priority_scores_json, evidence_json, "
                "guided_questions_json, context_version, context_finalized) "
                "VALUES ('old', 'completed', '2026-01-01T00:00:00+00:00', :content, '{}', '{}', "
                "'{}', '{}', '{}', '{}', 0, 0)"
            ),
            {"content": content},
        )

    command.upgrade(config, "0010")
    inspector = inspect(engine)
    columns = {c["name"]: c for c in inspector.get_columns("analyses")}
    assert columns["content_sha256"]["nullable"] is True
    index_names = {i["name"] for i in inspector.get_indexes("analyses")}
    assert {"ix_analyses_content_sha256", "ix_analyses_created_at"} <= index_names
    with engine.connect() as connection:
        digest = connection.execute(
            text("SELECT content_sha256 FROM analyses WHERE analysis_id = 'old'")
        ).scalar()
    assert digest == hashlib.sha256(content).hexdigest()

    command.downgrade(config, "-1")
    inspector = inspect(engine)
    assert "content_sha256" not in {c["name"] for c in inspector.get_columns("analyses")}
    assert "ix_analyses_content_sha256" not in {
        i["name"] for i in inspector.get_indexes("analyses")
    }
    assert "staged_uploads" in inspector.get_table_names()

    command.upgrade(config, "0010")
    assert "content_sha256" in {c["name"] for c in inspect(engine).get_columns("analyses")}
    engine.dispose()
