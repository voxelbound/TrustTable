"""Engine/session construction and migration invocation (`DB-01`).

`Settings.database_url`/`Settings.data_directory` (`FND-02`) are the only
inputs: no new `Settings` field is introduced here. For a `sqlite:///`
URL, `ensure_data_directory` creates `Settings.data_directory` before the
first connection — SQLite does not create a missing parent directory
itself, and a fresh container/host would otherwise fail on first
connect. Non-SQLite URLs (a future, disclosed possibility per
`docs/architecture.md` §8) skip directory creation entirely.

Migrations run programmatically (`run_migrations`), driven directly by
`Settings.database_url` rather than a static `alembic.ini` value or an
environment variable — this is what lets `main.create_app()` and every
test build a fully isolated database purely from `Settings`, with no
separate migrate-then-serve deploy step (recorded assumption 4,
`WP-074`).
"""

from __future__ import annotations

from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from ..config import Settings

#: `backend/alembic.ini`/`backend/alembic/` live one level above this
#: package (`backend/src/trusttable_backend/persistence/database.py` ->
#: `backend/`), mirroring `config.py`'s own `_REPO_ROOT` precedent one
#: directory shallower.
_BACKEND_ROOT = Path(__file__).resolve().parents[3]


def _is_sqlite(database_url: str) -> bool:
    return database_url.startswith("sqlite")


def ensure_data_directory(settings: Settings) -> None:
    """Create `Settings.data_directory` if missing, for a SQLite URL only.

    A no-op for any other backend — a future non-SQLite deployment owns
    its own provisioning, matching `docs/architecture.md` §8's own
    disclosed forward-compatibility note.
    """
    if _is_sqlite(settings.database_url):
        Path(settings.data_directory).mkdir(parents=True, exist_ok=True)


def build_engine(settings: Settings) -> Engine:
    """Build the SQLAlchemy 2 engine `Settings.database_url` describes.

    `ensure_data_directory` runs first so a fresh SQLite file's parent
    directory always exists before the first connection attempt.
    `check_same_thread=False` is required for SQLite because FastAPI/
    Starlette may serve a request on a different thread than the one
    that built the engine (this project's own single-process,
    single-worker deployment model, `ADR-003`/`ADR-004`, makes this
    safe: `SqlAnalysisStore` opens one short-lived `Session` per call,
    never sharing a connection across threads concurrently).
    """
    ensure_data_directory(settings)
    connect_args = {"check_same_thread": False} if _is_sqlite(settings.database_url) else {}
    return create_engine(settings.database_url, connect_args=connect_args, future=True)


def build_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Build a `Session` factory bound to `engine`.

    `expire_on_commit=False`: `SqlAnalysisStore` returns the `Analysis`
    it just wrote/read after the session's own `with` block has already
    closed the session — attribute access on now-detached ORM rows must
    not trigger an implicit (and, post-close, failing) reload.
    """
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)


def head_revision() -> str | None:
    """Return the migration head revision `backend/alembic/versions/`
    declares (`None` for an empty versions directory). Used only by
    `is_schema_ready`.
    """
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    config = Config(str(_BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(_BACKEND_ROOT / "alembic"))
    script = ScriptDirectory.from_config(config)
    return script.get_current_head()


def current_revision(engine: Engine) -> str | None:
    """Return the revision `engine`'s own database currently reports
    (`None` for an unmigrated/empty database). Used only by
    `is_schema_ready`.
    """
    from alembic.runtime.migration import MigrationContext

    with engine.connect() as connection:
        migration_context = MigrationContext.configure(connection)
        return migration_context.get_current_revision()


def is_schema_ready(engine: Engine) -> bool:
    """`True` when `engine`'s database is migrated to the current head.

    The `api.v1.health` `storage` readiness check's only decision:
    `False` for an empty/pre-migration/behind-head schema, or for any
    connection failure (never raises).
    """
    try:
        return current_revision(engine) == head_revision()
    except Exception:  # noqa: BLE001 - readiness check must never raise
        return False


def run_migrations(settings: Settings) -> None:
    """Run Alembic migrations to `head` against `Settings.database_url`.

    Programmatic invocation (`alembic.command.upgrade`), not a shell-out:
    `backend/alembic.ini`'s own `sqlalchemy.url` placeholder is always
    overridden here with the real, typed `Settings.database_url` before
    upgrading, so `alembic.ini` never needs to duplicate or fall out of
    sync with `Settings`' own default.
    """
    # Imported lazily so a process that never touches persistence (for
    # example a pure-unit-test import of an unrelated module) does not
    # pay Alembic's own import cost.
    from alembic import command
    from alembic.config import Config

    ensure_data_directory(settings)
    config = Config(str(_BACKEND_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(_BACKEND_ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", settings.database_url)
    command.upgrade(config, "head")
